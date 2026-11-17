"""Medicine library: typeahead search and custom entries."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Medicine
from .common import NotFound, ValidationFailed, audit

FIELDS = ("name", "generic_name", "form", "strength", "category", "default_dose",
          "default_frequency", "default_duration", "default_instructions", "active")


def medicine_dict(m: Medicine) -> dict:
    d = {f: getattr(m, f) for f in FIELDS}
    d.update(id=m.id, is_custom=m.is_custom, usage_count=m.usage_count)
    return d


def search_medicines(s: Session, q: str, limit: int = 15, include_inactive: bool = False) -> list[dict]:
    q = (q or "").strip().lower()
    stmt = select(Medicine)
    if not include_inactive:
        stmt = stmt.where(Medicine.active.is_(True))
    if q:
        terms = q.split()
        for t in terms:
            like = f"%{t}%"
            stmt = stmt.where(or_(Medicine.name.ilike(like), Medicine.generic_name.ilike(like), Medicine.category.ilike(like)))
    rows = list(s.scalars(stmt.limit(400)))

    def rank(m: Medicine):
        n = m.name.lower()
        starts = 0 if q and n.startswith(q) else 1
        word = 0 if q and any(w.startswith(q.split()[0]) for w in n.split()) else 1
        return (starts, word, -m.usage_count, n)

    rows.sort(key=rank)
    return [medicine_dict(m) for m in rows[:limit]]


def create_medicine(s: Session, data: dict, actor: str) -> Medicine:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationFailed("Medicine name is required")
    m = Medicine(**{f: (data.get(f) or "") for f in FIELDS if f != "active"}, is_custom=True, active=True)
    m.name = name
    s.add(m)
    s.flush()
    audit(s, actor, "medicine.create", "medicine", m.id, {"name": name})
    return m


def update_medicine(s: Session, medicine_id: str, data: dict, actor: str) -> Medicine:
    m = s.get(Medicine, medicine_id)
    if m is None:
        raise NotFound("medicine not found")
    for f in FIELDS:
        if f in data and data[f] is not None:
            setattr(m, f, data[f] if f == "active" else str(data[f]).strip())
    if not m.name:
        raise ValidationFailed("Medicine name is required")
    s.flush()
    audit(s, actor, "medicine.update", "medicine", m.id, {"fields": sorted(k for k in data if k in FIELDS)})
    return m
