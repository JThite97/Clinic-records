"""First-run setup, login/logout, settings, users, audit, backups."""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import APP_NAME, APP_VERSION
from ..database import DatabaseKeyError
from ..models import AuditLog, Patient, User, Visit
from ..schemas import ClinicIn, LoginIn, PasswordIn, RestoreIn, RuntimeIn, SetupIn, UserIn
from ..security import Keystore, KeystoreError, verify_password
from ..services import admin_service
from ..services.backup_service import BackupError, BackupService
from ..services.common import audit, verify_audit_chain
from ..services.document_service import store_asset
from ..state import AppState, UserSession
from .deps import admin_user, current_session, db_session, desktop_user, get_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def backups(state: AppState) -> BackupService:
    return BackupService(state.paths, state.keystore)


def _session_out(sess: UserSession) -> dict:
    return {"token": sess.token, "user": {"id": sess.user_id, "username": sess.username, "full_name": sess.full_name,
                                          "role": sess.role}, "scope": sess.scope}


# --- status / setup / login --------------------------------------------------

@router.get("/health")
def health():
    return {"ok": True, "app": APP_NAME, "version": APP_VERSION}


@router.get("/system/status")
def status(state: AppState = Depends(get_state)):
    clinic_name = None
    if state.db is not None:
        with state.db.session() as s:
            clinic_name = admin_service.get_clinic(s).get("clinic_name")
    return {"initialized": state.initialized, "unlocked": state.unlocked, "version": APP_VERSION,
            "clinic_name": clinic_name, "network_access": state.settings.network_access, "port": state.settings.port}


@router.post("/system/setup")
def setup(body: SetupIn, state: AppState = Depends(get_state)):
    with state.lock:
        if state.initialized:
            raise HTTPException(409, "Already set up")
        # Start clean (a half-finished earlier setup may have left files).
        state.paths.db_file.unlink(missing_ok=True)
        state.paths.keystore_file.unlink(missing_ok=True)
        key = Keystore.generate_data_key()
        db = state.open_database(key)
        with db.session() as s:
            u = admin_service.create_user(s, state.keystore, key, body.username, body.password, body.full_name or body.doctor_name, "admin", body.username)
            admin_service.update_clinic(s, {"clinic_name": body.clinic_name, "doctor_name": body.doctor_name}, body.username)
            audit(s, u.username, "system.setup", "system", "", {"clinic": body.clinic_name})
        sess = state.new_session(u)
        log.info("first-run setup complete")
        return _session_out(sess)


@router.post("/system/restore-setup")
async def restore_setup(file: UploadFile = File(...), username: str = Form(...), password: str = Form(...), state: AppState = Depends(get_state)):
    """Fresh install: restore a backup file taken on another computer."""
    if state.initialized:
        raise HTTPException(409, "Already set up. Use Backups > Restore instead.")
    tmp = Path(tempfile.mkdtemp(prefix="clinic-up-")) / "upload.crbak"
    try:
        with tmp.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        svc = backups(state)
        try:
            key = svc.key_from_archive(tmp, username, password)
            svc.restore(tmp, key)
        except BackupError as e:
            raise HTTPException(400, str(e)) from e
        dest = state.paths.backups / f"imported-{file.filename or 'backup'}"
        shutil.copy2(tmp, dest.with_suffix(".crbak"))
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    return _login(state, LoginIn(username=username, password=password))


def _login(state: AppState, body: LoginIn) -> dict:
    who = body.username.strip().lower()
    if state.throttle.blocked(who):
        raise HTTPException(429, "Too many attempts. Wait 5 minutes and try again.")
    if not state.initialized:
        raise HTTPException(409, "Not set up yet")
    scope = "mobile" if body.scope == "mobile" else "desktop"
    with state.lock:
        if state.db is None:
            try:
                key = state.keystore.unwrap(who, body.password)
                state.open_database(key)
            except (KeystoreError, DatabaseKeyError):
                state.throttle.fail(who)
                log.warning("failed unlock for %s", who)
                raise HTTPException(401, "Wrong username or password")
    with state.db.session() as s:
        u = admin_service.authenticate(s, who, body.password)
        if u is None:
            state.throttle.fail(who)
            audit(s, who, "auth.failed", "user", "", {"scope": scope})
            raise HTTPException(401, "Wrong username or password")
        audit(s, u.username, "auth.login", "user", u.id, {"scope": scope})
    state.throttle.reset(who)
    return _session_out(state.new_session(u, scope))


@router.post("/auth/login")
def login(body: LoginIn, request: Request, state: AppState = Depends(get_state)):
    if getattr(request.state, "remote", False):
        body.scope = "mobile"
    return _login(state, body)


@router.post("/auth/logout")
def logout(sess: UserSession = Depends(current_session), state: AppState = Depends(get_state)):
    state.sessions.pop(sess.token, None)
    return {"ok": True}


@router.post("/auth/lock")
def lock(sess: UserSession = Depends(desktop_user), state: AppState = Depends(get_state)):
    """Close the database and end every session (the 'Lock' button)."""
    with state.db.session() as s:
        audit(s, sess.username, "system.lock")
    state.close_database()
    return {"ok": True}


@router.get("/auth/me")
def me(sess: UserSession = Depends(current_session)):
    return {"id": sess.user_id, "username": sess.username, "full_name": sess.full_name, "role": sess.role, "scope": sess.scope}


@router.post("/auth/password")
def change_own_password(body: PasswordIn, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    u = s.get(User, sess.user_id)
    if not body.current_password or not verify_password(u.password_hash, body.current_password):
        raise HTTPException(400, "Current password is wrong")
    admin_service.change_password(s, state.keystore, state.data_key, u.id, body.new_password, sess.username)
    return {"ok": True}


# --- dashboard ---------------------------------------------------------------

@router.get("/dashboard")
def dashboard(sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    from ..services import visit_service

    return {
        "patients": s.scalar(select(func.count()).select_from(Patient).where(Patient.archived.is_(False))) or 0,
        "visits": s.scalar(select(func.count()).select_from(Visit).where(Visit.superseded.is_(False))) or 0,
        "today": visit_service.todays_visits(s),
        "follow_ups": visit_service.due_follow_ups(s),
        "last_backup_hours": backups(state).last_backup_age_hours(),
    }


# --- settings ----------------------------------------------------------------

@router.get("/settings")
def get_settings(sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    rt = state.settings
    return {"clinic": admin_service.get_clinic(s),
            "runtime": {"network_access": rt.network_access, "backup_retention": rt.backup_retention,
                        "auto_backup_hours": rt.auto_backup_hours, "port": rt.port},
            "paths": {"home": str(state.paths.home), "backups": str(state.paths.backups), "logs": str(state.paths.log_file)}}


@router.put("/settings/clinic")
def put_clinic(body: ClinicIn, sess: UserSession = Depends(admin_user), s: Session = Depends(db_session)):
    return admin_service.update_clinic(s, body.model_dump(exclude_none=True), sess.username)


@router.put("/settings/runtime")
def put_runtime(body: RuntimeIn, sess: UserSession = Depends(admin_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    rt = state.settings
    restart = False
    if body.network_access is not None and body.network_access != rt.network_access:
        rt.network_access = body.network_access
        restart = True
    if body.backup_retention is not None:
        rt.backup_retention = body.backup_retention
    if body.auto_backup_hours is not None:
        rt.auto_backup_hours = body.auto_backup_hours
    state.save_settings()
    audit(s, sess.username, "settings.runtime", "settings", "runtime", body.model_dump(exclude_none=True))
    return {"ok": True, "restart_required": restart}


@router.post("/settings/asset/{kind}")
def upload_asset(kind: str, file: UploadFile = File(...), sess: UserSession = Depends(admin_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    if kind not in ("logo", "signature"):
        raise HTTPException(404, "unknown asset")
    rel = store_asset(state.paths.documents, file.file, file.filename or "image.png", kind)
    return admin_service.update_clinic(s, {f"{kind}_path": rel}, sess.username)


@router.delete("/settings/asset/{kind}")
def delete_asset(kind: str, sess: UserSession = Depends(admin_user), s: Session = Depends(db_session)):
    if kind not in ("logo", "signature"):
        raise HTTPException(404, "unknown asset")
    return admin_service.update_clinic(s, {f"{kind}_path": ""}, sess.username)


@router.get("/settings/asset/{kind}")
def get_asset(kind: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    rel = admin_service.get_clinic(s).get(f"{kind}_path")
    if kind not in ("logo", "signature") or not rel:
        raise HTTPException(404, "not set")
    path = state.paths.documents / rel
    if not path.exists():
        raise HTTPException(404, "missing")
    return FileResponse(path)


# --- users -------------------------------------------------------------------

@router.get("/users")
def list_users(sess: UserSession = Depends(admin_user), s: Session = Depends(db_session)):
    return [admin_service.user_dict(u) for u in s.scalars(select(User).order_by(User.username))]


@router.post("/users")
def add_user(body: UserIn, sess: UserSession = Depends(admin_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    u = admin_service.create_user(s, state.keystore, state.data_key, body.username, body.password, body.full_name, body.role, sess.username)
    return admin_service.user_dict(u)


@router.post("/users/{user_id}/password")
def reset_password(user_id: str, body: PasswordIn, sess: UserSession = Depends(admin_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    admin_service.change_password(s, state.keystore, state.data_key, user_id, body.new_password, sess.username)
    return {"ok": True}


@router.post("/users/{user_id}/active/{active}")
def set_user_active(user_id: str, active: bool, sess: UserSession = Depends(admin_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    if user_id == sess.user_id and not active:
        raise HTTPException(400, "You cannot deactivate yourself")
    return admin_service.user_dict(admin_service.set_active(s, state.keystore, user_id, active, sess.username))


# --- audit -------------------------------------------------------------------

@router.get("/audit")
def audit_log(limit: int = 200, offset: int = 0, entity_id: str | None = None, sess: UserSession = Depends(admin_user), s: Session = Depends(db_session)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).offset(offset).limit(min(limit, 1000))
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    rows = [{"id": r.id, "ts": r.ts.isoformat(), "username": r.username, "action": r.action, "entity": r.entity,
             "entity_id": r.entity_id, "details": r.details} for r in s.scalars(stmt)]
    ok, bad = verify_audit_chain(s)
    return {"entries": rows, "chain_ok": ok, "first_bad_id": bad}


# --- backups -----------------------------------------------------------------

@router.get("/backups")
def list_backups(sess: UserSession = Depends(admin_user), state: AppState = Depends(get_state)):
    svc = backups(state)
    return {"backups": svc.list_backups(), "folder": str(state.paths.backups), "retention": state.settings.backup_retention,
            "auto_backup_hours": state.settings.auto_backup_hours}


@router.post("/backups")
def create_backup(sess: UserSession = Depends(admin_user), state: AppState = Depends(get_state)):
    svc = backups(state)
    with state.lock:
        path = svc.create_backup(state.data_key, "manual")
        svc.prune(state.settings.backup_retention)
    with state.db.session() as s:
        audit(s, sess.username, "backup.create", "backup", path.name)
    return {"name": path.name, "verify": svc.verify_backup(path, state.data_key)}


@router.post("/backups/{name}/verify")
def verify_backup(name: str, sess: UserSession = Depends(admin_user), state: AppState = Depends(get_state)):
    svc = backups(state)
    try:
        return svc.verify_backup(svc.resolve(name), state.data_key)
    except BackupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/backups/{name}/download")
def download_backup(name: str, sess: UserSession = Depends(admin_user), state: AppState = Depends(get_state)):
    try:
        p = backups(state).resolve(name)
    except BackupError as e:
        raise HTTPException(404, str(e)) from e
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


@router.post("/backups/upload")
def upload_backup(file: UploadFile = File(...), sess: UserSession = Depends(admin_user), state: AppState = Depends(get_state)):
    name = Path(file.filename or "uploaded.crbak").name
    if not name.endswith(".crbak"):
        raise HTTPException(400, "Choose a .crbak backup file")
    dest = state.paths.backups / f"uploaded-{name}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"name": dest.name}


@router.post("/backups/restore")
def restore_backup(body: RestoreIn, sess: UserSession = Depends(admin_user), state: AppState = Depends(get_state)):
    """Restore with a safety snapshot first. Everyone must log in again."""
    svc = backups(state)
    try:
        archive = svc.resolve(body.name)
        key = svc.key_from_archive(archive, sess.username, body.password)
    except BackupError as e:
        raise HTTPException(400, str(e)) from e
    with state.lock:
        snap = svc.create_backup(state.data_key, "pre-restore")
        with state.db.session() as s:
            audit(s, sess.username, "backup.restore.start", "backup", body.name, {"snapshot": snap.name})
        state.close_database()
        try:
            svc.restore(archive, key)
        except BackupError as e:
            raise HTTPException(400, str(e)) from e
        db = state.open_database(key)
        with db.session() as s:
            audit(s, sess.username, "backup.restore", "backup", body.name, {"snapshot": snap.name})
        state.sessions.clear()
    return {"ok": True, "snapshot": snap.name, "relogin": True}
