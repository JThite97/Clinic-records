"""Phone sync (pairing, push, pull, files) and the read-only mobile API."""
from __future__ import annotations

import socket

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Device
from ..schemas import PairIn, PushIn, ResolveIn
from ..services import admin_service, document_service, patient_service, pdf_service, sync_service, visit_service
from ..services.common import Origin, document_dict, patient_dict, visit_dict
from ..state import AppState, UserSession
from .deps import admin_user, current_session, db_session, desktop_user, device, get_state

router = APIRouter(prefix="/api")


# --- device management (desktop) ----------------------------------------------

def _lan_addresses() -> list[str]:
    addrs = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))


@router.post("/sync/pairing-code")
def pairing_code(sess: UserSession = Depends(admin_user), state: AppState = Depends(get_state)):
    code = sync_service.new_pairing_code(state.pairing_codes)
    return {"code": code, "expires_in": sync_service.PAIRING_TTL, "port": state.settings.port,
            "addresses": _lan_addresses(), "network_access": state.settings.network_access}


@router.get("/sync/devices")
def devices(sess: UserSession = Depends(admin_user), s: Session = Depends(db_session)):
    rows = s.scalars(select(Device).order_by(Device.created_at.desc()))
    return [{"id": d.id, "name": d.name, "revoked": d.revoked, "created_at": d.created_at.isoformat(),
             "last_seen": d.last_seen.isoformat() if d.last_seen else None, "last_pull_seq": d.last_pull_seq} for d in rows]


@router.post("/sync/devices/{device_id}/revoke")
def revoke(device_id: str, sess: UserSession = Depends(admin_user), s: Session = Depends(db_session)):
    d = s.get(Device, device_id)
    if d is None:
        raise HTTPException(404, "device not found")
    d.revoked = True
    from ..services.common import audit

    audit(s, sess.username, "device.revoke", "device", d.id, {"name": d.name})
    return {"ok": True}


@router.get("/sync/conflicts")
def conflicts(resolved: bool = False, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    return sync_service.list_conflicts(s, include_resolved=resolved)


@router.post("/sync/conflicts/{conflict_id}/resolve")
def resolve(conflict_id: int, body: ResolveIn, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    sync_service.resolve_conflict(s, conflict_id, body.use_other, sess.username)
    return {"ok": True}


# --- device endpoints (phone) -------------------------------------------------

@router.post("/sync/pair")
def pair(body: PairIn, s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    dev, token = sync_service.pair_device(s, state.pairing_codes, body.code, body.device_name)
    return {"device_id": dev.id, "device_token": token, "cursor": 0}


@router.post("/sync/push")
def push(body: PushIn, dev: Device = Depends(device), s: Session = Depends(db_session)):
    return sync_service.push(s, dev, body.events)


@router.get("/sync/pull")
def pull(since: int = 0, limit: int = 500, dev: Device = Depends(device), s: Session = Depends(db_session)):
    return sync_service.pull(s, dev, since, limit)


@router.get("/sync/files/{doc_id}")
def sync_file(doc_id: str, dev: Device = Depends(device), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    d = document_service.get_document(s, doc_id)
    return FileResponse(document_service.document_path(state.paths.documents, d), media_type=d.mime_type, filename=d.original_filename)


@router.post("/sync/files", status_code=201)
def sync_upload(
    patient_id: str = Form(...),
    doc_id: str = Form(...),
    title: str = Form(""),
    category: str = Form("lab"),
    file: UploadFile = File(...),
    dev: Device = Depends(device),
    s: Session = Depends(db_session),
    state: AppState = Depends(get_state),
):
    try:
        existing = document_service.get_document(s, doc_id)
        return document_dict(existing)  # idempotent re-upload
    except document_service.NotFound:
        pass
    d = document_service.add_document(s, state.paths.documents, patient_id, file.file, file.filename or "file",
                                      Origin(actor=f"device:{dev.name}", device_id=dev.id), title, category, doc_id=doc_id)
    return document_dict(d)


# --- read-only mobile API (phone browser over Tailscale) -----------------------

@router.get("/mobile/patients")
def m_search(q: str = "", sess: UserSession = Depends(current_session), s: Session = Depends(db_session)):
    return patient_service.search_patients(s, q, 30)


@router.get("/mobile/patients/{patient_id}")
def m_patient(patient_id: str, sess: UserSession = Depends(current_session), s: Session = Depends(db_session)):
    p = patient_service.get_patient(s, patient_id)
    return {"patient": patient_dict(p),
            "visits": [visit_dict(v) for v in visit_service.list_visits(s, p.id)],
            "documents": [document_dict(d) for d in document_service.list_documents(s, p.id)]}


@router.get("/mobile/documents/{doc_id}/file")
def m_doc(doc_id: str, sess: UserSession = Depends(current_session), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    d = document_service.get_document(s, doc_id)
    return FileResponse(document_service.document_path(state.paths.documents, d), media_type=d.mime_type, filename=d.original_filename,
                        content_disposition_type="inline")


@router.get("/mobile/visits/{visit_id}/prescription.pdf")
def m_rx(visit_id: str, sess: UserSession = Depends(current_session), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    v = visit_service.get_visit(s, visit_id)
    p = patient_service.get_patient(s, v.patient_id)
    pdf = pdf_service.prescription_pdf(visit_dict(v), patient_dict(p), admin_service.get_clinic(s), state.paths.documents)
    return Response(pdf, media_type="application/pdf")
