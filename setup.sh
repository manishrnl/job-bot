#!/usr/bin/env bash
# One-time setup: virtualenv + dependencies + headless Chromium (used for PDF rendering)
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt
./.venv/bin/python -m playwright install chromium
[ -f config.yaml ] || cp config.example.yaml config.yaml
chmod +x jb
echo "Done. Next: edit config.yaml, then run ./jb init /path/to/linkedin_profile.pdf"
