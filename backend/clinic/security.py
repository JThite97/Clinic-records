"""Password hashing and the encryption key manager.

Key hierarchy
-------------
* One random 256-bit **data key** encrypts the SQLite database (SQLCipher)
  and the backup archives (AES-256 zip).
* The data key is never stored in the clear. For every user, keystore.json
  holds a copy of it *wrapped* (AES-256-GCM) with a key-encryption key
  derived from that user's password (scrypt, N=2**15).
* Logging in unwraps the data key, which opens the database. A forgotten
  password for the *last* administrator therefore means the data cannot be
  opened: the setup screen says so, and backups carry the keystore so a
  restore on a new machine works with the same login.

Passwords are additionally stored as Argon2id hashes inside the encrypted
database so the login check does not depend on the keystore alone.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

_ph = PasswordHasher()  # Argon2id with library defaults

MIN_PASSWORD_LEN = 8


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(hash_: str, password: str) -> bool:
    try:
        return _ph.verify(hash_, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _kek(password: str, salt: bytes, n: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=8, p=1).derive(password.encode("utf-8"))


class KeystoreError(Exception):
    pass


class Keystore:
    """keystore.json: {"version": 1, "users": {username: {salt, nonce, ct, n}}}"""

    SCRYPT_N = 2**15
    _lock = threading.Lock()

    def __init__(self, path: Path):
        self.path = path

    # -- persistence -------------------------------------------------------
    def exists(self) -> bool:
        return self.path.exists()

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "users": {}}
        return json.loads(self.path.read_text("utf-8"))

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), "utf-8")
        os.replace(tmp, self.path)

    def raw(self) -> dict:
        return self._read()

    @classmethod
    def from_raw(cls, raw: dict) -> "Keystore":
        ks = cls(Path(os.devnull))
        ks._mem = raw  # type: ignore[attr-defined]
        ks._read = lambda: ks._mem  # type: ignore[method-assign]
        return ks

    # -- key operations ----------------------------------------------------
    @staticmethod
    def generate_data_key() -> bytes:
        return secrets.token_bytes(32)

    def wrap_for(self, username: str, password: str, data_key: bytes) -> None:
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        kek = _kek(password, salt, self.SCRYPT_N)
        ct = AESGCM(kek).encrypt(nonce, data_key, username.lower().encode("utf-8"))
        with self._lock:
            data = self._read()
            data["users"][username.lower()] = {
                "salt": _b64(salt),
                "nonce": _b64(nonce),
                "ct": _b64(ct),
                "n": self.SCRYPT_N,
            }
            self._write(data)

    def unwrap(self, username: str, password: str) -> bytes:
        entry = self._read()["users"].get(username.lower())
        if not entry:
            raise KeystoreError("unknown user")
        kek = _kek(password, _unb64(entry["salt"]), int(entry.get("n", self.SCRYPT_N)))
        try:
            return AESGCM(kek).decrypt(
                _unb64(entry["nonce"]), _unb64(entry["ct"]), username.lower().encode("utf-8")
            )
        except InvalidTag as e:
            raise KeystoreError("wrong password") from e

    def remove(self, username: str) -> None:
        with self._lock:
            data = self._read()
            data["users"].pop(username.lower(), None)
            self._write(data)

    def users(self) -> list[str]:
        return sorted(self._read()["users"].keys())
