"""Schema creation and first-run seeding."""
from __future__ import annotations

import json
import logging
from importlib import resources

from sqlalchemy import func, select

from .database import Database
from .models import Base, Medicine, Setting

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DEFAULT_CLINIC = {
    "clinic_name": "My Clinic",
    "clinic_address": "",
    "clinic_phone": "",
    "clinic_email": "",
    "doctor_name": "",
    "doctor_qualifications": "",
    "doctor_registration": "",
    "footer_note": "",
    "paper_size": "A4",  # A4 | Letter
    "logo_path": "",  # relative to documents/
    "signature_path": "",
}


def load_medicine_seed() -> list[dict]:
    with resources.files("clinic.data").joinpath("medicines.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def init_schema(db: Database) -> None:
    Base.metadata.create_all(db.engine)
    with db.session() as s:
        if s.get(Setting, "schema_version") is None:
            s.add(Setting(key="schema_version", value=SCHEMA_VERSION))
        if s.get(Setting, "clinic") is None:
            s.add(Setting(key="clinic", value=dict(DEFAULT_CLINIC)))
        if (s.scalar(select(func.count()).select_from(Medicine)) or 0) == 0:
            seed = load_medicine_seed()
            s.add_all(Medicine(**m) for m in seed)
            log.info("seeded %d medicines", len(seed))
