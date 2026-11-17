# Build ClinicRecords installer on Windows.
# Prerequisites: Python 3.12, Node.js 22, Rust (rustup), and the
# "Desktop development with C++" workload / WebView2 (preinstalled on Windows 10/11).
#   powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\pip install -r requirements-dev.txt -e .
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\pyinstaller --noconfirm clinic-server.spec
$triple = (rustc -vV | Select-String "host:").ToString().Split(" ")[1]
New-Item -ItemType Directory -Force "$root\desktop\src-tauri\binaries" | Out-Null
Copy-Item dist\clinic-server.exe "$root\desktop\src-tauri\binaries\clinic-server-$triple.exe" -Force
Pop-Location

Push-Location "$root\desktop"
npm ci
npx tauri build
Pop-Location

Write-Host "`nInstallers:" -ForegroundColor Green
Get-ChildItem "$root\desktop\src-tauri\target\release\bundle" -Recurse -Include *.exe, *.msi | ForEach-Object { $_.FullName }
