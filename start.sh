#!/bin/bash
# Agent Jo Jobs. On macOS, double-click start.command instead.
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || { echo "  Run ./install.sh first."; exit 1; }
exec .venv/bin/python run_jobs.py "$@"
