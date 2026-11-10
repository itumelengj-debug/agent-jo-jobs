#!/bin/bash
# Agent Jo Jobs — install on macOS or Linux.
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -z "$PY" ] && { echo "  Needs Python 3.10+. macOS: brew install python@3.12, or python.org."; exit 1; }
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet || { echo "  pip failed — check your connection or proxy."; exit 1; }
.venv/bin/python -c "import jobs.server" || { echo "  Installed, but the app won't load."; exit 1; }

# the browser for portal applications — the download is the slow part
if .venv/bin/python -c "
from playwright.sync_api import sync_playwright as s
import pathlib, sys
p = s().start(); e = p.chromium.executable_path; p.stop()
sys.exit(0 if pathlib.Path(e).exists() else 1)" 2>/dev/null; then
  echo "  Browser for portal applications: ready"
else
  echo "  Downloading the browser for portal applications (about 150 MB)..."
  if .venv/bin/python -m playwright install chromium; then
    echo "  Browser: ready"
  else
    echo "  The browser didn't download — often a proxy or a blocked network."
    echo "  Portal applications will not work until you run:"
    echo "    .venv/bin/python -m playwright install chromium"
  fi
fi
echo
echo "  Ready. Start it with ./start.sh (macOS: double-click start.command)"
echo "  It opens at http://127.0.0.1:8766"
