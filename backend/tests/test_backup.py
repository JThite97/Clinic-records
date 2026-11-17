"""Sprint 7: encrypted backups, retention, restore with safety snapshot."""
import io
import os
import time

import pyzipper
import pytest

from conftest import PASSWORD, login
from clinic.main import auto_backup_tick
from clinic.services.backup_service import BackupService


def _svc(state):
    return BackupService(state.paths, state.keystore)


def test_create_and_verify(client, admin, patient, state):
    client.post(f"/api/patients/{patient['id']}/documents", files={"file": ("lab.pdf", b"%PDF lab", "application/pdf")}, headers=admin)
    r = client.post("/api/backups", headers=admin)
    assert r.status_code == 200
    assert r.json()["verify"]["ok"] and r.json()["verify"]["files"] == 2
    path = state.paths.backups / r.json()["name"]
    # The archive is AES encrypted: no password, no content.
    with pyzipper.AESZipFile(path) as zf:
        with pytest.raises(RuntimeError):
            zf.read("manifest.json")
        assert zf.getinfo("clinic.db").flag_bits & 0x1  # encrypted entry


def test_wrong_key_and_tamper_detected(admin, state):
    path = _svc(state).create_backup(state.data_key)
    assert _svc(state).verify_backup(path, b"\x01" * 32)["ok"] is False
    data = bytearray(path.read_bytes())
    data[200] ^= 0xFF
    path.write_bytes(bytes(data))
    assert _svc(state).verify_backup(path, state.data_key)["ok"] is False


def test_retention_keeps_last_n(admin, state):
    svc = _svc(state)
    for i in range(5):
        p = svc.create_backup(state.data_key, "auto")
        os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
    removed = svc.prune(3)
    assert len(removed) == 2
    assert len(svc.list_backups()) == 3


def test_auto_backup_tick(admin, state):
    assert auto_backup_tick(state) is not None  # none yet: back up now
    assert auto_backup_tick(state) is None  # fresh one exists


def test_restore_with_snapshot(client, admin, patient, state):
    name = client.post("/api/backups", headers=admin).json()["name"]
    client.post("/api/patients", json={"full_name": "Added After Backup"}, headers=admin)
    assert len(client.get("/api/patients", headers=admin).json()) == 2
    r = client.post("/api/backups/restore", json={"name": name, "password": "wrong-password"}, headers=admin)
    assert r.status_code == 400
    r = client.post("/api/backups/restore", json={"name": name, "password": PASSWORD}, headers=admin)
    assert r.status_code == 200, r.text
    snap = r.json()["snapshot"]
    assert "pre-restore" in snap
    assert client.get("/api/patients", headers=admin).status_code == 401  # must log in again
    h = login(client, "asha", PASSWORD)
    names = [p["full_name"] for p in client.get("/api/patients", headers=h).json()]
    assert names == ["Ravi Kumar"]
    # and the snapshot can bring the newer state back
    r = client.post("/api/backups/restore", json={"name": snap, "password": PASSWORD}, headers=h)
    h = login(client, "asha", PASSWORD)
    assert len(client.get("/api/patients", headers=h).json()) == 2


def test_restore_on_new_computer(client, admin, patient, state, tmp_path):
    from fastapi.testclient import TestClient

    from clinic.main import create_app

    name = client.post("/api/backups", headers=admin).json()["name"]
    data = (state.paths.backups / name).read_bytes()
    app2 = create_app(tmp_path / "new-pc", background=False)
    with TestClient(app2) as c2:
        r = c2.post("/api/system/restore-setup", files={"file": (name, io.BytesIO(data))}, data={"username": "asha", "password": "bad-password"})
        assert r.status_code == 400
        r = c2.post("/api/system/restore-setup", files={"file": (name, io.BytesIO(data))}, data={"username": "asha", "password": PASSWORD})
        assert r.status_code == 200, r.text
        h = {"Authorization": f"Bearer {r.json()['token']}"}
        assert c2.get("/api/patients/P000001", headers=h).json()["full_name"] == "Ravi Kumar"
