# MY.md: run SMM Authority (local and on my server)

Plain steps, copy and paste. Details live in `README.md` and `docs/DEPLOY.md`.

---

## A. On my computer (local)

You need: **Python 3.11+**, **Node 20+**, **git**.

1. Get the code
   ```bash
   git clone -b claude/gifted-bell-e2oh51 https://github.com/eddytools/smm-authority.git
   cd smm-authority
   ```
2. Start everything with one command
   ```bash
   ./scripts/dev.sh
   ```
   First run installs dependencies, creates `api/.env`, loads demo data, then starts the API (`:8000`), the post
   publisher, the results puller and the dashboard (`:5173`). Stop with `Ctrl+C`.
3. Open **http://localhost:5173** and sign in:
   - demo user: `demo@example.com` / `demo-password-1` (fictional "Acme SaaS Growth" venture)
   - admin: `admin@example.com` / `change-me-now` (from `api/.env`)
   - start from empty data instead: `./scripts/dev.sh --reset` rebuilds the demo; delete `api/smm.db` to wipe everything.
4. (Optional) turn on AI. Edit `api/.env`, add **one** of these, save, then stop and rerun `./scripts/dev.sh`:
   ```bash
   ANTHROPIC_API_KEY=sk-ant-...                       # Claude
   # or
   OPENAI_API_KEY=sk-...        and  SMM_AI_MODEL=<model id from OpenAI's model list>
   # or
   GEMINI_API_KEY=...           and  SMM_AI_MODEL=<model id from Google's model list>
   # or any OpenAI-compatible server (Groq, OpenRouter, Together, Ollama...):
   SMM_AI_PROVIDER=openai
   SMM_OPENAI_BASE_URL=http://localhost:11434/v1      # example: Ollama
   SMM_AI_MODEL=<model id>
   ```
   Then sign in as admin, go to **Users** (top of the page), and press **Test the AI connection**. Without a key the
   app works; only drafting, scoring, quick replies and brief suggestions are off.
5. (Optional) run the tests
   ```bash
   cd api && .venv/bin/python -m pytest -q        # backend, about a minute
   cd ../dashboard && npm run build               # type-check + build the dashboard
   ```

Local troubleshooting
- "Address already in use": something else uses port 8000 or 5173. Stop it, or change the port.
- Sign-in fails after pulling new code: delete `api/smm.db` (dev data only) and rerun.
- AI test says "SMM_AI_MODEL is required" at startup: OpenAI and Gemini need `SMM_AI_MODEL` set.

---

## B. On my server (VPS) at https://authority.thegrowthstacker.in

You need: a VPS running **Ubuntu 24.04 or Debian 12**, root/sudo, ports **80 and 443** open.

1. **DNS (in the domain's DNS panel).** Add an `A` record:
   `authority` -> your VPS IPv4. Check it from anywhere:
   ```bash
   dig +short authority.thegrowthstacker.in
   ```
   It must print the VPS IP before HTTPS can be issued (can take a few minutes to hours).
2. **SSH in and install** (replace the two emails):
   ```bash
   ssh root@YOUR_VPS_IP
   apt-get update && apt-get install -y git
   git clone -b claude/gifted-bell-e2oh51 https://github.com/eddytools/smm-authority.git /opt/smm
   /opt/smm/deploy/install.sh --admin-email you@example.com --certbot-email you@example.com
   ```
   If the repo is private, `git clone` asks for your GitHub username and a **personal access token** as the password.
   The installer takes a few minutes. At the end it prints the **admin password once**: copy it now.
3. **Sign in:** https://authority.thegrowthstacker.in with the admin email and that password. Change the password after.
4. **If HTTPS did not get issued** (DNS wasn't ready), once `dig` shows the right IP run:
   ```bash
   certbot --nginx -d authority.thegrowthstacker.in -m you@example.com --agree-tos --redirect
   ```
5. **Turn on AI** (optional). Edit the settings file, add one vendor, restart:
   ```bash
   nano /etc/smm/smm.env
   #   ANTHROPIC_API_KEY=sk-ant-...
   #   (or)  OPENAI_API_KEY=sk-...   +  SMM_AI_MODEL=<model id>
   #   (or)  GEMINI_API_KEY=...      +  SMM_AI_MODEL=<model id>
   #   (or)  SMM_AI_PROVIDER=openai  +  SMM_OPENAI_BASE_URL=https://...  +  SMM_AI_MODEL=<model id>
   systemctl restart smm-api smm-publish
   ```
   Then in the dashboard: **Users** page -> **Test the AI connection**.
6. **Turn on LinkedIn / X posting** (optional). Create an app on each platform's developer portal, set its redirect URL to
   `https://authority.thegrowthstacker.in/api/integrations/linkedin/callback` (or `.../x/callback`), put the
   client id and secret in `/etc/smm/smm.env` (`SMM_LINKEDIN_CLIENT_ID`, `SMM_LINKEDIN_CLIENT_SECRET`, `SMM_X_CLIENT_ID`,
   `SMM_X_CLIENT_SECRET`), then `systemctl restart smm-api smm-publish`. Connect the account on a venture's **Publishing** page.
7. **Let more people in** (optional): Users page -> add users. Or set `SMM_ALLOW_REGISTRATION=true` in `/etc/smm/smm.env`
   and restart to allow self sign-up.

### Every day on the server

| What | Command |
|---|---|
| Update to the latest code | `sudo /opt/smm/deploy/update.sh` |
| Is it running? | `systemctl status smm-api smm-publish` and `curl -s https://authority.thegrowthstacker.in/api/health` |
| API log | `journalctl -u smm-api -f` |
| Job logs (feed, results, backups) | `tail -f /var/log/smm/*.log` |
| Restart | `sudo systemctl restart smm-api smm-publish` |
| Backups | `/var/backups/smm` (nightly, 14 kept). **Copy these and `/etc/smm/smm.env` off the server regularly.** |

Restore a backup:
```bash
systemctl stop smm-api smm-publish
runuser -u smm -- sh -c 'gunzip -c /var/backups/smm/smm-YYYYMMDD-HHMMSS.db.gz > /var/lib/smm/smm.db'
systemctl start smm-api smm-publish
```

### If something goes wrong
- **Installer stopped with an error:** read the red message, fix it, run the same install command again (it is safe to repeat).
- **Site shows nginx welcome page or 502:** `systemctl status smm-api`, then `journalctl -u smm-api -n 50`.
- **API won't start, mentions `SMM_AI_MODEL` or a key:** the AI settings in `/etc/smm/smm.env` are incomplete: fix or remove them.
- **Update says "database is at migration ..."**: run `cd /opt/smm/api && sudo -u smm /opt/smm/api/.venv/bin/alembic upgrade head` with the env loaded, or just rerun `update.sh`.
- Still stuck: copy the error output and send it to me.

### Remember
- Never commit or share `/etc/smm/smm.env`: it holds the secret key, the token-encryption key and API keys. Keep a copy somewhere safe,
  because saved LinkedIn/X connections can't be decrypted without it.
- The deploy scripts and the OpenAI / Gemini / X / LinkedIn connections have **not** been run against the real services yet: test each once.
