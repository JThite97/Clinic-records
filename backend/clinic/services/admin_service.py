"""Clinic profile and user accounts."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..bootstrap import DEFAULT_CLINIC
from ..models import Setting, User
from ..security import MIN_PASSWORD_LEN, Keystore, hash_password, verify_password
from .common import Conflict, NotFound, ValidationFailed, audit

ROLES = ("admin", "doctor", "staff")


def get_clinic(s: Session) -> dict:
    row = s.get(Setting, "clinic")
    data = dict(DEFAULT_CLINIC)
    if row and isinstance(row.value, dict):
        data.update(row.value)
    return data


def update_clinic(s: Session, changes: dict, actor: str) -> dict:
    data = get_clinic(s)
    for k, v in changes.items():
        if k in DEFAULT_CLINIC and v is not None:
            data[k] = str(v).strip() if isinstance(v, str) else v
    if data.get("paper_size") not in ("A4", "Letter"):
        data["paper_size"] = "A4"
    row = s.get(Setting, "clinic")
    if row is None:
        s.add(Setting(key="clinic", value=data))
    else:
        row.value = data
    s.flush()
    audit(s, actor, "settings.clinic", "settings", "clinic", {"fields": sorted(changes)})
    return data


def user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role, "active": u.active,
            "created_at": u.created_at.isoformat()}


def check_password_rules(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValidationFailed(f"Password must be at least {MIN_PASSWORD_LEN} characters")


def create_user(s: Session, keystore: Keystore, data_key: bytes, username: str, password: str, full_name: str, role: str, actor: str) -> User:
    username = (username or "").strip().lower()
    if not username or not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise ValidationFailed("Username may contain letters, numbers, dot, dash and underscore")
    if role not in ROLES:
        raise ValidationFailed("Unknown role")
    check_password_rules(password)
    if s.scalar(select(User).where(User.username == username)):
        raise Conflict("Username already exists")
    u = User(username=username, full_name=(full_name or "").strip(), role=role, password_hash=hash_password(password))
    s.add(u)
    s.flush()
    keystore.wrap_for(username, password, data_key)
    audit(s, actor, "user.create", "user", u.id, {"username": username, "role": role})
    return u


def authenticate(s: Session, username: str, password: str) -> User | None:
    u = s.scalar(select(User).where(User.username == (username or "").strip().lower()))
    if u is None or not u.active or not verify_password(u.password_hash, password):
        return None
    return u


def change_password(s: Session, keystore: Keystore, data_key: bytes, user_id: str, new_password: str, actor: str) -> None:
    u = s.get(User, user_id)
    if u is None:
        raise NotFound("user not found")
    check_password_rules(new_password)
    u.password_hash = hash_password(new_password)
    s.flush()
    keystore.wrap_for(u.username, new_password, data_key)
    audit(s, actor, "user.password", "user", u.id, {"username": u.username})


def set_active(s: Session, keystore: Keystore, user_id: str, active: bool, actor: str) -> User:
    u = s.get(User, user_id)
    if u is None:
        raise NotFound("user not found")
    if not active and u.role == "admin":
        admins = s.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.active.is_(True))) or 0
        if admins <= 1:
            raise ValidationFailed("At least one active administrator is required")
    u.active = active
    if not active:
        keystore.remove(u.username)
    s.flush()
    audit(s, actor, "user.activate" if active else "user.deactivate", "user", u.id, {"username": u.username})
    return u
