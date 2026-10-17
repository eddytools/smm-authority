#!/usr/bin/env bash
# One-time install of SMM Authority on a Debian/Ubuntu VPS: API + scheduled jobs + dashboard behind nginx, with HTTPS.
#
#   git clone -b claude/gifted-bell-e2oh51 https://github.com/eddytools/smm-authority.git /opt/smm
#   sudo /opt/smm/deploy/install.sh --admin-email you@example.com --certbot-email you@example.com
#
# Safe to re-run: it never overwrites /etc/smm/smm.env, never touches other nginx sites, and keeps the database.
# Needs: root, Ubuntu 24.04 / Debian 12 or newer (Python 3.11+), DNS for the domain already pointing at this server.
set -euo pipefail

DOMAIN="${DOMAIN:-authority.thegrowthstacker.in}"
ADMIN_EMAIL="" CERTBOT_EMAIL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --admin-email) ADMIN_EMAIL="$2"; shift 2 ;;
    --certbot-email) CERTBOT_EMAIL="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 2 ;;
  esac
done

# Run a command as the service user with a usable HOME (npm and pip write caches there)
as_smm() { runuser -u smm -- env HOME=/var/lib/smm "$@"; }
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root (sudo)."
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$ROOT" = "/opt/smm" ] || die "The repository must be at /opt/smm (it is at $ROOT). Clone it there: git clone <repo> /opt/smm"
command -v apt-get >/dev/null || die "This installer supports Debian/Ubuntu (apt)."
[ -n "$ADMIN_EMAIL" ] || die "Pass --admin-email you@example.com (the first admin's sign-in)."

say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx certbot python3-certbot-nginx sqlite3 curl git ca-certificates dnsutils >/dev/null

PYV=$(python3 -c 'import sys; print("%d%02d" % sys.version_info[:2])')
[ "$PYV" -ge 311 ] || die "Python 3.11+ is required (found $(python3 --version)). Use Ubuntu 24.04 / Debian 12, or install a newer Python first."

NODEV=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
if [ "$NODEV" -lt 20 ]; then
  say "Installing Node.js 22 (NodeSource) to build the dashboard"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
  apt-get install -y -qq nodejs >/dev/null
fi

say "Creating the service user and folders"
id smm >/dev/null 2>&1 || useradd --system --home /var/lib/smm --shell /usr/sbin/nologin smm
install -d -o smm -g smm -m 750 /var/lib/smm /var/log/smm /var/backups/smm
install -d -m 750 -o root -g smm /etc/smm
chown -R smm:smm /opt/smm

say "Setting up the API (Python environment)"
as_smm python3 -m venv /opt/smm/api/.venv
as_smm /opt/smm/api/.venv/bin/pip install -q --upgrade pip
as_smm /opt/smm/api/.venv/bin/pip install -q -r /opt/smm/api/requirements.txt

ENV_FILE=/etc/smm/smm.env
if [ -f "$ENV_FILE" ]; then
  say "Keeping your existing $ENV_FILE"
else
  say "Writing $ENV_FILE with fresh secrets"
  PY=/opt/smm/api/.venv/bin/python
  SECRET=$($PY -c 'import secrets; print(secrets.token_urlsafe(48))')
  FERNET=$($PY -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
  ADMIN_PW=$($PY -c 'import secrets; print(secrets.token_urlsafe(16))')
  sed -e "s|SMM_SECRET_KEY=__GENERATED__|SMM_SECRET_KEY=$SECRET|" \
      -e "s|SMM_TOKEN_ENCRYPTION_KEY=__GENERATED__|SMM_TOKEN_ENCRYPTION_KEY=$FERNET|" \
      -e "s|SMM_ADMIN_PASSWORD=__GENERATED__|SMM_ADMIN_PASSWORD=$ADMIN_PW|" \
      -e "s|__ADMIN_EMAIL__|$ADMIN_EMAIL|" \
      -e "s|authority.thegrowthstacker.in|$DOMAIN|g" \
      /opt/smm/deploy/env.production.example > "$ENV_FILE"
  chown root:smm "$ENV_FILE"; chmod 640 "$ENV_FILE"
  GENERATED_ADMIN_PW="$ADMIN_PW"
fi

say "Building the dashboard"
cd /opt/smm/dashboard
as_smm npm ci --no-audit --no-fund --silent
as_smm env VITE_API_URL=/api npm run build --silent
chmod -R a+rX /opt/smm/dashboard/dist
# nginx (www-data) must be able to walk down to dist/
chmod a+x /opt /opt/smm /opt/smm/dashboard

say "Installing services, scheduled jobs and the nginx site"
install -m 644 /opt/smm/deploy/smm-api.service /etc/systemd/system/smm-api.service
install -m 644 /opt/smm/deploy/smm-publish.service /etc/systemd/system/smm-publish.service
install -m 644 /opt/smm/deploy/smm.cron /etc/cron.d/smm
chmod +x /opt/smm/deploy/backup.sh /opt/smm/deploy/update.sh
SITE=/etc/nginx/sites-available/$DOMAIN
if [ -f "$SITE" ] && grep -q "listen 443" "$SITE"; then
  echo "nginx site already has HTTPS configured by certbot: leaving it as is"
else
  sed "s|authority.thegrowthstacker.in|$DOMAIN|g" /opt/smm/deploy/nginx.conf > "$SITE"
fi
ln -sfn "$SITE" /etc/nginx/sites-enabled/$DOMAIN
nginx -t
systemctl daemon-reload
systemctl enable --now smm-api smm-publish >/dev/null
systemctl reload nginx

say "Waiting for the API to come up"
for i in $(seq 1 30); do
  if curl -fsS -H "Host: $DOMAIN" http://127.0.0.1/api/health >/dev/null 2>&1; then OK=1; break; fi
  sleep 1
done
[ "${OK:-0}" = 1 ] || { journalctl -u smm-api -n 40 --no-pager; die "The API did not become healthy. See the log above."; }
echo "API is healthy (through nginx)."

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 'Nginx Full' >/dev/null && echo "ufw: allowed HTTP and HTTPS"
fi

say "HTTPS"
SERVER_IP=$(curl -fsS https://api.ipify.org 2>/dev/null || true)
DNS_IP=$(dig +short A "$DOMAIN" | tail -n1 || true)
if [ -n "$CERTBOT_EMAIL" ] && [ -n "$SERVER_IP" ] && [ "$SERVER_IP" = "$DNS_IP" ]; then
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$CERTBOT_EMAIL" --redirect
  HTTPS_DONE=1
else
  echo "Not requesting a certificate yet: DNS for $DOMAIN is '${DNS_IP:-not set}', this server is '${SERVER_IP:-unknown}', certbot email '${CERTBOT_EMAIL:-not given}'."
  echo "Once an A record points $DOMAIN at this server, run:"
  echo "  sudo certbot --nginx -d $DOMAIN -m you@example.com --agree-tos --redirect"
fi

say "Done"
SCHEME=$([ "${HTTPS_DONE:-0}" = 1 ] && echo https || echo http)
echo "Dashboard:  $SCHEME://$DOMAIN"
echo "Sign in as: $ADMIN_EMAIL"
if [ -n "${GENERATED_ADMIN_PW:-}" ]; then
  echo "Password:   $GENERATED_ADMIN_PW   <- shown once. Change it after signing in (it is also in $ENV_FILE)."
fi
echo
echo "Logs:       journalctl -u smm-api -f      /var/log/smm/"
echo "Update:     sudo /opt/smm/deploy/update.sh"
echo "Optional:   add ANTHROPIC_API_KEY / LinkedIn / X credentials to $ENV_FILE, then: sudo systemctl restart smm-api smm-publish"
