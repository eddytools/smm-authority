#!/usr/bin/env bash
# Build the dashboard on THIS computer, upload it, and tell the server to update. Run it from your own machine:
#
#   ./scripts/deploy-from-local.sh                       # deploys to root@194.164.151.203
#   SERVER=root@1.2.3.4 ./scripts/deploy-from-local.sh   # another server
#   BRANCH=main ./scripts/deploy-from-local.sh           # another branch (default: the branch you are on)
#   ./scripts/deploy-from-local.sh --test                # run the backend tests first
#
# Needs: ssh access to the server (key or password), rsync, Node 20+. The server already has the app installed
# (deploy/install.sh), with the code at /opt/smm as a git clone. The API code reaches the server by `git pull`, so
# push your commits to GitHub first: this script stops if there are unpushed ones.
set -euo pipefail
cd "$(dirname "$0")/.."

SERVER="${SERVER:-root@194.164.151.203}"
BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
RUN_TESTS=0
[ "${1:-}" = "--test" ] && RUN_TESTS=1

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
command -v rsync >/dev/null || die "rsync is not installed."
command -v npm >/dev/null || die "Node.js/npm is not installed."

say "Checking the code is pushed ($BRANCH)"
git diff --quiet && git diff --cached --quiet || die "You have uncommitted changes. Commit them first."
git fetch -q origin "$BRANCH" || die "Could not fetch origin/$BRANCH."
[ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$BRANCH")" ] || die "Your $BRANCH differs from origin/$BRANCH. Push (or pull) first so the server gets the same code."

if [ "$RUN_TESTS" = 1 ]; then
  say "Running the backend tests"
  [ -d api/.venv ] || python3 -m venv api/.venv
  api/.venv/bin/pip install -q -r api/requirements-dev.txt
  (cd api && .venv/bin/python -m pytest -q)
fi

say "Building the dashboard on this computer"
(cd dashboard && npm ci --no-audit --no-fund --silent && VITE_API_URL=/api npm run build --silent)
[ -f dashboard/dist/index.html ] || die "The build did not produce dashboard/dist."

say "Uploading the dashboard to $SERVER"
ssh "$SERVER" 'mkdir -p /opt/smm/dashboard/dist'
rsync -az --delete dashboard/dist/ "$SERVER:/opt/smm/dashboard/dist/"

say "Updating the server (backup, pull $BRANCH, dependencies, migrations, restart)"
ssh "$SERVER" "set -e; cd /opt/smm; runuser -u smm -- git fetch -q origin '$BRANCH'; runuser -u smm -- git checkout -q '$BRANCH'; SMM_SKIP_DASHBOARD_BUILD=1 /opt/smm/deploy/update.sh"

say "Done. Open https://authority.thegrowthstacker.in and sign in."
