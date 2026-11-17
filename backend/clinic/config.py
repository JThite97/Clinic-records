"""Application paths and runtime settings.

All runtime data lives under one "clinic home" folder:

    <home>/data/        clinic.db (SQLCipher), keystore.json, settings.json
    <home>/documents/   patient attachments, logo/signature images
    <home>/backups/     AES-256 encrypted backup archives
    <home>/logs/        clinic.log (rotating)
    <home>/exports/     PDFs written for printing / opening

The home folder defaults to %APPDATA%\\ClinicRecords on Windows and
~/.clinic-records elsewhere, and can be overridden with CLINIC_HOME.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP_NAME = "Clinic Records"
APP_VERSION = "1.0.0"
DEFAULT_PORT = 8000


def default_home() -> Path:
    env = os.environ.get("CLINIC_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "ClinicRecords"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ClinicRecords"
    return Path.home() / ".clinic-records"


@dataclass
class Paths:
    home: Path

    @property
    def data(self) -> Path:
        return self.home / "data"

    @property
    def documents(self) -> Path:
        return self.home / "documents"

    @property
    def backups(self) -> Path:
        return self.home / "backups"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def exports(self) -> Path:
        return self.home / "exports"

    @property
    def db_file(self) -> Path:
        return self.data / "clinic.db"

    @property
    def keystore_file(self) -> Path:
        return self.data / "keystore.json"

    @property
    def settings_file(self) -> Path:
        return self.data / "settings.json"

    @property
    def log_file(self) -> Path:
        return self.logs / "clinic.log"

    def ensure(self) -> None:
        for p in (self.data, self.documents, self.backups, self.logs, self.exports):
            p.mkdir(parents=True, exist_ok=True)


@dataclass
class RuntimeSettings:
    """Machine-level settings that must be readable before the DB is unlocked.

    Clinic details (name, doctor, letterhead) live inside the encrypted DB;
    this file only holds things the server needs at start-up.
    """

    port: int = DEFAULT_PORT
    # When true the server binds 0.0.0.0 so a phone on the Tailscale network
    # can reach the read-only mobile view and the sync endpoints.
    network_access: bool = False
    backup_retention: int = 30
    auto_backup_hours: int = 24
    session_hours: int = 12
    extra: dict = field(default_factory=dict)


class SettingsStore:
    _lock = threading.Lock()

    def __init__(self, paths: Paths):
        self.paths = paths

    def load(self) -> RuntimeSettings:
        f = self.paths.settings_file
        if not f.exists():
            return RuntimeSettings()
        try:
            raw = json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            return RuntimeSettings()
        known = {k: raw[k] for k in RuntimeSettings.__dataclass_fields__ if k in raw}
        return RuntimeSettings(**known)

    def save(self, s: RuntimeSettings) -> None:
        with self._lock:
            self.paths.data.mkdir(parents=True, exist_ok=True)
            tmp = self.paths.settings_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(s), indent=2), "utf-8")
            os.replace(tmp, self.paths.settings_file)
