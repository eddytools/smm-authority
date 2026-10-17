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
| GET/POST | `/users` | admin |
| GET/PATCH | `/users/{id}` | admin |
| GET | `/health` | public |

## Configuration (API, `SMM_` prefix)

`ENV`, `DATABASE_URL` (SQLite by default, any SQLAlchemy URL e.g. Postgres), `SECRET_KEY`,
`ACCESS_TOKEN_MINUTES`, `CORS_ORIGINS` (comma-separated), `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ALLOW_REGISTRATION`.
With `SMM_ENV=production` the API refuses to start without a random `SMM_SECRET_KEY` of 32+ characters.

## Known limitations of this first slice

- Tables are created on startup; add Alembic migrations before the schema grows.
- The dashboard keeps the JWT in `localStorage`. Move to an httpOnly cookie (same-site deployment) before launch.
- No login rate limiting, password-reset email or email verification yet.
- Ventures hold only basic fields. The Authority Brief, trend feed, planner and tracking attach to a venture next.
