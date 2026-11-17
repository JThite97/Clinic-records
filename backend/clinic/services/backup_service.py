"""Encrypted backups and restore.

Archive format (``clinic-backup-YYYYmmdd-HHMMSS-<reason>.crbak``)
------------------------------------------------------------------
An AES-256 encrypted zip (WinZip AES, via pyzipper) whose password is the
clinic data key. It contains:

* ``clinic.db``        a consistent online copy of the SQLCipher database
* ``documents/...``    every stored attachment and letterhead image
* ``manifest.json``    creation time, app version, SHA-256 of every file

The zip *comment* holds the keystore (base64 JSON). Keystore entries are
already encrypted with each user's password, so it is safe in the clear, and
it lets a backup be restored on a new computer with the usual login.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import pyzipper
import sqlcipher3

from ..config import APP_VERSION
from ..security import Keystore, KeystoreError

log = logging.getLogger(__name__)

SUFFIX = ".crbak"
REASONS = ("manual", "auto", "pre-restore")


class BackupError(Exception):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _password(key: bytes) -> bytes:
    return key.hex().encode("ascii")


def _online_copy(db_file: Path, key: bytes, dest: Path) -> None:
    """Page-level copy via the SQLite backup API (safe while the app runs)."""
    src = sqlcipher3.connect(str(db_file))
    dst = sqlcipher3.connect(str(dest))
    try:
        for c in (src, dst):
            c.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _integrity_ok(db_file: Path, key: bytes) -> bool:
    c = sqlcipher3.connect(str(db_file))
    try:
        c.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
        res = c.execute("PRAGMA integrity_check").fetchone()
        return bool(res) and res[0] == "ok"
    except sqlcipher3.DatabaseError:
        return False
    finally:
        c.close()


class BackupService:
    _lock = threading.Lock()

    def __init__(self, paths, keystore: Keystore):
        self.paths = paths
        self.keystore = keystore

    # -- create ------------------------------------------------------------
    def create_backup(self, key: bytes, reason: str = "manual") -> Path:
        if reason not in REASONS:
            reason = "manual"
        with self._lock:
            self.paths.backups.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"clinic-backup-{stamp}-{reason}{SUFFIX}"
            dest = self.paths.backups / name
            n = 1
            while dest.exists():
                dest = self.paths.backups / f"clinic-backup-{stamp}-{reason}-{n}{SUFFIX}"
                n += 1
            tmpdir = Path(tempfile.mkdtemp(prefix="clinic-bak-"))
            part = dest.with_suffix(".part")
            try:
                db_copy = tmpdir / "clinic.db"
                _online_copy(self.paths.db_file, key, db_copy)
                files: dict[str, str] = {"clinic.db": _sha256(db_copy)}
                docs = [p for p in self.paths.documents.rglob("*") if p.is_file() and not p.name.endswith(".part")]
                for p in docs:
                    files["documents/" + p.relative_to(self.paths.documents).as_posix()] = _sha256(p)
                manifest = {
                    "format": 1,
                    "app_version": APP_VERSION,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "reason": reason,
                    "files": files,
                }
                with pyzipper.AESZipFile(part, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
                    zf.setpassword(_password(key))
                    zf.setencryption(pyzipper.WZ_AES, nbits=256)
                    zf.write(db_copy, "clinic.db")
                    for p in docs:
                        zf.write(p, "documents/" + p.relative_to(self.paths.documents).as_posix())
                    zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                    zf.comment = base64.b64encode(json.dumps(self.keystore.raw()).encode("utf-8"))
                os.replace(part, dest)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
                if part.exists():
                    part.unlink()
            log.info("backup created %s (%d files)", dest.name, len(files))
            return dest

    # -- list / prune ------------------------------------------------------
    def list_backups(self) -> list[dict]:
        out = []
        for p in sorted(self.paths.backups.glob(f"*{SUFFIX}"), key=lambda x: x.stat().st_mtime, reverse=True):
            reason = next((r for r in REASONS if f"-{r}" in p.stem), "manual")
            st = p.stat()
            out.append({"name": p.name, "size_bytes": st.st_size, "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"), "reason": reason})
        return out

    def prune(self, keep: int) -> list[str]:
        """Keep the newest ``keep`` regular backups and the newest 5 pre-restore snapshots."""
        removed = []
        regular = [b for b in self.list_backups() if b["reason"] != "pre-restore"]
        snaps = [b for b in self.list_backups() if b["reason"] == "pre-restore"]
        for b in regular[max(keep, 1):] + snaps[5:]:
            (self.paths.backups / b["name"]).unlink(missing_ok=True)
            removed.append(b["name"])
        if removed:
            log.info("pruned %d old backups", len(removed))
        return removed

    def resolve(self, name: str) -> Path:
        p = (self.paths.backups / Path(name).name)
        if not p.exists() or p.suffix != SUFFIX:
            raise BackupError("backup not found")
        return p

    def last_backup_age_hours(self) -> float | None:
        b = [x for x in self.list_backups() if x["reason"] != "pre-restore"]
        if not b:
            return None
        return (time.time() - (self.paths.backups / b[0]["name"]).stat().st_mtime) / 3600

    # -- verify ------------------------------------------------------------
    @staticmethod
    def read_keystore(archive: Path) -> dict:
        with pyzipper.AESZipFile(archive) as zf:
            if not zf.comment:
                raise BackupError("archive has no keystore")
            return json.loads(base64.b64decode(zf.comment))

    @staticmethod
    def key_from_archive(archive: Path, username: str, password: str) -> bytes:
        ks = Keystore.from_raw(BackupService.read_keystore(archive))
        try:
            return ks.unwrap(username, password)
        except KeystoreError as e:
            raise BackupError("username or password does not match this backup") from e

    def verify_backup(self, archive: Path, key: bytes) -> dict:
        """Decrypt every entry, check SHA-256 against the manifest and run an
        integrity check on the database copy."""
        tmpdir = Path(tempfile.mkdtemp(prefix="clinic-verify-"))
        try:
            try:
                with pyzipper.AESZipFile(archive) as zf:
                    zf.setpassword(_password(key))
                    manifest = json.loads(zf.read("manifest.json"))
                    bad = zf.testzip()
                    if bad:
                        return {"ok": False, "reason": f"corrupt entry {bad}"}
                    for name, digest in manifest["files"].items():
                        h = hashlib.sha256()
                        with zf.open(name) as f:
                            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                                h.update(chunk)
                        if h.hexdigest() != digest:
                            return {"ok": False, "reason": f"checksum mismatch {name}"}
                    zf.extract("clinic.db", tmpdir)
            except RuntimeError as e:  # bad password
                return {"ok": False, "reason": "wrong key", "detail": str(e)}
            except (KeyError, ValueError, pyzipper.BadZipFile) as e:
                return {"ok": False, "reason": "not a valid backup", "detail": str(e)}
            if not _integrity_ok(tmpdir / "clinic.db", key):
                return {"ok": False, "reason": "database integrity check failed"}
            return {"ok": True, "files": len(manifest["files"]), "created_at": manifest.get("created_at"), "app_version": manifest.get("app_version")}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # -- restore -----------------------------------------------------------
    def restore(self, archive: Path, key: bytes) -> None:
        """Replace the database, documents and keystore with the archive's.

        The caller must close the database first and should take a
        pre-restore snapshot. Files are swapped in only after the whole
        archive verified, and the previous state is rolled back on error.
        """
        check = self.verify_backup(archive, key)
        if not check["ok"]:
            raise BackupError(f"backup failed verification: {check['reason']}")
        keystore_raw = self.read_keystore(archive)
        stage = Path(tempfile.mkdtemp(prefix="clinic-restore-", dir=self.paths.home))
        old = Path(tempfile.mkdtemp(prefix="clinic-old-", dir=self.paths.home))
        try:
            with pyzipper.AESZipFile(archive) as zf:
                zf.setpassword(_password(key))
                zf.extractall(stage)
            # Move current state aside.
            for suffix in ("", "-wal", "-shm"):
                f = Path(str(self.paths.db_file) + suffix)
                if f.exists():
                    shutil.move(str(f), old / f.name)
            if self.paths.documents.exists():
                shutil.move(str(self.paths.documents), old / "documents")
            if self.paths.keystore_file.exists():
                shutil.copy2(self.paths.keystore_file, old / "keystore.json")
            try:
                self.paths.data.mkdir(parents=True, exist_ok=True)
                shutil.move(str(stage / "clinic.db"), self.paths.db_file)
                if (stage / "documents").exists():
                    shutil.move(str(stage / "documents"), self.paths.documents)
                else:
                    self.paths.documents.mkdir(parents=True, exist_ok=True)
                tmp = self.paths.keystore_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(keystore_raw, indent=2), "utf-8")
                os.replace(tmp, self.paths.keystore_file)
            except Exception:
                log.exception("restore failed; rolling back")
                self.paths.db_file.unlink(missing_ok=True)
                shutil.rmtree(self.paths.documents, ignore_errors=True)
                for f in old.iterdir():
                    target = self.paths.documents if f.name == "documents" else (
                        self.paths.keystore_file if f.name == "keystore.json" else self.paths.data / f.name)
                    shutil.move(str(f), target)
                raise
            log.info("restored from %s", archive.name)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(old, ignore_errors=True)
