"""Sprints 3-4: visits are append-only; prescriptions and copy-previous."""
from conftest import rx


def _visit(client, h, pid, **kw):
    r = client.post(f"/api/patients/{pid}/visits", json=kw, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_new_visit_locks_previous(client, admin, patient):
    v1 = _visit(client, admin, patient["id"], diagnosis="Fever", prescription=rx("Paracetamol 650 mg"))
    assert v1["locked"] is False
    v2 = _visit(client, admin, patient["id"], diagnosis="Follow-up")
    assert client.get(f"/api/visits/{v1['id']}", headers=admin).json()["locked"] is True
    assert v2["locked"] is False


def test_no_way_to_overwrite_a_visit(client, admin, patient):
    v = _visit(client, admin, patient["id"], diagnosis="Fever")
    assert client.put(f"/api/visits/{v['id']}", json={"diagnosis": "x"}, headers=admin).status_code == 405
    assert client.delete(f"/api/visits/{v['id']}", headers=admin).status_code == 405


def test_amendment_keeps_original(client, admin, patient):
    v1 = _visit(client, admin, patient["id"], diagnosis="Fever", chief_complaint="Fever 2 days", prescription=rx("Paracetamol 650 mg"))
    _visit(client, admin, patient["id"], diagnosis="Later")
    # v1 is locked now: reason required
    r = client.post(f"/api/visits/{v1['id']}/amend", json={"diagnosis": "Dengue (NS1 +ve)"}, headers=admin)
    assert r.status_code == 422
    r = client.post(f"/api/visits/{v1['id']}/amend", json={"diagnosis": "Dengue (NS1 +ve)", "reason": "Lab report received"}, headers=admin)
    assert r.status_code == 201
    a = r.json()
    assert a["amends_id"] == v1["id"] and a["root_id"] == v1["id"]
    assert a["chief_complaint"] == "Fever 2 days"  # unchanged fields carried over
    assert a["prescription"]["items"][0]["medicine_name"] == "Paracetamol 650 mg"
    hist = client.get(f"/api/visits/{v1['id']}/history", headers=admin).json()
    assert [h["diagnosis"] for h in hist] == ["Fever", "Dengue (NS1 +ve)"]
    assert hist[0]["superseded"] is True
    current = client.get(f"/api/patients/{patient['id']}/visits", headers=admin).json()
    assert {v["diagnosis"] for v in current} == {"Dengue (NS1 +ve)", "Later"}
    allv = client.get(f"/api/patients/{patient['id']}/visits?all_versions=true", headers=admin).json()
    assert len(allv) == 3
    audit = client.get("/api/audit", headers=admin).json()["entries"]
    assert any(e["action"] == "visit.amend" and e["details"]["reason"] == "Lab report received" for e in audit)


def test_copy_previous_prescription(client, admin, patient):
    v1 = _visit(client, admin, patient["id"], prescription=rx("Amlodipine 5 mg", "Atorvastatin 10 mg"))
    items = client.get(f"/api/visits/{v1['id']}/copy-prescription", headers=admin).json()["items"]
    assert [i["medicine_name"] for i in items] == ["Amlodipine 5 mg", "Atorvastatin 10 mg"]
    v2 = _visit(client, admin, patient["id"], prescription={"items": items})
    assert [i["medicine_name"] for i in v2["prescription"]["items"]] == ["Amlodipine 5 mg", "Atorvastatin 10 mg"]
    last = client.get(f"/api/patients/{patient['id']}/last-prescription", headers=admin).json()
    assert last["visit_id"] == v2["id"]


def test_vitals_and_dashboard(client, admin, patient):
    _visit(client, admin, patient["id"], bp_systolic="130", bp_diastolic=85, temperature="37.8", follow_up_date="2099-01-01")
    d = client.get("/api/dashboard", headers=admin).json()
    assert d["patients"] == 1 and d["visits"] == 1 and len(d["today"]) == 1
