"""Patients, visits, prescriptions, medicines, documents and PDFs."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..models import Document
from ..schemas import AmendIn, MedicineIn, PatientIn, VisitIn
from ..services import admin_service, document_service, medicine_service, patient_service, pdf_service, visit_service
from ..services.common import Origin, document_dict, patient_dict, visit_dict
from ..state import AppState, UserSession
from .deps import clinical_user, db_session, desktop_user, get_state

router = APIRouter(prefix="/api")


def origin(sess: UserSession) -> Origin:
    return Origin(actor=sess.username)


# --- patients ----------------------------------------------------------------

@router.get("/patients")
def search(q: str = "", limit: int = 25, archived: bool = False, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    return patient_service.search_patients(s, q, min(limit, 200), include_archived=archived)


@router.post("/patients", status_code=201)
def create_patient(body: PatientIn, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    return patient_dict(patient_service.create_patient(s, body.data(), origin(sess)))


@router.get("/patients/{patient_id}")
def get_patient(patient_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    return patient_dict(patient_service.get_patient(s, patient_id))


@router.put("/patients/{patient_id}")
def update_patient(patient_id: str, body: PatientIn, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    p, _ = patient_service.update_patient(s, patient_id, body.data(), origin(sess))
    return patient_dict(p)


@router.get("/patients/{patient_id}/visits")
def patient_visits(patient_id: str, all_versions: bool = False, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    p = patient_service.get_patient(s, patient_id)
    return [visit_dict(v) for v in visit_service.list_visits(s, p.id, include_superseded=all_versions)]


@router.get("/patients/{patient_id}/last-prescription")
def last_rx(patient_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    p = patient_service.get_patient(s, patient_id)
    return visit_service.last_prescription(s, p.id)


@router.post("/patients/{patient_id}/visits", status_code=201)
def create_visit(patient_id: str, body: VisitIn, sess: UserSession = Depends(clinical_user), s: Session = Depends(db_session)):
    p = patient_service.get_patient(s, patient_id)
    v = visit_service.create_visit(s, p.id, body.fields(), body.rx(), origin(sess))
    return visit_dict(v)


@router.get("/patients/{patient_id}/record.pdf")
def record_pdf(patient_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    p = patient_service.get_patient(s, patient_id)
    visits = [visit_dict(v) for v in visit_service.list_visits(s, p.id)]
    docs = [document_dict(d) for d in document_service.list_documents(s, p.id)]
    pdf = pdf_service.patient_record_pdf(patient_dict(p), visits, docs, admin_service.get_clinic(s), state.paths.documents)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{p.patient_number}-record.pdf"'})


# --- visits ------------------------------------------------------------------

@router.get("/visits/{visit_id}")
def get_visit(visit_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    return visit_dict(visit_service.get_visit(s, visit_id))


@router.get("/visits/{visit_id}/history")
def history(visit_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    return visit_service.visit_history(s, visit_id)


@router.post("/visits/{visit_id}/amend", status_code=201)
def amend(visit_id: str, body: AmendIn, sess: UserSession = Depends(clinical_user), s: Session = Depends(db_session)):
    v, _ = visit_service.amend_visit(s, visit_id, body.fields(), body.rx(), body.reason, origin(sess))
    return visit_dict(v)


@router.get("/visits/{visit_id}/copy-prescription")
def copy_rx(visit_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    return {"items": visit_service.copy_previous_prescription(s, visit_id)}


def _rx_pdf(s: Session, visit_id: str, state: AppState) -> tuple[bytes, str]:
    v = visit_service.get_visit(s, visit_id)
    p = patient_service.get_patient(s, v.patient_id)
    pdf = pdf_service.prescription_pdf(visit_dict(v), patient_dict(p), admin_service.get_clinic(s), state.paths.documents)
    return pdf, f"{p.patient_number}-{v.visit_date:%Y%m%d}-prescription.pdf"


@router.get("/visits/{visit_id}/prescription.pdf")
def prescription_pdf(visit_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    pdf, name = _rx_pdf(s, visit_id, state)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.post("/visits/{visit_id}/prescription.pdf/export")
def export_prescription(visit_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    """Write the PDF to the exports folder and return its path, so the desktop
    shell can open it in the system PDF viewer for printing."""
    pdf, name = _rx_pdf(s, visit_id, state)
    dest = state.paths.exports / f"{datetime.now():%H%M%S}-{name}"
    dest.write_bytes(pdf)
    for old in sorted(state.paths.exports.glob("*.pdf"), key=lambda p: p.stat().st_mtime)[:-50]:
        old.unlink(missing_ok=True)
    return {"path": str(dest)}


@router.post("/patients/{patient_id}/record.pdf/export")
def export_record(patient_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    p = patient_service.get_patient(s, patient_id)
    visits = [visit_dict(v) for v in visit_service.list_visits(s, p.id)]
    docs = [document_dict(d) for d in document_service.list_documents(s, p.id)]
    pdf = pdf_service.patient_record_pdf(patient_dict(p), visits, docs, admin_service.get_clinic(s), state.paths.documents)
    dest = state.paths.exports / f"{datetime.now():%H%M%S}-{p.patient_number}-record.pdf"
    dest.write_bytes(pdf)
    return {"path": str(dest)}


# --- medicines ---------------------------------------------------------------

@router.get("/medicines")
def medicines(q: str = "", limit: int = 15, inactive: bool = False, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    return medicine_service.search_medicines(s, q, min(limit, 500), include_inactive=inactive)


@router.post("/medicines", status_code=201)
def add_medicine(body: MedicineIn, sess: UserSession = Depends(clinical_user), s: Session = Depends(db_session)):
    return medicine_service.medicine_dict(medicine_service.create_medicine(s, body.model_dump(exclude_none=True), sess.username))


@router.put("/medicines/{medicine_id}")
def edit_medicine(medicine_id: str, body: MedicineIn, sess: UserSession = Depends(clinical_user), s: Session = Depends(db_session)):
    return medicine_service.medicine_dict(medicine_service.update_medicine(s, medicine_id, body.model_dump(exclude_none=True), sess.username))


# --- documents ---------------------------------------------------------------

@router.get("/patients/{patient_id}/documents")
def documents(patient_id: str, archived: bool = False, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    p = patient_service.get_patient(s, patient_id)
    return [document_dict(d) for d in document_service.list_documents(s, p.id, include_archived=archived)]


@router.post("/patients/{patient_id}/documents", status_code=201)
def upload_document(
    patient_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    category: str = Form("lab"),
    visit_id: str | None = Form(None),
    sess: UserSession = Depends(desktop_user),
    s: Session = Depends(db_session),
    state: AppState = Depends(get_state),
):
    p = patient_service.get_patient(s, patient_id)
    d = document_service.add_document(s, state.paths.documents, p.id, file.file, file.filename or "file", origin(sess), title, category, visit_id or None)
    return document_dict(d)


def _doc(s: Session, doc_id: str) -> Document:
    return document_service.get_document(s, doc_id)


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: str, download: bool = False, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    d = _doc(s, doc_id)
    path = document_service.document_path(state.paths.documents, d)
    if not path.exists():
        raise HTTPException(404, "File is missing from the documents folder")
    return FileResponse(path, media_type=d.mime_type, filename=d.original_filename,
                        content_disposition_type="attachment" if download else "inline")


@router.get("/documents/{doc_id}/path")
def document_local_path(doc_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    """Absolute path, so the desktop shell can open it in the default viewer."""
    d = _doc(s, doc_id)
    return {"path": str(document_service.document_path(state.paths.documents, d))}


@router.post("/documents/{doc_id}/verify")
def verify(doc_id: str, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session), state: AppState = Depends(get_state)):
    return document_service.verify_document(state.paths.documents, _doc(s, doc_id))


@router.post("/documents/{doc_id}/archive/{archived}")
def archive(doc_id: str, archived: bool, sess: UserSession = Depends(desktop_user), s: Session = Depends(db_session)):
    return document_dict(document_service.set_archived(s, doc_id, archived, origin(sess)))
