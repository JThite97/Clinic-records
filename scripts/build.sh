#!/usr/bin/env bash
# Build the installer on macOS or Linux (see scripts/build-windows.ps1 for Windows).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root/backend"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt -e .
.venv/bin/python -m pytest
.venv/bin/pyinstaller --noconfirm clinic-server.spec
triple=$(rustc -vV | sed -n 's/host: //p')
mkdir -p "$root/desktop/src-tauri/binaries"
cp dist/clinic-server "$root/desktop/src-tauri/binaries/clinic-server-$triple"
cd "$root/desktop"
npm ci
npx tauri build "$@"
echo "Installers are in desktop/src-tauri/target/release/bundle/"
