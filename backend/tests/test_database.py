"""Sprint 1: tables, relations, cascades and encryption at rest."""
import pytest
from sqlalchemy import inspect, select, text

from clinic.database import DatabaseKeyError, make_engine
from clinic.models import Document, Patient, Prescription, PrescriptionItem, Visit
from clinic.services.common import Origin
from clinic.services import patient_service, visit_service


def test_all_tables_created(state, admin):
    names = set(inspect(state.db.engine).get_table_names())
    for t in ("users", "patients", "visits", "medicines", "prescriptions", "prescription_items", "documents",
              "audit_log", "sync_events", "devices", "sync_conflicts", "settings", "counters"):
        assert t in names


def test_foreign_keys_enforced(state, admin):
    with state.db.engine.connect() as c:
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_cascade_delete_patient_removes_children(state, admin, home):
    with state.db.session() as s:
        p = patient_service.create_patient(s, {"full_name": "Temp"}, Origin("t"))
        v = visit_service.create_visit(s, p.id, {"diagnosis": "x"}, {"items": [{"medicine_name": "A"}]}, Origin("t"))
        s.add(Document(patient_id=p.id, original_filename="a.pdf", stored_path="x", sha256="0" * 64))
        pid, vid = p.id, v.id
    with state.db.session() as s:
        s.delete(s.get(Patient, pid))
    with state.db.session() as s:
        assert s.get(Visit, vid) is None
        assert s.scalars(select(Prescription)).all() == []
        assert s.scalars(select(PrescriptionItem)).all() == []
        assert s.scalars(select(Document)).all() == []


def test_database_file_is_encrypted(state, admin, home):
    raw = (home / "data" / "clinic.db").read_bytes()[:16]
    assert raw != b"SQLite format 3\x00"


def test_wrong_key_is_rejected(state, admin, home):
    with pytest.raises(DatabaseKeyError):
        make_engine(home / "data" / "clinic.db", b"\x00" * 32)


def test_logs_written(admin, home):
    assert (home / "logs" / "clinic.log").exists()
