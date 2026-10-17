# Deploying to a VPS (authority.thegrowthstacker.in)

One server, nginx in front, no containers: the API and the scheduled jobs run under systemd/cron as an unprivileged `smm`
user, SQLite lives in `/var/lib/smm`, and nginx serves the built dashboard and proxies `/api/` to the API on `127.0.0.1:8010`.
Because the dashboard and API share one host there is no CORS to configure.

## Before you start

1. **A server** running Ubuntu 24.04 or Debian 12 (anything with Python 3.11+ and `apt`), with ports 80 and 443 open and
   root/sudo access. About 1 GB of RAM is enough (the dashboard build is the heaviest step; add swap on 512 MB machines).
2. **DNS:** an `A` record `authority` for `thegrowthstacker.in` pointing at the server's IPv4 address (and an `AAAA` record if you
   want IPv6). Check with `dig +short authority.thegrowthstacker.in`. HTTPS can't be issued until this resolves to the server.
3. **Other sites are fine.** The installer adds one nginx site for this domain and never edits your existing ones. If something
   else already uses port 8010, change it in `deploy/smm-api.service` and `deploy/nginx.conf`.

## Install

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone -b claude/gifted-bell-e2oh51 https://github.com/eddytools/smm-authority.git /opt/smm
sudo /opt/smm/deploy/install.sh --admin-email you@example.com --certbot-email you@example.com
```

If the repository is private, clone with a [personal access token](https://github.com/settings/tokens) (read-only, this repo)
or a deploy key; `update.sh` later runs `git pull` as the `smm` user, so store that credential for the `smm` user too
(`sudo -u smm git config --global credential.helper store`, then one authenticated pull), or run updates by hand.

The installer, in order: installs packages (nginx, certbot, Python venv, Node 22 for the build), creates the `smm` user, installs
Python dependencies, writes `/etc/smm/smm.env` with freshly generated secrets, builds the dashboard, installs the systemd units
and cron jobs and the nginx site, starts everything, checks `/api/health` through nginx, and requests the HTTPS certificate if DNS
already points here. It prints the admin password **once** at the end. Re-running it is safe: it keeps `/etc/smm/smm.env` and the
database.

## What runs

| Piece | How | Notes |
| --- | --- | --- |
| API | `smm-api.service` (uvicorn, 1 worker, `127.0.0.1:8010`) | applies database migrations before starting |
| Scheduled posting | `smm-publish.service` (loop, every 60 s) | no-op until a LinkedIn/X account is connected |
| Trend feed refresh | cron, every 8 hours (`/etc/cron.d/smm`) | log: `/var/log/smm/ingest.log` |
| X results pull | cron, hourly | log: `/var/log/smm/metrics.log` |
| Backups | cron, 03:40 nightly | `/var/backups/smm`, newest 14 kept |
| Dashboard | static files from `/opt/smm/dashboard/dist` | built with `VITE_API_URL=/api` |

The API runs **one worker** on purpose: the login rate limit is held in memory, and SQLite wants one writer. Moving to several
workers or machines means PostgreSQL and a shared rate-limit store first (see Known limitations in the README).

## Settings

Everything is in `/etc/smm/smm.env` (readable only by root and the `smm` group). After editing it:
`sudo systemctl restart smm-api smm-publish`.

- **Registration is closed** (`SMM_ALLOW_REGISTRATION=false`): the only account is the admin. Create users from the Admin page,
  or set it to `true` to let people sign up.
- **AI features** (drafting, scoring, quick replies, brief suggestions) need `ANTHROPIC_API_KEY=` in that file. Without it they
  return a clear "not configured" message and everything else works.
- **Publishing:** add the LinkedIn and/or X app credentials, and register
  `https://authority.thegrowthstacker.in/api/integrations/linkedin/callback` (and `.../x/callback`) as the redirect URL in each
  developer portal. `SMM_TOKEN_ENCRYPTION_KEY` is already generated: back it up with the database, because OAuth tokens can't be
  decrypted without it.

## Updating

```bash
sudo /opt/smm/deploy/update.sh
```

Backs up the database, pulls, reinstalls dependencies, rebuilds the dashboard, restarts the services (migrations run on start)
and checks health. If the API doesn't come back it says so and leaves the backup in `/var/backups/smm`.

## Restoring a backup

```bash
sudo systemctl stop smm-api smm-publish
sudo -u smm sh -c 'gunzip -c /var/backups/smm/smm-YYYYMMDD-HHMMSS.db.gz > /var/lib/smm/smm.db'
sudo systemctl start smm-api smm-publish
```

Copy `/var/backups/smm` and `/etc/smm/smm.env` off the server too: a backup on the same disk doesn't survive losing the disk.

## Checking on it

```bash
systemctl status smm-api smm-publish
journalctl -u smm-api -f          # API log
tail -f /var/log/smm/*.log        # scheduled jobs
curl -s https://authority.thegrowthstacker.in/api/health
```

## Not covered

- No firewall, SSH hardening, fail2ban or OS update policy: those are server-wide choices (at minimum `ufw allow OpenSSH` before
  enabling `ufw`, and unattended security upgrades).
- SQLite is the database. That is fine for a handful of users on one server; the Alembic migrations have only been run on SQLite.
- Nothing monitors the server. A free uptime check against `/api/health` is a sensible first step.
- The installer has been syntax-checked and the same production configuration (production mode, migrations, `/api` prefix,
  same-origin dashboard, closed registration, no API docs) was tested locally behind a stand-in for nginx, but the scripts
  themselves have **not been run on a real server**. Read `deploy/install.sh` before running it as root, and send me the
  output if anything fails.
