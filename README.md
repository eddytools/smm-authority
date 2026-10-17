# SMM Authority

SaaS that helps prospects build online authority, grow their brand and convert attention into leads.
See [`docs/PRD.md`](docs/PRD.md) and [`docs/SCOPE.md`](docs/SCOPE.md).

## Layout

| Folder | What | Stack |
|---|---|---|
| [`api/`](api) | Standalone REST API. Owns auth, roles, data. | Python, FastAPI, SQLAlchemy 2 |
| [`dashboard/`](dashboard) | Web UI. Talks to the API over HTTP only, never to the database. | React, TypeScript, Vite |

The two are deployed and versioned independently; the only contract between them is the API
(`/docs` serves interactive OpenAPI docs). Recurring jobs (ingestion, scheduling, metrics) will be
Python scripts living beside the API; AI APIs are used for research only (see PRD section 7).

## Roles and ownership

- **user**: registers themselves, creates **any number of ventures**, sees and edits only their own.
- **admin**: everything a user can do, plus manage users (create, change role, deactivate/reactivate, reset password)
  and view/edit/delete any venture (`GET /ventures?scope=all`).
- Self-registration always creates a `user`. The first admin is bootstrapped from `SMM_ADMIN_EMAIL` /
  `SMM_ADMIN_PASSWORD` at startup (never overwritten if it already exists). Admins can promote others.
- An admin cannot demote or deactivate their own account, so an admin always remains.
- Deactivation takes effect immediately (the user is re-checked on every request).
- A venture belongs to one owner; other users get `404` (not `403`) for ventures they don't own.
  Venture names are unique per owner.

## Run locally

```bash
# 1. API  (http://localhost:8000, docs at /docs)
cd api
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # set SMM_ADMIN_EMAIL / SMM_ADMIN_PASSWORD / SMM_SECRET_KEY
.venv/bin/uvicorn --factory app.main:create_app --reload

# 2. Dashboard  (http://localhost:5173)
cd dashboard
cp .env.example .env            # VITE_API_URL=http://localhost:8000
npm install && npm run dev
```

Tests: `cd api && .venv/bin/python -m pytest` and `cd dashboard && npm run build` (typecheck + build).

## API overview

| Method | Path | Access |
|---|---|---|
| POST | `/auth/register`, `/auth/login` | public |
| GET | `/auth/me` | any signed-in user |
| GET/POST | `/ventures` (`?scope=mine\|all`, `include_archived`, `limit`, `offset`) | user (`all` = admin) |
| GET/PATCH/DELETE | `/ventures/{id}` | owner or admin |
| GET/PUT | `/ventures/{id}/brief` (PUT appends a new version) | owner or admin |
| GET | `/ventures/{id}/brief/versions`, `/ventures/{id}/brief/versions/{n}` | owner or admin |
| POST | `/ventures/{id}/brief/suggest` (AI draft, not saved) | owner or admin |
| GET/POST | `/ventures/{id}/sources`, PATCH/DELETE `/ventures/{id}/sources/{sid}` | owner or admin |
| GET | `/ventures/{id}/feed` (`status=active\|new\|saved\|dismissed`, `source_id`, `limit`, `offset`) | owner or admin |
| PATCH | `/ventures/{id}/feed/{item}` (save / dismiss / restore) | owner or admin |
| POST | `/ventures/{id}/feed/refresh` (runs the ingest script now), `/ventures/{id}/feed/score` (on-demand AI) | owner or admin |
| GET | `/planner/framework` (stages, post types, platform rules, status pipeline) | any signed-in user |
| POST | `/ventures/{id}/plan/generate` (`start_date`, `period=week\|month`, `timezone`, `mix`, `replace`) | owner or admin |
| GET | `/ventures/{id}/plan` (`start`, `end`, `status`, `include_archived`) | owner or admin |
| POST / PATCH / DELETE | `/ventures/{id}/plan/slots[/{slot}]` | owner or admin |
| GET/POST | `/users` | admin |
| GET/PATCH | `/users/{id}` | admin |
| GET | `/health` | public |

## Authority setup (per venture)

Each venture has a one-time, editable **Authority Brief**: ICP, ideation (niche, angle, 3-5 pillars, proof, opinions),
offer/funnel links, voice, and platform choice with weekly cadence. Saving never edits history, it appends a new version,
and restoring an old version is just saving it again.

"Suggest with AI" drafts ideation and platform choices from what the user has typed. It is on-demand only, never saved
automatically, and is capped per non-admin user per 24h (`SMM_AI_DAILY_LIMIT_PER_USER`). Calls go through
`app/ai.py` (Anthropic SDK, structured output, model `SMM_AI_MODEL`). Without `ANTHROPIC_API_KEY` the endpoint
returns 503 and the rest of the app is unaffected. Token usage is recorded in `ai_usage`.

## Trend feed

Each venture has sources: **RSS URLs, subreddits, and Google News queries** (up to 20). Items are ranked for the niche
without any AI: the ingest script scores each one 0-100 from keyword overlap with the venture's Authority Brief (50%),
freshness (30%) and engagement (20%). **Score with AI** (optional, on request, counts against the daily AI limit) sends only
the best unscored items from the last 14 days, in one call, and stores a 0-100 relevance and a one-line "why it matters".
Items are deduplicated by normalised URL, can be saved or dismissed (dismissed items do not come back), and unsaved items
are pruned after `SMM_FEED_RETENTION_DAYS` (30).

The recurring work is a plain script, not an AI call. Schedule it, for example hourly:

```cron
0 * * * *  cd /srv/smm/api && .venv/bin/python -m app.jobs.ingest >> /var/log/smm-ingest.log 2>&1
```

`python -m app.jobs.ingest --venture 7` runs one venture. Each source records `last_status` / `last_error`, so a broken
feed shows up in the dashboard instead of failing silently, and one bad source never blocks the others.

**Fetching user-supplied URLs is SSRF-guarded** (`app/fetch.py`): http(s) only, no embedded credentials, every hop
including redirects must resolve to a public IP, the connection is pinned to the validated IP while TLS still verifies the
hostname, and redirects/size/time are capped.

## Content planner

Built on the three-stage funnel and ten post types (`app/framework.py`): **TOFU / growth** (newsjacking, awareness,
educational, spectacle), **MOFU / trust** (story, short video, lead magnet), **BOFU / selling** (conversion, objection,
product demo). Generating a **week or month** is plain deterministic code (`app/planner.py`), no AI:

- one slot per planned post, using each platform's weekly cadence from the Authority setup and assumed best-time windows
  (tunable in `PLATFORM_SCHEDULE`), in the user's timezone;
- a funnel mix (default 50/30/20, editable) with a month rhythm of growth, then trust, then capture, then convert;
  within each week growth posts come before selling posts, and every stage and pillar appears;
- platform rules (Reddit gets no promotional or video posts; blog/newsletter get no short video);
- real topics from the trend feed (saved items first), each used once; other slots get the framework's guidance as a prompt;
- CTAs from the offer links, and reserved reactive (newsjacking) slots flagged with ⚡.

Status pipeline: Idea → Drafted → In review → Approved → Scheduled → Published → Analysed (plus Skipped, Archived).
A draft is required before a post leaves Idea, nothing can be Scheduled without being Approved first, and published posts
are read-only. Regenerating asks for confirmation and only replaces untouched ideas: anything the user edited, moved
(dragged posts get a 🔒) or locked is kept.

## Configuration (API, `SMM_` prefix)

`ENV`, `DATABASE_URL` (SQLite by default, any SQLAlchemy URL e.g. Postgres), `SECRET_KEY`,
`ACCESS_TOKEN_MINUTES`, `CORS_ORIGINS` (comma-separated), `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ALLOW_REGISTRATION`,
`AI_MODEL`, `AI_DAILY_LIMIT_PER_USER`, `AI_SCORE_BATCH` (items per scoring call, 20), `FEED_RETENTION_DAYS`,
`REFRESH_MIN_INTERVAL_SECONDS` (60), `FETCH_USER_AGENT`, and `ANTHROPIC_API_KEY` (also accepted as `SMM_ANTHROPIC_API_KEY`).
With `SMM_ENV=production` the API refuses to start without a random `SMM_SECRET_KEY` of 32+ characters.

## Known limitations of this first slice

- Tables are created on startup; add Alembic migrations before the schema grows.
- The dashboard keeps the JWT in `localStorage`. Move to an httpOnly cookie (same-site deployment) before launch.
- No login rate limiting, password-reset email or email verification yet.
- The AI suggestion call has not been run against the live Anthropic API in this repo (no key in the build environment);
  it is covered by tests with a stubbed client and a schema check. Do one real call before relying on it.
- Refusal fallbacks (`fallbacks`) are not enabled: refusals surface as a 502 with a clear message. Add them if
  suggestions ever get declined in practice.
- **Feed fetching has not been run against the real internet from this repo.** The build sandbox only reaches the web
  through an HTTPS proxy, and the fetcher connects directly (needed for its SSRF guard). It is tested against local
  HTTP and HTTPS servers (including certificate verification) and with canned feeds, not live Reddit/Google. Run one
  refresh on a real server before relying on it, and note it will not work on a host that only allows egress via a proxy.
- Reddit's public JSON endpoint is rate-limited and often blocked from datacenter IPs, and Reddit's terms restrict
  commercial use. Plan to move to Reddit's OAuth API with a registered app before launch.
- Not built yet: X and Google Trends sources (they need paid API access), per-source "dismissals tune relevance",
  turning a feed item into a post idea, and an opt-in schedule for AI scoring.
- The planner schedules and tracks posts but does **not publish** anything yet: "Published" is set by hand. Drafting
  with AI in the user's voice, auto-publishing to LinkedIn/X, and performance tracking are the next slices.
- Best-time windows and the month rhythm are assumed defaults, not measured data; tune them once real results exist.
- The planner UI has no "add a post" button yet (the API supports it).
- SQLite is for development; production should use Postgres (set `SMM_DATABASE_URL`).
