# Architecture decisions

Decisions carried over from the planning chat (Oct 2026) and the ones made while
building V1 (Nov 2026).

## Stack: Tauri + React desktop, FastAPI sidecar

Chosen in planning over the original PySide6 spec: a much smaller installer, a
modern UI stack shared with the future React Native phone app, and the FastAPI
server doubles as the phone sync hub. The server is Python (FastAPI,
SQLAlchemy, ReportLab) as in the original spec, frozen with PyInstaller and
started/stopped by the Tauri shell. The server also exits if the shell dies
(`--parent-pid` watchdog).

## The desktop is the hub; no always-on server

Planning chose "the phone records edits offline and syncs when the desktop is
on" over a separate server. So the database lives only on the clinic computer;
phones keep a full copy of every patient (attachments download on demand).

## Encryption and keys

- One random 256-bit data key encrypts the SQLCipher database and the backups.
- It is wrapped per user with scrypt(password) + AES-256-GCM in
  `data/keystore.json`; logging in unwraps it. No password is stored in the clear.
- Consequence: the server starts *locked* and sync works only while someone is
  logged in. If every administrator password is lost, the data is unrecoverable.
- Backups embed the keystore (already password-protected) in the zip comment, so
  a backup can be restored on a new computer with the usual login.

## Historical integrity

Visits, prescriptions and documents are append-only. An edit creates an
amendment (new row, same `root_id`, `amends_id` → previous, reason) and marks the
previous version superseded. There is no update or delete route for visits.
Creating a visit locks earlier visits; amending a locked visit requires a
reason. The audit log is hash-chained and verified on every view.

## Sync rules (Sprint 0)

- Every change, desktop or phone, is written to `sync_events` (server order =
  `seq`). Phones push their outbox and pull everything after their cursor.
- Push is idempotent by `event_id`; each event applies in its own savepoint, so
  one bad event does not block the rest.
- Patient demographics: per-field last-write-wins on (client timestamp, device
  id). The losing value goes to `sync_conflicts` and the *Phone sync* screen,
  where the doctor can keep it or switch. The doctor's choice always wins.
- Clinical records: concurrent amendments of the same visit are both kept; the
  newer becomes current and the pair is flagged for review.
- Phones are paired with a 6-digit code (10 minutes, single use) and get a
  device token (only its SHA-256 is stored); devices can be revoked.

## Network exposure

The server binds `127.0.0.1` unless an administrator enables phone access
(then `0.0.0.0`, intended for a Tailscale network). Non-loopback clients can
reach only `/mobile`, login, `/api/mobile/*` (GET only) and the sync endpoints;
a login from the network always gets a read-only session.

## Known limits / next steps

- **Phone app (Sprint 9+)**: the React Native app is not built yet. The server
  side (pairing, push/pull, files, conflicts) is done and tested with a
  simulated two-phone harness in `backend/tests/test_sync.py`.
- Phone clocks drive last-write-wins for demographics; a phone with a badly
  wrong clock can win or lose unexpectedly (the loser is always kept for review).
- PDFs use Helvetica, so names in Devanagari or other Indian scripts will not
  print correctly yet; embedding a Unicode font (e.g. Noto Sans) is the fix.
- Installers are unsigned; Windows SmartScreen will warn on first run until a
  code-signing certificate is added to the build.
- India's DPDP Act 2023 applies to health data. The design (encryption, audit
  trail, local storage) supports compliance, but have it reviewed before launch.
