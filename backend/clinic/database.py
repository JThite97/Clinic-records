"""SQLAlchemy engine on top of SQLCipher.

The database file is encrypted with the 256-bit data key from the keystore
(see security.py). Every connection runs ``PRAGMA key`` first and then
``PRAGMA foreign_keys = ON``.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import sqlcipher3
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)


class DatabaseKeyError(Exception):
    """The key does not open this database file."""


def _connect(path: Path, key: bytes):
    conn = sqlcipher3.connect(str(path), check_same_thread=False, timeout=30)
    conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
    conn.execute("PRAGMA cipher_memory_security = OFF")
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlcipher3.DatabaseError as e:  # wrong key or not a SQLCipher file
        conn.close()
        raise DatabaseKeyError(str(e)) from e
    return conn


def verify_key(path: Path, key: bytes) -> None:
    _connect(path, key).close()


def make_engine(path: Path, key: bytes) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    verify_key(path, key)  # fail fast with a clear error
    engine = create_engine(
        "sqlite://",
        module=sqlcipher3,
        creator=lambda: _connect(path, key),
        pool_pre_ping=False,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.close()

    return engine


class Database:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Context-managed transaction: commit on success, rollback on error."""
        s = self.Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def checkpoint(self) -> None:
        """Flush the WAL into the main file (before a backup copy)."""
        with self.engine.connect() as c:
            c.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")

    def dispose(self) -> None:
        self.engine.dispose()
