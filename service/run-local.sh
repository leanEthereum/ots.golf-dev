#!/usr/bin/env bash
# Start the site and the worker for local development.
set -euo pipefail
cd "$(dirname "$0")"

# The website re-seeds the invented demo board at every start when explicitly enabled with OTS_PHONY=1;
# OTS_PHONY=0 shows real submissions only. Nothing else needs to exist beforehand.
env -u GITHUB_TOKEN -u GITHUB_WEBHOOK_SECRET OTS_ROLE=worker .venv/bin/python -m app.worker &
worker=$!
trap 'kill "$worker" 2>/dev/null || true; wait "$worker" 2>/dev/null || true' EXIT
.venv/bin/uvicorn app.main:app --port "${PORT:-8000}" --reload
