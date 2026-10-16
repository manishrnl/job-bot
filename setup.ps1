# One-time setup on Windows. Run from this folder:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv }
else { python -m venv .venv }

.\.venv\Scripts\python.exe -m pip install -q --upgrade pip
.\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
if (-not (Test-Path config.yaml)) { Copy-Item config.example.yaml config.yaml }
Write-Host "Done. Next: edit config.yaml, then run:  .\jb init C:\path\to\Profile.pdf"
