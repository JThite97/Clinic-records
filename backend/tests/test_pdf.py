"""Sprint 6: PDFs fit on one page for a single visit (A4 and Letter)."""
import pytest

from clinic.services.pdf_service import page_count, patient_record_pdf, prescription_pdf

PATIENT = {"full_name": "Ravi Kumar", "patient_number": "P000001", "age": 42, "sex": "M", "phone": "9876543210",
           "blood_group": "B+", "allergies": "Penicillin, sulfa drugs"}


def _visit(n_items=6, long=False):
    text = ("Patient reports intermittent fever with chills, body ache and headache. " * (12 if long else 1)).strip()
    return {
        "visit_date": "2026-11-17T10:30:00", "chief_complaint": text, "history": text, "examination": text,
        "diagnosis": "Viral fever; rule out dengue", "advice": "Plenty of fluids. " * (10 if long else 1),
        "follow_up_date": "2026-11-20", "bp_systolic": 120, "bp_diastolic": 80, "pulse": 88, "temperature": 38.2, "spo2": 98, "weight": 70,
        "prescription": {"notes": "", "items": [
            {"medicine_name": f"Medicine number {i} 500 mg", "form": "Tablet", "dose": "1 tab", "frequency": "1-0-1",
             "timing": "After food", "duration": "5 days", "quantity": "10", "instructions": "Take with water"} for i in range(n_items)]},
    }


CLINIC = {"clinic_name": "Sunrise Clinic", "clinic_address": "12 MG Road\nPune 411001", "clinic_phone": "020-1234567",
          "doctor_name": "Dr. Asha Rao", "doctor_qualifications": "MBBS, MD (Medicine)", "doctor_registration": "MMC 12345",
          "footer_note": "Valid for 30 days"}


@pytest.mark.parametrize("paper", ["A4", "Letter"])
@pytest.mark.parametrize("items,long", [(3, False), (12, False), (25, True)])
def test_prescription_single_page(paper, items, long):
    pdf = prescription_pdf(_visit(items, long), PATIENT, {**CLINIC, "paper_size": paper})
    assert pdf.startswith(b"%PDF")
    assert page_count(pdf) == 1


def test_letter_page_size():
    pdf = prescription_pdf(_visit(), PATIENT, {**CLINIC, "paper_size": "Letter"})
    assert b"612 792" in pdf


def test_patient_record_multi_visit():
    pdf = patient_record_pdf(PATIENT, [_visit(5, True) for _ in range(6)], [{"title": "CBC", "category": "lab", "original_filename": "cbc.pdf", "uploaded_at": "2026-11-17T10:00:00"}], CLINIC)
    assert page_count(pdf) >= 2


def test_pdf_endpoints_with_logo(client, admin, patient):
    import io


    png = _tiny_png()
    assert client.post("/api/settings/asset/logo", files={"file": ("logo.png", io.BytesIO(png), "image/png")}, headers=admin).status_code == 200
    v = client.post(f"/api/patients/{patient['id']}/visits", json={"diagnosis": "x", "prescription": {"items": [{"medicine_name": "A"}]}}, headers=admin).json()
    r = client.get(f"/api/visits/{v['id']}/prescription.pdf", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    r = client.post(f"/api/visits/{v['id']}/prescription.pdf/export", headers=admin)
    from pathlib import Path

    assert Path(r.json()["path"]).exists()


def _tiny_png() -> bytes:
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\x0f\x76\x6e" * 8 for _ in range(8))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
