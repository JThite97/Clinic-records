"""Sprint 5: document vault."""
import hashlib


def test_upload_copy_checksum_and_verify(client, admin, patient, home, tmp_path):
    src = tmp_path / "cbc report.pdf"
    data = b"%PDF-1.4 fake lab report " * 100
    src.write_bytes(data)
    with src.open("rb") as f:
        r = client.post(f"/api/patients/{patient['id']}/documents", files={"file": (src.name, f, "application/pdf")},
                        data={"title": "CBC", "category": "lab"}, headers=admin)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["sha256"] == hashlib.sha256(data).hexdigest()
    src.unlink()  # deleting the original does not affect the stored copy
    stored = list((home / "documents" / "patients" / patient["patient_number"]).iterdir())
    assert len(stored) == 1
    r = client.get(f"/api/documents/{doc['id']}/file", headers=admin)
    assert r.content == data
    assert client.post(f"/api/documents/{doc['id']}/verify", headers=admin).json()["ok"]
    stored[0].write_bytes(b"tampered")
    assert client.post(f"/api/documents/{doc['id']}/verify", headers=admin).json()["ok"] is False


def test_reject_bad_type_and_archive(client, admin, patient):
    r = client.post(f"/api/patients/{patient['id']}/documents", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, headers=admin)
    assert r.status_code == 422
    r = client.post(f"/api/patients/{patient['id']}/documents", files={"file": ("xray.png", b"\x89PNG....", "image/png")}, headers=admin)
    did = r.json()["id"]
    client.post(f"/api/documents/{did}/archive/true", headers=admin)
    assert client.get(f"/api/patients/{patient['id']}/documents", headers=admin).json() == []
    assert len(client.get(f"/api/patients/{patient['id']}/documents?archived=true", headers=admin).json()) == 1
