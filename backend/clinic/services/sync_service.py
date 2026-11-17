"""Sprint 0 sync layer: the desktop is the hub, phones sync when it is on.

Protocol
--------
* A phone is paired once with a short code shown on the desktop and gets a
  long-lived device token (only its SHA-256 is stored).
* ``push``: the phone sends the events from its outbox. Each event is
  applied with the same service functions the desktop uses, inside its own
  savepoint. Events are idempotent by ``event_id``: re-sending is harmless.
* ``pull``: the phone asks for every event after its cursor (``seq``), in
  server order, and applies them to its local copy.

Conflict rules
--------------
* Visits, prescriptions, documents: append-only. Two devices amending the
  same visit produce two amendments; both are kept and the pair is flagged.
* Patient demographics: per-field last-write-wins on (client_ts, device_id).
  The losing value is kept in ``sync_conflicts`` for the doctor to review.
* Everything is recorded in the immutable event log and the audit trail.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Device, Patient, SyncConflict, SyncEvent, Visit, utcnow
from . import patient_service, visit_service
from .common import Conflict, NotFound, Origin, ValidationFailed, audit

log = logging.getLogger(__name__)

PAIRING_TTL = 600  # seconds
MAX_PUSH = 500
MAX_PULL = 1000


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_pairing_code(codes: dict[str, float]) -> str:
    now = time.time()
    for c, exp in list(codes.items()):
        if exp < now:
            codes.pop(c, None)
    code = f"{secrets.randbelow(10**6):06d}"
    codes[code] = now + PAIRING_TTL
    return code


def pair_device(s: Session, codes: dict[str, float], code: str, name: str) -> tuple[Device, str]:
    exp = codes.pop((code or "").strip(), None)
    if not exp or exp < time.time():
        raise ValidationFailed("Pairing code is invalid or expired")
    token = secrets.token_urlsafe(32)
    dev = Device(id=f"dev-{secrets.token_hex(6)}", name=(name or "Phone").strip()[:120], token_hash=token_hash(token))
    s.add(dev)
    s.flush()
    audit(s, "system", "device.pair", "device", dev.id, {"name": dev.name})
    return dev, token


def authenticate_device(s: Session, token: str) -> Device | None:
    if not token:
        return None
    dev = s.scalar(select(Device).where(Device.token_hash == token_hash(token)))
    if dev is None or dev.revoked:
        return None
    dev.last_seen = utcnow()
    return dev


def _apply(s: Session, dev: Device, ev: dict) -> dict:
    entity, op = ev.get("entity"), ev.get("op")
    payload = ev.get("payload") or {}
    origin = Origin(actor=f"device:{dev.name}", device_id=dev.id, ts=int(ev.get("client_ts") or time.time() * 1000), event_id=ev["event_id"])
    eid = ev.get("entity_id")
    if entity == "patient" and op == "create":
        p = patient_service.create_patient(s, payload.get("fields") or {}, origin, patient_id=eid)
        return {"patient_number": p.patient_number}
    if entity == "patient" and op == "update":
        _, conflicts = patient_service.update_patient(s, eid, payload.get("fields") or {}, origin, base=payload.get("base"))
        return {"conflicts": [c.field for c in conflicts]}
    if entity == "visit" and op == "create":
        visit_service.create_visit(s, payload["patient_id"], payload.get("fields") or {}, payload.get("prescription"), origin, visit_id=eid)
        return {}
    if entity == "visit" and op == "amend":
        _, conflict = visit_service.amend_visit(s, payload["amends_id"], payload.get("fields") or {}, payload.get("prescription"),
                                                payload.get("reason") or "Amended on phone", origin, new_visit_id=eid)
        return {"conflict": bool(conflict)}
    raise ValidationFailed(f"unsupported event {entity}.{op}")


def push(s: Session, dev: Device, events: list[dict]) -> dict:
    if len(events) > MAX_PUSH:
        raise ValidationFailed(f"at most {MAX_PUSH} events per push")
    results = []
    for ev in events:
        event_id = str(ev.get("event_id") or "")
        if not event_id:
            results.append({"event_id": None, "status": "rejected", "error": "missing event_id"})
            continue
        if s.scalar(select(SyncEvent.seq).where(SyncEvent.event_id == event_id)) is not None:
            results.append({"event_id": event_id, "status": "duplicate"})
            continue
        sp = s.begin_nested()
        try:
            info = _apply(s, dev, ev)
            sp.commit()
            results.append({"event_id": event_id, "status": "applied", **info})
        except (ValidationFailed, NotFound, Conflict, KeyError, ValueError, TypeError) as e:
            sp.rollback()
            log.warning("sync event %s rejected: %s", event_id, e)
            results.append({"event_id": event_id, "status": "rejected", "error": str(e)})
    s.flush()
    return {"results": results, "cursor": current_cursor(s)}


def current_cursor(s: Session) -> int:
    return s.scalar(select(func.max(SyncEvent.seq))) or 0


def pull(s: Session, dev: Device | None, since: int, limit: int = MAX_PULL) -> dict:
    limit = max(1, min(limit, MAX_PULL))
    rows = list(s.scalars(select(SyncEvent).where(SyncEvent.seq > since).order_by(SyncEvent.seq).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    if dev is not None and rows:
        dev.last_pull_seq = rows[-1].seq
    return {
        "events": [
            {"seq": r.seq, "event_id": r.event_id, "device_id": r.device_id, "entity": r.entity,
             "entity_id": r.entity_id, "op": r.op, "payload": r.payload, "client_ts": r.client_ts}
            for r in rows
        ],
        "cursor": rows[-1].seq if rows else since,
        "more": more,
    }


def list_conflicts(s: Session, include_resolved: bool = False) -> list[dict]:
    stmt = select(SyncConflict).order_by(SyncConflict.created_at.desc())
    if not include_resolved:
        stmt = stmt.where(SyncConflict.resolved.is_(False))
    out = []
    for c in s.scalars(stmt):
        label = c.entity_id
        if c.entity == "patient":
            p = s.get(Patient, c.entity_id)
            label = f"{p.patient_number} {p.full_name}" if p else c.entity_id
        elif c.entity == "visit":
            v = s.scalar(select(Visit).where(Visit.root_id == c.entity_id).limit(1))
            if v:
                p = s.get(Patient, v.patient_id)
                label = f"Visit {v.visit_date:%d %b %Y} - {p.full_name if p else ''}"
        out.append({"id": c.id, "entity": c.entity, "entity_id": c.entity_id, "label": label, "field": c.field, "kind": c.kind,
                    "kept_value": c.kept_value, "other_value": c.other_value, "kept_device": c.kept_device,
                    "other_device": c.other_device, "resolved": c.resolved, "created_at": c.created_at.isoformat()})
    return out


def resolve_conflict(s: Session, conflict_id: int, use_other: bool, actor: str) -> None:
    c = s.get(SyncConflict, conflict_id)
    if c is None:
        raise NotFound("conflict not found")
    if c.resolved:
        return
    if use_other and c.entity == "patient" and c.kind == "field":
        # The doctor's decision must win even over phone clocks running ahead.
        p = patient_service.get_patient(s, c.entity_id)
        cur_ts = int(((p.field_versions or {}).get(c.field) or [0])[0])
        origin = Origin(actor=actor)
        origin.ts = max(origin.ts, cur_ts + 1)
        patient_service.update_patient(s, c.entity_id, {c.field: c.other_value}, origin)
    c.resolved = True
    c.resolved_by = actor
    s.flush()
    audit(s, actor, "sync.resolve", c.entity, c.entity_id, {"conflict": c.id, "field": c.field, "used": "other" if use_other else "kept"})
