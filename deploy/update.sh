#!/usr/bin/env bash
# Deploy the latest code: back up the database, pull, update dependencies, migrate, rebuild the dashboard, restart.
#   sudo /opt/smm/deploy/update.sh
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)."; exit 1; }
as_smm() { runuser -u smm -- env HOME=/var/lib/smm "$@"; }
cd /opt/smm
DOMAIN=$(grep -oP '^SMM_DASHBOARD_URL=https?://\K[^/]+' /etc/smm/smm.env)

echo "==> Backing up the database"
as_smm /opt/smm/deploy/backup.sh
echo "==> Pulling the latest code"
as_smm git pull --ff-only
echo "==> Updating the API"
as_smm /opt/smm/api/.venv/bin/pip install -q -r api/requirements.txt
echo "==> Rebuilding the dashboard"
(cd dashboard && as_smm npm ci --no-audit --no-fund --silent && as_smm env VITE_API_URL=/api npm run build --silent)
chmod -R a+rX dashboard/dist
echo "==> Restarting (the API applies database migrations on start)"
systemctl restart smm-api smm-publish
for i in $(seq 1 30); do
  curl -fsS -H "Host: $DOMAIN" http://127.0.0.1/api/health >/dev/null 2>&1 && { echo "Healthy. Deployed $(git rev-parse --short HEAD)."; exit 0; }
  sleep 1
done
journalctl -u smm-api -n 40 --no-pager
echo "The API did not come back. The pre-update backup is in /var/backups/smm." >&2
exit 1
