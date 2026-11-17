"""Visits and prescriptions. Append-only: saved visits are never overwritten.

* ``create_visit`` adds a visit and locks every earlier visit of the patient.
* ``amend_visit`` writes a new version (same ``root_id``) that supersedes the
  previous one. Amending a locked (historical) visit requires a reason.
  The old version stays in the database and is shown in the history.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from ..models import (
    RX_ITEM_FIELDS,
    VISIT_FIELDS,
    Medicine,
    Patient,
    Prescription,
    PrescriptionItem,
    SyncConflict,
    Visit,
    new_id,
)
from .common import Conflict, NotFound, Origin, ValidationFailed, audit, emit, rx_items, visit_dict

log = logging.getLogger(__name__)

_INT = {"bp_systolic", "bp_diastolic", "pulse", "spo2", "resp_rate"}
_FLOAT = {"temperature", "weight", "height"}


def _parse_dt(v) -> datetime:
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError as e:
            raise ValidationFailed(f"bad visit_date: {v}") from e
    return datetime.now()


def _clean_visit(data: dict) -> dict:
    out = {}
    for k in VISIT_FIELDS:
        if k not in data:
            continue
        v = data[k]
        if isinstance(v, str):
            v = v.strip()
        if k in _INT:
            v = None if v in ("", None) else int(float(v))
        elif k in _FLOAT:
            v = None if v in ("", None) else float(v)
        elif k == "visit_date":
            v = _parse_dt(v)
        elif k == "follow_up_date":
            v = v or None
        elif v is None:
            v = ""
        out[k] = v
    return out


def _clean_items(items: list[dict] | None) -> list[dict]:
    out = []
    for it in items or []:
        name = (it.get("medicine_name") or "").strip()
        if not name:
            continue
        row = {f: (str(it.get(f) or "").strip() if f != "medicine_id" else it.get(f)) for f in RX_ITEM_FIELDS}
        row["medicine_name"] = name
        out.append(row)
    return out


def _attach_rx(s: Session, visit: Visit, items: list[dict], notes: str) -> None:
    if not items and not notes:
        return
    rx = Prescription(visit_id=visit.id, notes=notes or "")
    s.add(rx)
    s.flush()
    for pos, it in enumerate(items):
        s.add(PrescriptionItem(prescription_id=rx.id, position=pos, **it))
        if it.get("medicine_id"):
            med = s.get(Medicine, it["medicine_id"])
            if med:
                med.usage_count += 1
    s.flush()
    s.refresh(visit)


def get_visit(s: Session, visit_id: str) -> Visit:
    v = s.get(Visit, visit_id)
    if v is None:
        raise NotFound("visit not found")
    return v


def create_visit(
    s: Session,
    patient_id: str,
    data: dict,
    rx: dict | None,
    origin: Origin,
    visit_id: str | None = None,
) -> Visit:
    patient = s.get(Patient, patient_id)
    if patient is None:
        raise NotFound("patient not found")
    if visit_id and s.get(Visit, visit_id) is not None:
        raise Conflict("visit already exists")
    fields = _clean_visit(data)
    fields.setdefault("visit_date", datetime.now())
    vid = visit_id or new_id()
    # Lock every earlier visit of this patient.
    s.execute(update(Visit).where(Visit.patient_id == patient_id).values(locked=True))
    v = Visit(id=vid, root_id=vid, patient_id=patient_id, locked=False, created_by=origin.actor, device_id=origin.device_id, **fields)
    s.add(v)
    s.flush()
    items = _clean_items((rx or {}).get("items"))
    _attach_rx(s, v, items, (rx or {}).get("notes", ""))
    emit(s, origin, "visit", v.id, "create", {
        "patient_id": patient_id, "fields": fields,
        "prescription": {"items": items, "notes": (rx or {}).get("notes", "")},
    })
    audit(s, origin.actor, "visit.create", "visit", v.id, {"patient": patient.patient_number, "device": origin.device_id, "rx_items": len(items)})
    return v


def amend_visit(
    s: Session,
    visit_id: str,
    data: dict,
    rx: dict | None,
    reason: str,
    origin: Origin,
    new_visit_id: str | None = None,
) -> tuple[Visit, SyncConflict | None]:
    target = get_visit(s, visit_id)
    reason = (reason or "").strip()
    if target.locked and not reason:
        raise ValidationFailed("A reason is required to amend a historical visit")
    if new_visit_id and s.get(Visit, new_visit_id) is not None:
        raise Conflict("visit already exists")
    conflict = None
    if target.superseded:
        # Another device amended the same version concurrently: keep both,
        # newest becomes current, flag for review.
        current = s.scalar(select(Visit).where(Visit.root_id == target.root_id, Visit.superseded.is_(False)))
        conflict = SyncConflict(
            entity="visit", entity_id=target.root_id, field="amendment", kind="amendment",
            kept_value=new_visit_id or "", other_value=current.id if current else "",
            kept_device=origin.device_id, other_device=current.device_id if current else "",
        )
    base = {f: getattr(target, f) for f in VISIT_FIELDS}
    base.update(_clean_visit(data))
    v = Visit(
        id=new_visit_id or new_id(),
        root_id=target.root_id,
        amends_id=target.id,
        amendment_reason=reason,
        patient_id=target.patient_id,
        locked=target.locked,
        created_by=origin.actor,
        device_id=origin.device_id,
        **base,
    )
    s.execute(update(Visit).where(Visit.root_id == target.root_id).values(superseded=True))
    s.add(v)
    s.flush()
    if rx is None:
        items, notes = rx_items(target.prescription), (target.prescription.notes if target.prescription else "")
    else:
        items, notes = _clean_items(rx.get("items")), rx.get("notes", "")
    _attach_rx(s, v, items, notes)
    if conflict:
        conflict.kept_value = v.id
        s.add(conflict)
    emit(s, origin, "visit", v.id, "amend", {
        "amends_id": target.id, "reason": reason, "patient_id": v.patient_id,
        "fields": {k: base[k] for k in VISIT_FIELDS},
        "prescription": {"items": items, "notes": notes},
    })
    audit(s, origin.actor, "visit.amend", "visit", v.id, {"amends": target.id, "reason": reason, "device": origin.device_id})
    return v, conflict


def list_visits(s: Session, patient_id: str, include_superseded: bool = False) -> list[Visit]:
    stmt = (
        select(Visit)
        .where(Visit.patient_id == patient_id)
        .options(selectinload(Visit.prescription).selectinload(Prescription.items))
        .order_by(Visit.visit_date.desc(), Visit.created_at.desc())
    )
    if not include_superseded:
        stmt = stmt.where(Visit.superseded.is_(False))
    return list(s.scalars(stmt))


def visit_history(s: Session, visit_id: str) -> list[dict]:
    v = get_visit(s, visit_id)
    rows = s.scalars(select(Visit).where(Visit.root_id == v.root_id).order_by(Visit.created_at))
    return [visit_dict(r) for r in rows]


def copy_previous_prescription(s: Session, visit_id: str) -> list[dict]:
    """Medicines of a visit's prescription, ready to load into a new one."""
    v = get_visit(s, visit_id)
    if v.superseded:
        v = s.scalar(select(Visit).where(Visit.root_id == v.root_id, Visit.superseded.is_(False))) or v
    return rx_items(v.prescription)


def last_prescription(s: Session, patient_id: str) -> dict | None:
    for v in list_visits(s, patient_id):
        if v.prescription and v.prescription.items:
            return {"visit_id": v.id, "visit_date": v.visit_date.isoformat(), "items": rx_items(v.prescription)}
    return None


def todays_visits(s: Session) -> list[dict]:
    start = datetime.combine(date.today(), datetime.min.time())
    rows = s.execute(
        select(Visit, Patient)
        .join(Patient, Patient.id == Visit.patient_id)
        .where(Visit.visit_date >= start, Visit.superseded.is_(False))
        .order_by(Visit.visit_date.desc())
    ).all()
    return [
        {"visit_id": v.id, "visit_date": v.visit_date.isoformat(), "patient_id": p.id,
         "patient_number": p.patient_number, "full_name": p.full_name, "diagnosis": v.diagnosis,
         "chief_complaint": v.chief_complaint}
        for v, p in rows
    ]


def due_follow_ups(s: Session, days: int = 7) -> list[dict]:
    today = date.today()
    rows = s.execute(
        select(Visit, Patient)
        .join(Patient, Patient.id == Visit.patient_id)
        .where(Visit.superseded.is_(False), Visit.follow_up_date.is_not(None), Visit.follow_up_date >= today.isoformat())
        .order_by(Visit.follow_up_date)
    ).all()
    out = []
    for v, p in rows:
        try:
            d = date.fromisoformat(v.follow_up_date)
        except ValueError:
            continue
        if (d - today).days <= days:
            out.append({"visit_id": v.id, "follow_up_date": v.follow_up_date, "patient_id": p.id,
                        "patient_number": p.patient_number, "full_name": p.full_name, "phone": p.phone})
    return out
