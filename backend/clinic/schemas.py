"""Pydantic request schemas (responses are plain dicts from the services)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SetupIn(BaseModel):
    clinic_name: str = Field(min_length=1, max_length=200)
    doctor_name: str = Field(default="", max_length=200)
    username: str = Field(min_length=2, max_length=64)
    full_name: str = Field(default="", max_length=200)
    password: str = Field(min_length=8, max_length=256)


class LoginIn(BaseModel):
    username: str
    password: str
    scope: str = "desktop"


class PatientIn(BaseModel):
    full_name: str | None = None
    sex: str | None = None
    date_of_birth: str | None = None
    age_years: int | None = None
    phone: str | None = None
    alt_phone: str | None = None
    email: str | None = None
    address: str | None = None
    blood_group: str | None = None
    allergies: str | None = None
    chronic_conditions: str | None = None
    notes: str | None = None
    archived: bool | None = None

    def data(self) -> dict:
        return self.model_dump(exclude_unset=True)


class RxItemIn(BaseModel):
    medicine_id: str | None = None
    medicine_name: str = ""
    form: str = ""
    strength: str = ""
    dose: str = ""
    frequency: str = ""
    timing: str = ""
    duration: str = ""
    quantity: str = ""
    instructions: str = ""


class RxIn(BaseModel):
    items: list[RxItemIn] = []
    notes: str = ""


class VisitIn(BaseModel):
    visit_date: str | None = None
    chief_complaint: str | None = None
    history: str | None = None
    examination: str | None = None
    diagnosis: str | None = None
    advice: str | None = None
    notes: str | None = None
    follow_up_date: str | None = None
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    pulse: int | None = None
    temperature: float | None = None
    weight: float | None = None
    height: float | None = None
    spo2: int | None = None
    resp_rate: int | None = None
    prescription: RxIn | None = None

    def fields(self) -> dict:
        d = self.model_dump(exclude_unset=True, exclude={"prescription"})
        return d

    def rx(self) -> dict | None:
        return self.prescription.model_dump() if self.prescription is not None else None


class AmendIn(VisitIn):
    reason: str = ""


class MedicineIn(BaseModel):
    name: str | None = None
    generic_name: str | None = None
    form: str | None = None
    strength: str | None = None
    category: str | None = None
    default_dose: str | None = None
    default_frequency: str | None = None
    default_duration: str | None = None
    default_instructions: str | None = None
    active: bool | None = None


class ClinicIn(BaseModel):
    clinic_name: str | None = None
    clinic_address: str | None = None
    clinic_phone: str | None = None
    clinic_email: str | None = None
    doctor_name: str | None = None
    doctor_qualifications: str | None = None
    doctor_registration: str | None = None
    footer_note: str | None = None
    paper_size: str | None = None


class RuntimeIn(BaseModel):
    network_access: bool | None = None
    backup_retention: int | None = Field(default=None, ge=1, le=365)
    auto_backup_hours: int | None = Field(default=None, ge=0, le=24 * 30)


class UserIn(BaseModel):
    username: str
    full_name: str = ""
    password: str
    role: str = "doctor"


class PasswordIn(BaseModel):
    current_password: str | None = None
    new_password: str


class RestoreIn(BaseModel):
    name: str
    password: str


class PairIn(BaseModel):
    code: str
    device_name: str = "Phone"


class PushIn(BaseModel):
    events: list[dict]


class ResolveIn(BaseModel):
    use_other: bool = False
