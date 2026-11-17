#!/usr/bin/env bash
# Run the server and the UI in development (browser at http://localhost:1420).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
export CLINIC_HOME="${CLINIC_HOME:-$root/.dev-data}"
(cd "$root/backend" && .venv/bin/python -m clinic --port 8000) &
trap 'kill %1' EXIT
cd "$root/desktop" && npm run dev
