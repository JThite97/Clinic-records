"""ORM models.

Identifiers are UUID strings so that records can be created on a phone
while the desktop is off and merged later without collisions. Patients also
get a human friendly ``patient_number`` (P000001) assigned by the desktop.

Clinical records (visits, prescriptions, documents) are append-only: a
correction is a new *amendment* row that supersedes the old one, which is
kept forever.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default="doctor")  # admin|doctor|staff
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | None] = mapped_column(JSON)


class Counter(Base):
    """Monotonic counters (patient numbers)."""

    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    patient_number: Mapped[str | None] = mapped_column(String(16), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    sex: Mapped[str] = mapped_column(String(10), default="")  # M|F|O|""
    date_of_birth: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    age_years: Mapped[int | None] = mapped_column(Integer)  # when DOB unknown
    phone: Mapped[str] = mapped_column(String(32), default="", index=True)
    alt_phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    blood_group: Mapped[str] = mapped_column(String(8), default="")
    allergies: Mapped[str] = mapped_column(Text, default="")
    chronic_conditions: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # Per-field last-write timestamps (ms) and writer, for sync LWW.
    field_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    visits: Mapped[list["Visit"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )


PATIENT_FIELDS = (
    "full_name",
    "sex",
    "date_of_birth",
    "age_years",
    "phone",
    "alt_phone",
    "email",
    "address",
    "blood_group",
    "allergies",
    "chronic_conditions",
    "notes",
    "archived",
)


class Visit(Base):
    __tablename__ = "visits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    # The first version of this visit; amendments share it.
    root_id: Mapped[str] = mapped_column(String(36), index=True)
    amends_id: Mapped[str | None] = mapped_column(ForeignKey("visits.id"))
    amendment_reason: Mapped[str] = mapped_column(Text, default="")
    superseded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=True)

    visit_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    chief_complaint: Mapped[str] = mapped_column(Text, default="")
    history: Mapped[str] = mapped_column(Text, default="")
    examination: Mapped[str] = mapped_column(Text, default="")
    diagnosis: Mapped[str] = mapped_column(Text, default="")
    advice: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    follow_up_date: Mapped[str | None] = mapped_column(String(10))

    bp_systolic: Mapped[int | None] = mapped_column(Integer)
    bp_diastolic: Mapped[int | None] = mapped_column(Integer)
    pulse: Mapped[int | None] = mapped_column(Integer)
    temperature: Mapped[float | None] = mapped_column(Float)  # deg C
    weight: Mapped[float | None] = mapped_column(Float)  # kg
    height: Mapped[float | None] = mapped_column(Float)  # cm
    spo2: Mapped[int | None] = mapped_column(Integer)
    resp_rate: Mapped[int | None] = mapped_column(Integer)

    created_by: Mapped[str] = mapped_column(String(64), default="")
    device_id: Mapped[str] = mapped_column(String(64), default="desktop")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="visits")
    prescription: Mapped["Prescription | None"] = relationship(
        back_populates="visit", cascade="all, delete-orphan", uselist=False, passive_deletes=True
    )

    __table_args__ = (Index("ix_visits_patient_date", "patient_id", "visit_date"),)


VISIT_FIELDS = (
    "visit_date",
    "chief_complaint",
    "history",
    "examination",
    "diagnosis",
    "advice",
    "notes",
    "follow_up_date",
    "bp_systolic",
    "bp_diastolic",
    "pulse",
    "temperature",
    "weight",
    "height",
    "spo2",
    "resp_rate",
)


class Medicine(Base):
    __tablename__ = "medicines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), index=True)  # display / brand
    generic_name: Mapped[str] = mapped_column(String(200), default="", index=True)
    form: Mapped[str] = mapped_column(String(40), default="")  # Tablet, Syrup...
    strength: Mapped[str] = mapped_column(String(60), default="")
    category: Mapped[str] = mapped_column(String(80), default="")
    default_dose: Mapped[str] = mapped_column(String(60), default="")
    default_frequency: Mapped[str] = mapped_column(String(60), default="")
    default_duration: Mapped[str] = mapped_column(String(60), default="")
    default_instructions: Mapped[str] = mapped_column(String(200), default="")
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Prescription(Base):
    __tablename__ = "prescriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    visit_id: Mapped[str] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), unique=True, index=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    visit: Mapped[Visit] = relationship(back_populates="prescription")
    items: Mapped[list["PrescriptionItem"]] = relationship(
        back_populates="prescription",
        cascade="all, delete-orphan",
        order_by="PrescriptionItem.position",
        passive_deletes=True,
    )


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prescription_id: Mapped[str] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    medicine_id: Mapped[str | None] = mapped_column(String(36))
    medicine_name: Mapped[str] = mapped_column(String(200))
    form: Mapped[str] = mapped_column(String(40), default="")
    strength: Mapped[str] = mapped_column(String(60), default="")
    dose: Mapped[str] = mapped_column(String(60), default="")  # e.g. 1 tab
    frequency: Mapped[str] = mapped_column(String(60), default="")  # e.g. 1-0-1
    timing: Mapped[str] = mapped_column(String(60), default="")  # after food
    duration: Mapped[str] = mapped_column(String(60), default="")  # 5 days
    quantity: Mapped[str] = mapped_column(String(30), default="")
    instructions: Mapped[str] = mapped_column(String(300), default="")

    prescription: Mapped[Prescription] = relationship(back_populates="items")


RX_ITEM_FIELDS = (
    "medicine_id",
    "medicine_name",
    "form",
    "strength",
    "dose",
    "frequency",
    "timing",
    "duration",
    "quantity",
    "instructions",
)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    visit_id: Mapped[str | None] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(40), default="lab")
    original_filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(500))  # relative to documents/
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[str] = mapped_column(String(64), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="documents")


class AuditLog(Base):
    """Hash-chained audit trail: each row stores the hash of the previous one,
    so any later edit or deletion of a row breaks the chain detectably."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")


class SyncEvent(Base):
    """The event log: every change, from any device, in server order."""

    __tablename__ = "sync_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    op: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    client_ts: Mapped[int] = mapped_column(Integer)  # ms since epoch, writer clock
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    last_pull_seq: Mapped[int] = mapped_column(Integer, default=0)


class SyncConflict(Base):
    __tablename__ = "sync_conflicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    field: Mapped[str] = mapped_column(String(64), default="")
    kept_value: Mapped[dict | list | str | int | float | None] = mapped_column(JSON)
    other_value: Mapped[dict | list | str | int | float | None] = mapped_column(JSON)
    kept_device: Mapped[str] = mapped_column(String(64), default="")
    other_device: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(32), default="field")  # field|amendment
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
