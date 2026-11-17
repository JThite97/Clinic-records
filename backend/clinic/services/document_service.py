"""Document vault: attachments are copied into the clinic folder.

Files are stored under documents/patients/<P000001>/<doc-id>_<name> with a
SHA-256 checksum, so moving or deleting the original on the desktop does not
affect the stored copy. Documents are never deleted, only archived.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
import shutil
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Document, Patient, new_id
from .common import NotFound, Origin, ValidationFailed, audit, document_dict, emit

log = logging.getLogger(__name__)

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".txt", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".dcm"}
MAX_BYTES = 100 * 1024 * 1024
CATEGORIES = ("lab", "imaging", "prescription", "referral", "discharge", "other")


def safe_name(name: str) -> str:
    name = Path(name or "file").name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .") or "file"
    return name[:120]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def add_document(
    s: Session,
    documents_root: Path,
    patient_id: str,
    stream: BinaryIO,
    filename: str,
    origin: Origin,
    title: str = "",
    category: str = "lab",
    visit_id: str | None = None,
    doc_id: str | None = None,
) -> Document:
    p = s.get(Patient, patient_id)
    if p is None:
        raise NotFound("patient not found")
    fname = safe_name(filename)
    ext = Path(fname).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValidationFailed(f"File type {ext or '(none)'} is not allowed")
    category = category if category in CATEGORIES else "other"
    did = doc_id or new_id()
    folder_name = p.patient_number or p.id
    rel = Path("patients") / folder_name / f"{did[:8]}_{fname}"
    dest = documents_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    size = 0
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with tmp.open("wb") as out:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValidationFailed("File is larger than 100 MB")
                h.update(chunk)
                out.write(chunk)
        tmp.replace(dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    if size == 0:
        dest.unlink(missing_ok=True)
        raise ValidationFailed("File is empty")
    doc = Document(
        id=did,
        patient_id=p.id,
        visit_id=visit_id,
        title=(title or Path(fname).stem).strip(),
        category=category,
        original_filename=fname,
        stored_path=rel.as_posix(),
        mime_type=mimetypes.guess_type(fname)[0] or "application/octet-stream",
        size_bytes=size,
        sha256=h.hexdigest(),
        uploaded_by=origin.actor,
    )
    s.add(doc)
    s.flush()
    emit(s, origin, "document", doc.id, "create", document_dict(doc))
    audit(s, origin.actor, "document.add", "document", doc.id, {"patient": p.patient_number, "file": fname, "sha256": doc.sha256})
    log.info("document stored %s (%d bytes)", rel, size)
    return doc


def get_document(s: Session, doc_id: str) -> Document:
    d = s.get(Document, doc_id)
    if d is None:
        raise NotFound("document not found")
    return d


def document_path(documents_root: Path, d: Document) -> Path:
    p = (documents_root / d.stored_path).resolve()
    if documents_root.resolve() not in p.parents:
        raise NotFound("bad path")
    return p


def verify_document(documents_root: Path, d: Document) -> dict:
    path = document_path(documents_root, d)
    if not path.exists():
        return {"ok": False, "reason": "missing"}
    actual = sha256_file(path)
    return {"ok": actual == d.sha256, "expected": d.sha256, "actual": actual}


def list_documents(s: Session, patient_id: str, include_archived: bool = False) -> list[Document]:
    stmt = select(Document).where(Document.patient_id == patient_id).order_by(Document.uploaded_at.desc())
    if not include_archived:
        stmt = stmt.where(Document.archived.is_(False))
    return list(s.scalars(stmt))


def set_archived(s: Session, doc_id: str, archived: bool, origin: Origin) -> Document:
    d = get_document(s, doc_id)
    d.archived = archived
    s.flush()
    emit(s, origin, "document", d.id, "archive", {"archived": archived})
    audit(s, origin.actor, "document.archive" if archived else "document.unarchive", "document", d.id, {})
    return d


def store_asset(documents_root: Path, stream: BinaryIO, filename: str, kind: str) -> str:
    """Logo / signature images for the letterhead. Returns relative path."""
    ext = Path(safe_name(filename)).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg"}:
        raise ValidationFailed("Use a PNG or JPG image")
    rel = Path("clinic") / f"{kind}{ext}"
    dest = documents_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    for old in dest.parent.glob(f"{kind}.*"):
        old.unlink()
    with dest.open("wb") as out:
        shutil.copyfileobj(stream, out)
    return rel.as_posix()
