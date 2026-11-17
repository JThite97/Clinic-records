import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from clinic.main import create_app  # noqa: E402

PASSWORD = "correct-horse-1"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "clinic"


@pytest.fixture
def app(home):
    return create_app(home, background=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def state(app):
    return app.state.clinic


@pytest.fixture
def admin(client):
    r = client.post("/api/system/setup", json={"clinic_name": "Sunrise Clinic", "doctor_name": "Dr. Asha Rao",
                                                "username": "asha", "full_name": "Dr. Asha Rao", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def login(client, username, password, scope="desktop"):
    r = client.post("/api/auth/login", json={"username": username, "password": password, "scope": scope})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def patient(client, admin):
    r = client.post("/api/patients", json={"full_name": "Ravi Kumar", "sex": "M", "age_years": 42, "phone": "98765 43210",
                                           "allergies": "Penicillin"}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def rx(*names):
    return {"items": [{"medicine_name": n, "dose": "1 tab", "frequency": "1-0-1", "duration": "5 days"} for n in names], "notes": ""}
