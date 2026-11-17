from conftest import PASSWORD, login


def test_status_before_and_after_setup(client):
    s = client.get("/api/system/status").json()
    assert s == {**s, "initialized": False, "unlocked": False}
    client.post("/api/system/setup", json={"clinic_name": "C", "username": "doc", "password": PASSWORD})
    s = client.get("/api/system/status").json()
    assert s["initialized"] and s["unlocked"] and s["clinic_name"] == "C"


def test_setup_only_once(client, admin):
    r = client.post("/api/system/setup", json={"clinic_name": "C", "username": "other", "password": PASSWORD})
    assert r.status_code == 409


def test_requires_login(client, admin):
    assert client.get("/api/patients").status_code == 401


def test_lock_then_unlock_with_password(client, admin, state):
    assert client.post("/api/auth/lock", headers=admin).status_code == 200
    assert not state.unlocked
    assert client.get("/api/patients", headers=admin).status_code in (401, 423)
    assert client.post("/api/auth/login", json={"username": "asha", "password": "nope-nope"}).status_code == 401
    assert not state.unlocked
    h = login(client, "asha", PASSWORD)
    assert state.unlocked
    assert client.get("/api/patients", headers=h).status_code == 200


def test_restart_requires_login(home, admin, client):
    from fastapi.testclient import TestClient

    from clinic.main import create_app

    app2 = create_app(home, background=False)
    with TestClient(app2) as c2:
        assert c2.get("/api/system/status").json()["unlocked"] is False
        h = login(c2, "asha", PASSWORD)
        assert c2.get("/api/auth/me", headers=h).json()["username"] == "asha"


def test_throttle_after_failures(client, admin):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "asha", "password": "bad-password"})
    r = client.post("/api/auth/login", json={"username": "asha", "password": PASSWORD})
    assert r.status_code == 429


def test_roles(client, admin, patient):
    r = client.post("/api/users", json={"username": "reception", "password": "front-desk-1", "role": "staff"}, headers=admin)
    assert r.status_code == 200, r.text
    staff = login(client, "reception", "front-desk-1")
    # staff can register patients but not write clinical notes or manage users
    assert client.post("/api/patients", json={"full_name": "Walk In"}, headers=staff).status_code == 201
    assert client.post(f"/api/patients/{patient['id']}/visits", json={"diagnosis": "x"}, headers=staff).status_code == 403
    assert client.get("/api/users", headers=staff).status_code == 403
    # a new user can unlock the database after a lock too
    client.post("/api/auth/lock", headers=admin)
    login(client, "reception", "front-desk-1")


def test_password_change_rewraps_key(client, admin):
    r = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "new-password-2"}, headers=admin)
    assert r.status_code == 200
    client.post("/api/auth/lock", headers=admin)
    assert client.post("/api/auth/login", json={"username": "asha", "password": PASSWORD}).status_code == 401
    login(client, "asha", "new-password-2")


def test_last_admin_cannot_be_deactivated(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.post(f"/api/users/{me['id']}/active/false", headers=admin).status_code == 400


def test_cors_preflight_from_desktop_webview(client):
    """Regression: the Windows WebView2 preflight (incl. private-network) must succeed."""
    h = {"Origin": "http://tauri.localhost", "Access-Control-Request-Method": "POST",
         "Access-Control-Request-Headers": "content-type,authorization",
         "Access-Control-Request-Private-Network": "true"}
    r = client.options("/api/system/setup", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == "http://tauri.localhost"
    assert r.headers["access-control-allow-private-network"] == "true"
    h["Origin"] = "tauri://localhost"
    assert client.options("/api/system/setup", headers=h).status_code == 200
    h["Origin"] = "https://evil.example"
    assert client.options("/api/system/setup", headers=h).status_code == 400
