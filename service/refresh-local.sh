#!/usr/bin/env bash
# Reconcile local demo fixtures without replacing rows, then reload the development server.
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${OTS_PHONY:-1}" == "1" && -x .venv/bin/python ]]; then
  .venv/bin/python -B seed_demo.py --refresh
fi

# Uvicorn --reload watches Python sources. A timestamp change reloads the app
# even when the commit only changed Lean, templates, metadata or documentation.
touch app/main.py
