"""Sprint 4: medicine library."""


def test_library_seeded_with_500(client, admin, state):
    from sqlalchemy import func, select

    from clinic.models import Medicine

    with state.db.session() as s:
        assert s.scalar(select(func.count()).select_from(Medicine)) == 500


def test_autocomplete(client, admin):
    rows = client.get("/api/medicines", params={"q": "amox"}, headers=admin).json()
    assert rows and all("amox" in r["name"].lower() or "amox" in r["generic_name"].lower() for r in rows)
    assert rows[0]["name"].lower().startswith("amox")
    rows = client.get("/api/medicines", params={"q": "metformin 500"}, headers=admin).json()
    assert any(r["name"] == "Metformin 500 mg" for r in rows)


def test_custom_medicine_and_usage_ranking(client, admin, patient):
    r = client.post("/api/medicines", json={"name": "Zyx Special Syrup", "form": "Syrup", "default_dose": "5 ml"}, headers=admin)
    assert r.status_code == 201 and r.json()["is_custom"]
    mid = r.json()["id"]
    client.post(f"/api/patients/{patient['id']}/visits", json={"prescription": {"items": [{"medicine_id": mid, "medicine_name": "Zyx Special Syrup"}]}}, headers=admin)
    rows = client.get("/api/medicines", params={"q": "zyx"}, headers=admin).json()
    assert rows[0]["usage_count"] == 1
    client.put(f"/api/medicines/{mid}", json={"active": False}, headers=admin)
    assert client.get("/api/medicines", params={"q": "zyx"}, headers=admin).json() == []
