"""Sprint 0: the two-offline-phones harness.

``Phone`` is a minimal stand-in for the future React Native client: a local
copy of the records, an outbox of unsent events, and a pull cursor.
"""
import time
import uuid

import pytest

from conftest import rx


class Phone:
    def __init__(self, client, name):
        self.c = client
        self.name = name
        self.token = None
        self.cursor = 0
        self.outbox: list[dict] = []
        self.patients: dict[str, dict] = {}
        self.visits: dict[str, dict] = {}
        self.seen: set[str] = set()
        self.clock = 0

    def pair(self, code):
        r = self.c.post("/api/sync/pair", json={"code": code, "device_name": self.name})
        assert r.status_code == 200, r.text
        self.token = r.json()["device_token"]

    @property
    def h(self):
        return {"X-Device-Token": self.token}

    def _ev(self, entity, entity_id, op, payload, ts):
        ev = {"event_id": str(uuid.uuid4()), "entity": entity, "entity_id": entity_id, "op": op, "payload": payload, "client_ts": ts}
        self.outbox.append(ev)
        return ev

    # offline edits
    def create_patient(self, name, ts, **fields):
        pid = str(uuid.uuid4())
        self.patients[pid] = {"full_name": name, **fields}
        self._ev("patient", pid, "create", {"fields": {"full_name": name, **fields}}, ts)
        return pid

    def edit_patient(self, pid, ts, **fields):
        base = {k: self.patients[pid].get(k) for k in fields}
        self.patients[pid].update(fields)
        self._ev("patient", pid, "update", {"fields": fields, "base": base}, ts)

    def add_visit(self, pid, ts, **fields):
        vid = str(uuid.uuid4())
        self._ev("visit", vid, "create", {"patient_id": pid, "fields": fields, "prescription": rx("Paracetamol 650 mg")}, ts)
        return vid

    def amend_visit(self, vid, ts, reason, **fields):
        nid = str(uuid.uuid4())
        self._ev("visit", nid, "amend", {"amends_id": vid, "reason": reason, "fields": fields}, ts)
        return nid

    # online
    def push(self):
        r = self.c.post("/api/sync/push", json={"events": self.outbox}, headers=self.h)
        assert r.status_code == 200, r.text
        res = r.json()["results"]
        assert all(x["status"] in ("applied", "duplicate") for x in res), res
        self.outbox = []
        return res

    def pull(self):
        while True:
            r = self.c.get("/api/sync/pull", params={"since": self.cursor, "limit": 50}, headers=self.h).json()
            for ev in r["events"]:
                self.seen.add(ev["event_id"])
                p = ev["payload"]
                if ev["entity"] == "patient":
                    cur = self.patients.setdefault(ev["entity_id"], {})
                    cur.update(p.get("fields") or {})
                    if p.get("patient_number"):
                        cur["patient_number"] = p["patient_number"]
                elif ev["entity"] == "visit":
                    self.visits[ev["entity_id"]] = {**p.get("fields", {}), "amends_id": p.get("amends_id")}
            self.cursor = r["cursor"]
            if not r["more"]:
                break


@pytest.fixture
def phones(client, admin):
    a, b = Phone(client, "Doctor's phone"), Phone(client, "Clinic tablet")
    for ph in (a, b):
        code = client.post("/api/sync/pairing-code", headers=admin).json()["code"]
        ph.pair(code)
    return a, b


def test_pairing_code_single_use(client, admin):
    code = client.post("/api/sync/pairing-code", headers=admin).json()["code"]
    assert client.post("/api/sync/pair", json={"code": code}).status_code == 200
    assert client.post("/api/sync/pair", json={"code": code}).status_code == 422
    assert client.get("/api/sync/pull", headers={"X-Device-Token": "nope"}).status_code == 401


def test_phone_creates_patient_offline_and_gets_number(client, admin, phones):
    a, b = phones
    pid = a.create_patient("Offline Patient", ts=1000, phone="9999911111")
    vid = a.add_visit(pid, ts=1001, diagnosis="Seen at home visit")
    res = a.push()
    assert res[0]["patient_number"] == "P000001"
    p = client.get(f"/api/patients/{pid}", headers=admin).json()
    assert p["full_name"] == "Offline Patient"
    assert client.get(f"/api/visits/{vid}", headers=admin).json()["diagnosis"] == "Seen at home visit"
    b.pull()
    assert b.patients[pid]["patient_number"] == "P000001"
    assert vid in b.visits


def test_push_is_idempotent(client, admin, phones):
    a, _ = phones
    a.create_patient("Once", ts=1)
    events = list(a.outbox)
    a.push()
    r = client.post("/api/sync/push", json={"events": events}, headers=a.h).json()
    assert r["results"][0]["status"] == "duplicate"
    assert len(client.get("/api/patients", headers=admin).json()) == 1


def test_desktop_changes_reach_phone(client, admin, phones, patient):
    a, _ = phones
    client.put(f"/api/patients/{patient['id']}", json={"phone": "8888800000"}, headers=admin)
    a.pull()
    assert a.patients[patient["id"]]["phone"] == "8888800000"
    assert a.patients[patient["id"]]["patient_number"] == "P000001"


def test_lww_per_field_and_conflict_flagged(client, admin, phones, patient):
    a, b = phones
    pid = patient["id"]
    a.pull(), b.pull()
    # both offline: A edits phone+address, B edits phone later and blood group
    now = int(time.time() * 1000)
    a.edit_patient(pid, ts=now + 1_000, phone="1111111111", address="New address A")
    b.edit_patient(pid, ts=now + 2_000, phone="2222222222", blood_group="O+")
    b.push()  # B syncs first
    a.push()  # A syncs later but its phone edit is older -> loses
    p = client.get(f"/api/patients/{pid}", headers=admin).json()
    assert p["phone"] == "2222222222"  # newest write wins
    assert p["address"] == "New address A"  # different fields merge
    assert p["blood_group"] == "O+"
    conflicts = client.get("/api/sync/conflicts", headers=admin).json()
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["field"] == "phone" and c["kept_value"] == "2222222222" and c["other_value"] == "1111111111"
    # doctor reviews and chooses the other value
    client.post(f"/api/sync/conflicts/{c['id']}/resolve", json={"use_other": True}, headers=admin)
    assert client.get(f"/api/patients/{pid}", headers=admin).json()["phone"] == "1111111111"
    assert client.get("/api/sync/conflicts", headers=admin).json() == []
    # both phones converge
    a.pull(), b.pull()
    assert a.patients[pid]["phone"] == b.patients[pid]["phone"] == "1111111111"


def test_concurrent_amendments_both_kept(client, admin, phones, patient):
    a, b = phones
    v = client.post(f"/api/patients/{patient['id']}/visits", json={"diagnosis": "Original"}, headers=admin).json()
    a.amend_visit(v["id"], ts=5, reason="phone A fix", diagnosis="Amended by A")
    b.amend_visit(v["id"], ts=6, reason="phone B fix", diagnosis="Amended by B")
    a.push()
    b.push()
    hist = client.get(f"/api/visits/{v['id']}/history", headers=admin).json()
    assert [h["diagnosis"] for h in hist] == ["Original", "Amended by A", "Amended by B"]
    current = [x for x in hist if not x["superseded"]]
    assert len(current) == 1 and current[0]["diagnosis"] == "Amended by B"
    conflicts = client.get("/api/sync/conflicts", headers=admin).json()
    assert len(conflicts) == 1 and conflicts[0]["kind"] == "amendment"


def test_bad_event_rejected_others_applied(client, admin, phones):
    a, _ = phones
    a.outbox.append({"event_id": str(uuid.uuid4()), "entity": "visit", "entity_id": str(uuid.uuid4()), "op": "create",
                     "payload": {"patient_id": "missing", "fields": {}}, "client_ts": 1})
    a.create_patient("Good one", ts=2)
    r = client.post("/api/sync/push", json={"events": a.outbox}, headers=a.h).json()["results"]
    assert [x["status"] for x in r] == ["rejected", "applied"]


def test_revoked_device_blocked(client, admin, phones):
    a, _ = phones
    devs = client.get("/api/sync/devices", headers=admin).json()
    dev = next(d for d in devs if d["name"] == a.name)
    client.post(f"/api/sync/devices/{dev['id']}/revoke", headers=admin)
    assert client.get("/api/sync/pull", headers=a.h).status_code == 401


def test_phone_document_upload_and_download(client, admin, phones, patient):
    a, _ = phones
    did = str(uuid.uuid4())
    r = client.post("/api/sync/files", data={"patient_id": patient["id"], "doc_id": did, "title": "Photo"},
                    files={"file": ("rash.jpg", b"\xff\xd8\xff jpeg", "image/jpeg")}, headers=a.h)
    assert r.status_code == 201, r.text
    again = client.post("/api/sync/files", data={"patient_id": patient["id"], "doc_id": did},
                        files={"file": ("rash.jpg", b"\xff\xd8\xff jpeg", "image/jpeg")}, headers=a.h)
    assert again.json()["id"] == did
    assert client.get(f"/api/sync/files/{did}", headers=a.h).content == b"\xff\xd8\xff jpeg"
