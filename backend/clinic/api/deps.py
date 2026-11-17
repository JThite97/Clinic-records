"""Request dependencies: app state, DB session, current user."""
from __future__ import annotations

from typing import Iterator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..models import Device
from ..services.sync_service import authenticate_device
from ..state import AppState, UserSession


def get_state(request: Request) -> AppState:
    return request.app.state.clinic


def db_session(state: AppState = Depends(get_state)) -> Iterator[Session]:
    if state.db is None:
        raise HTTPException(status_code=423, detail="Clinic data is locked. Please log in.")
    with state.db.session() as s:
        yield s


def _token(authorization: str | None, request: Request) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.query_params.get("token", "")


def current_session(request: Request, authorization: str | None = Header(default=None), state: AppState = Depends(get_state)) -> UserSession:
    sess = state.get_session(_token(authorization, request))
    if sess is None or state.db is None:
        raise HTTPException(status_code=401, detail="Please log in")
    return sess


def desktop_user(sess: UserSession = Depends(current_session)) -> UserSession:
    if sess.scope != "desktop":
        raise HTTPException(status_code=403, detail="Read-only mobile session")
    return sess


def admin_user(sess: UserSession = Depends(desktop_user)) -> UserSession:
    if not sess.is_admin:
        raise HTTPException(status_code=403, detail="Administrator only")
    return sess


def clinical_user(sess: UserSession = Depends(desktop_user)) -> UserSession:
    """Doctors and admins write clinical records; staff manage patients/documents."""
    if sess.role not in ("admin", "doctor"):
        raise HTTPException(status_code=403, detail="Only doctors can record visits")
    return sess


def device(x_device_token: str | None = Header(default=None), s: Session = Depends(db_session)) -> Device:
    dev = authenticate_device(s, x_device_token or "")
    if dev is None:
        raise HTTPException(status_code=401, detail="Unknown or revoked device")
    return dev
