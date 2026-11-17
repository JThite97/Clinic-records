"""Process-wide application state: paths, the unlocked database, sessions."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from .config import Paths, RuntimeSettings, SettingsStore
from .database import Database, make_engine
from .security import Keystore, new_token

log = logging.getLogger(__name__)


@dataclass
class UserSession:
    token: str
    user_id: str
    username: str
    full_name: str
    role: str
    scope: str  # "desktop" (full) | "mobile" (read-only)
    expires_at: float

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass
class LoginThrottle:
    failures: dict[str, list[float]] = field(default_factory=dict)
    window: float = 300.0
    limit: int = 5

    def blocked(self, key: str) -> bool:
        now = time.time()
        recent = [t for t in self.failures.get(key, []) if now - t < self.window]
        self.failures[key] = recent
        return len(recent) >= self.limit

    def fail(self, key: str) -> None:
        self.failures.setdefault(key, []).append(time.time())

    def reset(self, key: str) -> None:
        self.failures.pop(key, None)


class AppState:
    def __init__(self, paths: Paths):
        self.paths = paths
        paths.ensure()
        self.settings_store = SettingsStore(paths)
        self.settings: RuntimeSettings = self.settings_store.load()
        self.keystore = Keystore(paths.keystore_file)
        self.db: Database | None = None
        self.data_key: bytes | None = None
        self.sessions: dict[str, UserSession] = {}
        self.throttle = LoginThrottle()
        self.pairing_codes: dict[str, float] = {}
        self.lock = threading.RLock()  # serialises unlock/restore/backup

    # -- lifecycle ---------------------------------------------------------
    @property
    def initialized(self) -> bool:
        return self.keystore.exists() and self.paths.db_file.exists()

    @property
    def unlocked(self) -> bool:
        return self.db is not None

    def open_database(self, key: bytes) -> Database:
        """Open (or create) the encrypted DB with ``key`` and run migrations."""
        from .bootstrap import init_schema

        with self.lock:
            if self.db is not None:
                return self.db
            engine = make_engine(self.paths.db_file, key)
            db = Database(engine)
            init_schema(db)
            self.db = db
            self.data_key = key
            log.info("database unlocked")
            return db

    def close_database(self) -> None:
        with self.lock:
            if self.db is not None:
                self.db.dispose()
            self.db = None
            self.data_key = None
            self.sessions.clear()
            log.info("database locked")

    # -- sessions ----------------------------------------------------------
    def new_session(self, user, scope: str = "desktop") -> UserSession:
        hours = self.settings.session_hours if scope == "desktop" else 2
        sess = UserSession(
            token=new_token(),
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            scope=scope,
            expires_at=time.time() + hours * 3600,
        )
        self.sessions[sess.token] = sess
        return sess

    def get_session(self, token: str) -> UserSession | None:
        sess = self.sessions.get(token)
        if not sess:
            return None
        if sess.expires_at < time.time():
            self.sessions.pop(token, None)
            return None
        return sess

    def save_settings(self) -> None:
        self.settings_store.save(self.settings)
