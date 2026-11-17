# Clinic Records V1

A desktop app for a doctor's clinic: patient records, visits, prescriptions
with PDF printing, a document vault and encrypted backups. Everything stays
on the clinic's own computer; nothing goes to the cloud.

| Layer | Technology |
|---|---|
| Desktop window | Tauri 2 (Rust shell, system WebView) |
| User interface | React 19 + TypeScript (Vite) |
| Local server | FastAPI (Python), started by the app as a "sidecar" on `127.0.0.1:8000` |
| Database | SQLite encrypted with SQLCipher (AES-256), SQLAlchemy 2 |
| PDFs | ReportLab (A4 or Letter letterhead) |
| Backups | AES-256 encrypted zip (`.crbak`), automatic every 24 h, last 30 kept |
| Packaging | PyInstaller (server) + Tauri bundler (`.exe` / `.msi` installer) |

## What it does

- **Login and encryption.** First run creates the clinic and an administrator. The
  database is encrypted with a random 256-bit key that is itself locked with each
  user's password, so the records cannot be read without logging in. *Lock* closes
  the database instantly.
- **Patients.** Automatic IDs (P000001, P000002, …), typo-tolerant search by name,
  ID or phone (under 50 ms on 1,000 patients), allergies shown in red everywhere.
- **Visits.** Vitals, complaints, history, examination, diagnosis, advice and
  follow-up date, with the previous visit shown side by side.
  **Saved visits are never overwritten.** A correction is an *amendment*: a new
  version, with a reason, while the original stays in the version history. A new
  visit locks the earlier ones (amending a locked visit requires a reason).
- **Prescriptions.** 500-medicine library with typeahead, default dose/frequency/
  duration, automatic quantity, custom medicines, and *Copy from previous visit*
  in one click.
- **Printing.** One-page letterhead prescription (logo, doctor, registration
  number, signature image) and a full patient-record PDF. In the desktop app they
  open in the system PDF viewer for printing.
- **Document vault.** Lab reports and images are copied into the clinic folder
  with a SHA-256 checksum (deleting the original does not matter; *Verify*
  detects any change).
- **Backups.** Back up now, automatic daily backup, verify, download, restore (with
  an automatic safety snapshot first), and restore onto a new computer from the
  setup screen.
- **Audit log.** Every change, login and backup, hash-chained so tampering is
  detectable.
- **Users and roles.** Administrator, doctor (clinical records) and staff
  (registration and documents only).
- **Phones.** A read-only mobile web view (`http://<computer>:8000/mobile`) over a
  private network such as Tailscale, plus the **sync server** for the future phone
  app: pairing codes, push/pull of changes, per-field last-write-wins for
  demographics, append-only clinical records, and a *Changes to review* screen
  for conflicts. Network access is off until an administrator turns it on.

## Install (for the clinic)

Download the installer for your system from the GitHub Actions run
(**Actions → Test and build installers → Artifacts → ClinicRecords-Windows**) and
run `Clinic Records_1.0.0_x64-setup.exe`. Data is stored in
`%APPDATA%\ClinicRecords` (`data`, `documents`, `backups`, `logs`).

Copy the files in `backups` to a USB drive or second disk regularly. To move to a
new computer, install the app, choose **Restore a backup** on the first screen,
and log in with the same username and password.

> Keep the administrator password safe. If every administrator password is lost
> the encrypted records cannot be recovered; there is no back door.

## Build it yourself

Prerequisites: Python 3.11+, Node.js 22, Rust (`rustup`), and on Linux the
WebKitGTK dev packages (`libwebkit2gtk-4.1-dev librsvg2-dev`).

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1

# macOS / Linux
./scripts/build.sh
```

The scripts run the tests, build the server with PyInstaller, place it in
`desktop/src-tauri/binaries/clinic-server-<target-triple>`, and run
`tauri build`. Installers land in `desktop/src-tauri/target/release/bundle/`.
Pushing to GitHub runs the same steps for Windows, macOS and Linux in
`.github/workflows/build.yml`.

## Develop

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt -e .
cd ../desktop && npm install
cd .. && ./scripts/dev.sh          # server on :8000, UI on http://localhost:1420
# or inside the desktop window (needs a built sidecar in src-tauri/binaries):
cd desktop && npx tauri dev
```

The server can also serve the built UI itself, so the app runs in any browser:

```bash
cd desktop && npm run build
cd ../backend && CLINIC_UI_DIR=../desktop/dist .venv/bin/python -m clinic --home ./demo-data
# open http://127.0.0.1:8000
```

API documentation: `http://127.0.0.1:8000/api/docs`.

## Tests

```bash
cd backend && .venv/bin/python -m pytest       # 58 tests, sprint by sprint
cd desktop && npm test                         # UI helpers
cd desktop && npm run build && npm run e2e     # browser test of the whole workflow
```

| Sprint | Acceptance check | Test |
|---|---|---|
| 0 Sync | two offline phones, idempotent push, LWW + conflicts, concurrent amendments | `tests/test_sync.py` |
| 1 Core | all tables, cascades, foreign keys, encrypted file, wrong key rejected | `test_database.py`, `test_security.py`, `test_auth.py` |
| 2 Patients | P000001 → P000002, search < 50 ms on 1,000 records | `test_patients.py` |
| 3 Visits | new visit locks earlier ones; no overwrite, amendments audited | `test_visits.py` |
| 4 Prescriptions | 500 medicines, autocomplete, copy previous in one click | `test_medicines.py`, `test_visits.py`, e2e |
| 5 Documents | stored copy survives deleting the original; checksum verify | `test_documents.py` |
| 6 PDFs | single visit always one page on A4 and Letter | `test_pdf.py` |
| 7 Backups | create → decrypt + integrity check; retention; restore with snapshot | `test_backup.py` |
| 8 Mobile | read-only over the network; desktop API blocked remotely | `test_mobile.py`, e2e |

## Layout

```
backend/clinic/        FastAPI server
  config.py            paths (data, documents, backups, logs, exports) and settings
  database.py          SQLCipher engine, PRAGMA foreign_keys = ON
  models.py            User, Patient, Visit, Medicine, Prescription, Document, AuditLog, sync tables
  security.py          Argon2 password hashes, key wrapping (scrypt + AES-GCM)
  services/            patient, visit, medicine, document, pdf, backup, sync, admin
  api/                 HTTP routes (system, clinical, sync + mobile)
  mobile/index.html    read-only phone page
backend/tests/         pytest suite
desktop/src/           React UI (pages/, components/)
desktop/src-tauri/     Tauri shell that starts and stops the server
docs/DECISIONS.md      architecture decisions and known limits
```

See [docs/DECISIONS.md](docs/DECISIONS.md) for why things are built this way and
what is left for later (the React Native phone app).
