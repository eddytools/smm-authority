#!/usr/bin/env bash
# One command to run the whole app locally: API on :8000, dashboard on :5173, with demo data.
#   ./scripts/dev.sh            start (installs dependencies on first run)
#   ./scripts/dev.sh --reset    rebuild the demo data first
# Requires Python 3.11+ and Node 20+. Sign in with demo@example.com / demo-password-1
# (or the admin from api/.env: admin@example.com / change-me-now).
set -euo pipefail
cd "$(dirname "$0")/.."

[ -d api/.venv ] || python3 -m venv api/.venv
api/.venv/bin/pip install -q -r api/requirements-dev.txt
[ -f api/.env ] || cp api/.env.example api/.env
[ -f dashboard/.env ] || cp dashboard/.env.example dashboard/.env
[ -d dashboard/node_modules ] || (cd dashboard && npm install --no-audit --no-fund)

# publishing stores OAuth tokens encrypted, so it needs a key: make one for local use if there isn't one yet
grep -q '^SMM_TOKEN_ENCRYPTION_KEY=.' api/.env || echo "SMM_TOKEN_ENCRYPTION_KEY=$(api/.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" >> api/.env

(cd api && .venv/bin/python -m app.demo "$@")

trap 'kill 0' EXIT
(cd api && .venv/bin/uvicorn --factory app.main:create_app --reload --port 8000) &
(cd api && .venv/bin/python -m app.jobs.publish_due --loop 30) &   # posts scheduled posts on connected accounts (a no-op until you connect one)
(cd api && .venv/bin/python -m app.jobs.pull_metrics --loop 3600) &   # reads results for posts published to X (a no-op until X is connected)
(cd dashboard && npm run dev -- --host localhost --port 5173) &
echo
echo "  Dashboard: http://localhost:5173    API docs: http://localhost:8000/docs"
echo "  Demo login: demo@example.com / demo-password-1"
wait
