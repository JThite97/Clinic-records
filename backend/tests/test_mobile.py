"""Sprint 8: read-only mobile access over the network."""
from fastapi.testclient import TestClient

from conftest import PASSWORD

PHONE = ("100.101.102.103", 50123)  # a Tailscale address


def test_mobile_page_served(client):
    r = client.get("/mobile")
    assert r.status_code == 200 and "Read-only" in r.text


def test_remote_client_is_read_only(app, client, admin, patient):
    v = client.post(f"/api/patients/{patient['id']}/visits", json={"diagnosis": "Fever", "prescription": {"items": [{"medicine_name": "A"}]}}, headers=admin).json()
    phone = TestClient(app, client=PHONE)  # no lifespan: shares the running app
    if True:
        assert phone.get("/mobile").status_code == 200
        # desktop API is not reachable from the network
        assert phone.get("/api/patients", headers=admin).status_code == 403
        assert phone.post("/api/patients", json={"full_name": "x"}, headers=admin).status_code == 403
        assert phone.post("/api/backups", headers=admin).status_code == 403
        # logging in from the network always gives a read-only session
        r = phone.post("/api/auth/login", json={"username": "asha", "password": PASSWORD, "scope": "desktop"})
        assert r.json()["scope"] == "mobile"
        h = {"Authorization": f"Bearer {r.json()['token']}"}
        rows = phone.get("/api/mobile/patients", params={"q": "ravi"}, headers=h).json()
        assert rows[0]["patient_number"] == "P000001"
        detail = phone.get(f"/api/mobile/patients/{patient['id']}", headers=h).json()
        assert detail["visits"][0]["diagnosis"] == "Fever"
        assert phone.get(f"/api/mobile/visits/{v['id']}/prescription.pdf?token={r.json()['token']}").status_code == 200
        assert phone.post(f"/api/mobile/patients/{patient['id']}", headers=h).status_code == 405
    # a mobile token cannot be used for desktop endpoints either
    assert client.get("/api/patients", headers=h).status_code == 403
