"""Patients: numbering, create/update with per-field versions, fuzzy search."""
from __future__ import annotations

import logging
import re

from rapidfuzz import fuzz
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import PATIENT_FIELDS, Counter, Patient, SyncConflict
from .common import Conflict, NotFound, Origin, ValidationFailed, audit, emit, patient_dict

log = logging.getLogger(__name__)

NUMBER_RE = re.compile(r"^P?0*(\d{1,9})$", re.I)


def format_number(n: int) -> str:
    return f"P{n:06d}"


def next_patient_number(s: Session) -> str:
    """Deterministic, gap-free within a transaction: P000001, P000002, ..."""
    c = s.get(Counter, "patient")
    if c is None:
        c = Counter(name="patient", value=0)
        s.add(c)
        s.flush()
    s.execute(update(Counter).where(Counter.name == "patient").values(value=Counter.value + 1))
    s.refresh(c)
    return format_number(c.value)


def _clean(data: dict) -> dict:
    out = {}
    for k, v in data.items():
        if k not in PATIENT_FIELDS:
            continue
        if isinstance(v, str):
            v = v.strip()
        if k in ("date_of_birth",) and v == "":
            v = None
        if k == "age_years" and v in ("", None):
            v = None
        out[k] = v
    if "full_name" in out and not out["full_name"]:
        raise ValidationFailed("Patient name is required")
    return out


def get_patient(s: Session, patient_id: str) -> Patient:
    p = s.get(Patient, patient_id)
    if p is None:
        p = s.scalar(select(Patient).where(Patient.patient_number == patient_id.upper()))
    if p is None:
        raise NotFound("patient not found")
    return p


def create_patient(s: Session, data: dict, origin: Origin, patient_id: str | None = None) -> Patient:
    fields = _clean(data)
    if not fields.get("full_name"):
        raise ValidationFailed("Patient name is required")
    if patient_id and s.get(Patient, patient_id) is not None:
        raise Conflict("patient already exists")
    p = Patient(**fields)
    if patient_id:
        p.id = patient_id
    p.patient_number = next_patient_number(s)
    p.created_by = origin.actor
    p.field_versions = {f: [origin.ts, origin.device_id] for f in fields}
    s.add(p)
    s.flush()
    emit(s, origin, "patient", p.id, "create", {"fields": fields, "patient_number": p.patient_number})
    audit(s, origin.actor, "patient.create", "patient", p.id, {"number": p.patient_number, "name": p.full_name, "device": origin.device_id})
    log.info("patient created %s", p.patient_number)
    return p


def _norm(v):
    return "" if v is None else v


def _wins(incoming: tuple[int, str], current: list | None) -> bool:
    if not current:
        return True
    cur_ts, cur_dev = int(current[0]), str(current[1])
    return (incoming[0], incoming[1]) > (cur_ts, cur_dev)


def update_patient(s: Session, patient_id: str, changes: dict, origin: Origin, base: dict | None = None) -> tuple[Patient, list[SyncConflict]]:
    """Per-field last-write-wins.

    ``base`` (optional) holds the values the writer saw before editing. If the
    stored value differs from ``base`` the field was changed elsewhere in the
    meantime; the overwritten value is recorded as a conflict for review.
    """
    p = get_patient(s, patient_id)
    fields = _clean(changes)
    versions = dict(p.field_versions or {})
    applied: dict = {}
    conflicts: list[SyncConflict] = []
    for f, new in fields.items():
        cur = getattr(p, f)
        if cur == new:
            versions[f] = max(versions.get(f) or [0, ""], [origin.ts, origin.device_id])
            continue
        cur_ver = versions.get(f)
        if _wins((origin.ts, origin.device_id), cur_ver):
            if base is not None and f in base and _norm(base[f]) != _norm(cur):
                conflicts.append(SyncConflict(
                    entity="patient", entity_id=p.id, field=f, kept_value=new, other_value=cur,
                    kept_device=origin.device_id, other_device=(cur_ver or ["", ""])[1],
                ))
            setattr(p, f, new)
            versions[f] = [origin.ts, origin.device_id]
            applied[f] = new
        else:
            conflicts.append(SyncConflict(
                entity="patient", entity_id=p.id, field=f, kept_value=cur, other_value=new,
                kept_device=(cur_ver or ["", ""])[1], other_device=origin.device_id,
            ))
    p.field_versions = versions
    for c in conflicts:
        s.add(c)
    s.flush()
    if applied or conflicts or origin.device_id != "desktop":
        emit(s, origin, "patient", p.id, "update", {"fields": fields, "base": base or {}})
    if applied:
        audit(s, origin.actor, "patient.update", "patient", p.id, {"changed": sorted(applied), "device": origin.device_id})
    if conflicts:
        audit(s, origin.actor, "sync.conflict", "patient", p.id, {"fields": [c.field for c in conflicts]})
    return p, conflicts


def search_patients(s: Session, q: str, limit: int = 25, include_archived: bool = False) -> list[dict]:
    """Fuzzy search on name, patient number and phone.

    Loads the compact (id, number, name, phone) index and scores it with
    RapidFuzz; ~2-5 ms for 1,000 patients.
    """
    q = (q or "").strip()
    stmt = select(Patient.id, Patient.patient_number, Patient.full_name, Patient.phone, Patient.updated_at)
    if not include_archived:
        stmt = stmt.where(Patient.archived.is_(False))
    if not q:
        rows = s.execute(stmt.order_by(Patient.updated_at.desc()).limit(limit)).all()
        ids = [r.id for r in rows]
    else:
        rows = s.execute(stmt).all()
        ql = q.lower()
        digits = re.sub(r"\D", "", q)
        m = NUMBER_RE.match(q)
        num = format_number(int(m.group(1))) if m else None
        scored: list[tuple[float, str, str]] = []
        for r in rows:
            score = 0.0
            if num and r.patient_number == num:
                score = 200
            elif len(digits) >= 4 and digits in re.sub(r"\D", "", r.phone or ""):
                score = 150
            else:
                name = (r.full_name or "").lower()
                if name.startswith(ql):
                    score = 120
                elif any(part.startswith(ql) for part in name.split()):
                    score = 110
                elif ql in name:
                    score = 100
                else:
                    sc = max(fuzz.WRatio(ql, name), fuzz.partial_ratio(ql, name) * 0.95)
                    score = sc if sc >= 70 else 0
            if score:
                scored.append((score, r.full_name or "", r.id))
        scored.sort(key=lambda t: (-t[0], t[1].lower()))
        ids = [t[2] for t in scored[:limit]]
    if not ids:
        return []
    by_id = {p.id: p for p in s.scalars(select(Patient).where(Patient.id.in_(ids)))}
    return [patient_dict(by_id[i]) for i in ids if i in by_id]
