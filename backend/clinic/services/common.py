"""Shared helpers: request origin, audit trail, event log, serialisers."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    PATIENT_FIELDS,
    RX_ITEM_FIELDS,
    VISIT_FIELDS,
    AuditLog,
    Document,
    Patient,
    Prescription,
    SyncEvent,
    Visit,
    utcnow,
)

DESKTOP = "desktop"


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class ValidationFailed(Exception):
    pass


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Origin:
    """Who/where a change comes from. Desktop changes use the defaults; changes
    replayed from a phone carry the phone's device id, clock and event id."""

    actor: str = ""
    device_id: str = DESKTOP
    ts: int = field(default_factory=now_ms)
    event_id: str | None = None


def utc_iso(dt: datetime | None) -> str | None:
    """Timestamps are stored as naive UTC; mark them so clients convert."""
    return dt.isoformat() + "Z" if dt else None


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


# --- audit trail -------------------------------------------------------------

def _row_hash(prev: str, ts: str, username: str, action: str, entity: str, entity_id: str, details) -> str:
    body = json.dumps(
        [prev, ts, username, action, entity, entity_id, details], sort_keys=True, default=str
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def audit(s: Session, username: str, action: str, entity: str = "", entity_id: str = "", details: dict | None = None) -> None:
    details = {k: _jsonable(v) for k, v in (details or {}).items()}
    last = s.scalar(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))
    prev = last.hash if last else ""
    row = AuditLog(username=username, action=action, entity=entity, entity_id=entity_id, details=details, prev_hash=prev)
    row.ts = utcnow().replace(microsecond=0)
    row.hash = _row_hash(prev, row.ts.isoformat(), username, action, entity, entity_id, details)
    s.add(row)
    s.flush()


def verify_audit_chain(s: Session) -> tuple[bool, int | None]:
    """Returns (ok, first_bad_id)."""
    prev = ""
    for row in s.scalars(select(AuditLog).order_by(AuditLog.id)):
        expected = _row_hash(prev, row.ts.isoformat(), row.username, row.action, row.entity, row.entity_id, row.details)
        if row.prev_hash != prev or row.hash != expected:
            return False, row.id
        prev = row.hash
    return True, None


# --- event log ---------------------------------------------------------------

def emit(s: Session, origin: Origin, entity: str, entity_id: str, op: str, payload: dict) -> SyncEvent:
    ev = SyncEvent(
        event_id=origin.event_id or str(uuid.uuid4()),
        device_id=origin.device_id,
        entity=entity,
        entity_id=entity_id,
        op=op,
        payload={k: _jsonable(v) for k, v in payload.items()},
        client_ts=origin.ts,
    )
    s.add(ev)
    s.flush()
    return ev


# --- serialisers -------------------------------------------------------------

def patient_dict(p: Patient) -> dict:
    d = {f: getattr(p, f) for f in PATIENT_FIELDS}
    d.update(
        id=p.id,
        patient_number=p.patient_number,
        created_at=utc_iso(p.created_at),
        updated_at=utc_iso(p.updated_at),
        age=patient_age(p),
    )
    return d


def patient_age(p: Patient) -> int | None:
    if p.date_of_birth:
        try:
            dob = date.fromisoformat(p.date_of_birth)
        except ValueError:
            return p.age_years
        t = date.today()
        return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))
    return p.age_years


def rx_items(rx: Prescription | None) -> list[dict]:
    if rx is None:
        return []
    return [{f: getattr(i, f) for f in RX_ITEM_FIELDS} for i in rx.items]


def visit_dict(v: Visit) -> dict:
    d = {f: _jsonable(getattr(v, f)) for f in VISIT_FIELDS}
    d.update(
        id=v.id,
        patient_id=v.patient_id,
        root_id=v.root_id,
        amends_id=v.amends_id,
        amendment_reason=v.amendment_reason,
        superseded=v.superseded,
        locked=v.locked,
        created_by=v.created_by,
        device_id=v.device_id,
        created_at=utc_iso(v.created_at),
        prescription={
            "id": v.prescription.id if v.prescription else None,
            "notes": v.prescription.notes if v.prescription else "",
            "items": rx_items(v.prescription),
        },
    )
    return d


def document_dict(d: Document) -> dict:
    return {
        "id": d.id,
        "patient_id": d.patient_id,
        "visit_id": d.visit_id,
        "title": d.title,
        "category": d.category,
        "original_filename": d.original_filename,
        "mime_type": d.mime_type,
        "size_bytes": d.size_bytes,
        "sha256": d.sha256,
        "archived": d.archived,
        "uploaded_by": d.uploaded_by,
        "uploaded_at": utc_iso(d.uploaded_at),
    }
