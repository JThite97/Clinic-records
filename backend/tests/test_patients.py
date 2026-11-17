"""Sprint 2: patient numbering and search."""
import time

from clinic.services import patient_service
from clinic.services.common import Origin


def test_numbers_increment_deterministically(client, admin):
    nums = [client.post("/api/patients", json={"full_name": f"P {i}"}, headers=admin).json()["patient_number"] for i in range(3)]
    assert nums == ["P000001", "P000002", "P000003"]


def test_name_required(client, admin):
    assert client.post("/api/patients", json={"full_name": "  "}, headers=admin).status_code == 422


def test_get_by_number_and_update(client, admin, patient):
    r = client.get("/api/patients/P000001", headers=admin)
    assert r.json()["id"] == patient["id"]
    r = client.put(f"/api/patients/{patient['id']}", json={"phone": "9000000001", "blood_group": "B+"}, headers=admin)
    assert r.json()["phone"] == "9000000001" and r.json()["blood_group"] == "B+"
    audit = client.get("/api/audit", headers=admin).json()
    assert any(e["action"] == "patient.update" for e in audit["entries"])
    assert audit["chain_ok"]


def _seed(state, n):
    first = ["Ravi", "Asha", "Sunil", "Priya", "Anil", "Meena", "Rahul", "Kavita", "Vijay", "Neha", "Suresh", "Pooja"]
    last = ["Kumar", "Sharma", "Patil", "Deshmukh", "Iyer", "Reddy", "Joshi", "Thite", "Kulkarni", "Nair"]
    with state.db.session() as s:
        for i in range(n):
            patient_service.create_patient(s, {"full_name": f"{first[i % 12]} {last[(i // 12) % 10]} {i}", "phone": f"98{i:08d}"}, Origin("seed"))


def test_search_fuzzy_number_phone(client, admin, state):
    _seed(state, 50)
    rows = client.get("/api/patients", params={"q": "kavta"}, headers=admin).json()  # typo
    assert rows and rows[0]["full_name"].startswith("Kavita")
    rows = client.get("/api/patients", params={"q": "P000007"}, headers=admin).json()
    assert rows[0]["patient_number"] == "P000007"
    rows = client.get("/api/patients", params={"q": "7"}, headers=admin).json()
    assert rows[0]["patient_number"] == "P000007"
    rows = client.get("/api/patients", params={"q": "9800000012"}, headers=admin).json()
    assert rows[0]["phone"] == "9800000012"


def test_search_under_50ms_on_1000(state, admin):
    _seed(state, 1000)
    with state.db.session() as s:
        patient_service.search_patients(s, "warmup")
        worst = 0.0
        for q in ("ravi", "deshmuk", "P000500", "9800000999", "priya patil", "xyz"):
            t = time.perf_counter()
            patient_service.search_patients(s, q)
            worst = max(worst, time.perf_counter() - t)
    assert worst < 0.050, f"slowest search took {worst * 1000:.1f} ms"
