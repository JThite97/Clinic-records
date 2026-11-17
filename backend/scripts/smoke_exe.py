"""Smoke-test the frozen server binary the way the desktop shell runs it.

    python scripts/smoke_exe.py dist/clinic-server[.exe]

Starts the binary with --parent-pid (this process), waits for it, runs
setup -> patient -> visit -> PDF -> backup over HTTP, then checks the server
is still alive after the parent-watchdog interval. Prints the server output
and exits non-zero on any failure.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

exe = os.path.abspath(sys.argv[1])
port = 8799
home = tempfile.mkdtemp(prefix="clinic-smoke-")
base = f"http://127.0.0.1:{port}"
proc = subprocess.Popen([exe, "--home", home, "--port", str(port), "--parent-pid", str(os.getpid())],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def call(method, path, body=None, token=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Origin", "http://tauri.localhost")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = r.read()
        return payload if raw else json.loads(payload)


def fail(msg):
    print("SMOKE FAILED:", msg)
    alive = proc.poll() is None
    print("server alive:", alive, "exit code:", proc.returncode)
    if alive:
        proc.kill()
    out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
    print("---- server output ----\n" + out[-6000:])
    log = os.path.join(home, "logs", "clinic.log")
    if os.path.exists(log):
        print("---- clinic.log ----\n" + open(log, encoding="utf-8").read()[-6000:])
    sys.exit(1)


try:
    for _ in range(120):
        try:
            call("GET", "/api/health")
            break
        except Exception:
            if proc.poll() is not None:
                fail("server exited during start-up")
            time.sleep(0.5)
    else:
        fail("server did not start in 60 s")
    time.sleep(5)  # past the first parent-watchdog checks, like a user typing
    if proc.poll() is not None:
        fail("server exited after start-up (watchdog?)")
    # CORS preflight exactly as the desktop WebView sends it.
    pre = urllib.request.Request(base + "/api/system/setup", method="OPTIONS")
    for k, v in {"Origin": "http://tauri.localhost", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type,authorization",
                 "Access-Control-Request-Private-Network": "true"}.items():
        pre.add_header(k, v)
    with urllib.request.urlopen(pre, timeout=30) as r:
        assert r.headers.get("access-control-allow-origin") == "http://tauri.localhost", dict(r.headers)
    s = call("POST", "/api/system/setup", {"clinic_name": "Smoke", "doctor_name": "Dr S", "username": "doc", "password": "password-123"})
    t = s["token"]
    p = call("POST", "/api/patients", {"full_name": "Smoke Patient", "allergies": "None"}, t)
    v = call("POST", f"/api/patients/{p['id']}/visits", {"diagnosis": "x", "prescription": {"items": [{"medicine_name": "Paracetamol 650 mg"}]}}, t)
    pdf = call("GET", f"/api/visits/{v['id']}/prescription.pdf", token=t, raw=True)
    assert pdf.startswith(b"%PDF"), "not a PDF"
    b = call("POST", "/api/backups", {}, t)
    assert b["verify"]["ok"], b
    call("POST", "/api/auth/lock", {}, t)
    t = call("POST", "/api/auth/login", {"username": "doc", "password": "password-123"})["token"]
    assert call("GET", "/api/patients?q=smoke", token=t)[0]["patient_number"] == "P000001"
    time.sleep(5)
    if proc.poll() is not None:
        fail("server exited during the run")
    print("SMOKE OK:", p["patient_number"], b["name"])
except SystemExit:
    raise
except Exception as e:  # noqa: BLE001
    fail(repr(e))
finally:
    if proc.poll() is None:
        proc.kill()
