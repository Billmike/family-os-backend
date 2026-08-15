# FamilyOS Family API

Client-agnostic backend for FamilyOS v0.1 (FastAPI + PostgreSQL).

## Stack

- FastAPI, Pydantic, SQLAlchemy 2
- PostgreSQL 16
- Alembic migrations
- WebSockets (family realtime: events, tasks, shopping)
- Web Push (VAPID) + reminder scheduler

## Quick start (Docker)

```bash
cd backend
cp .env.example .env
# Set a unique JWT_SECRET (required; app refuses known placeholders / short values)
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Paste the output into JWT_SECRET in .env, then:
docker compose up --build
```

API: http://localhost:8001  
OpenAPI docs: http://localhost:8001/docs  
Health: http://localhost:8001/health

Seed demo data (with API/DB running):

```bash
docker compose exec api python -m scripts.seed
```

Demo logins after seed:

- `kayode@familyos.app` / `password123`
- `ade@familyos.app` / `password123`

## Local development (without Docker API)

```bash
cd backend
uv sync
cp .env.example .env
# Set JWT_SECRET in .env (see Quick start); never commit real secrets
docker compose up db -d
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8001
uv run python -m scripts.seed
```

Postgres is exposed on host port **5435** and the API on **8001** by default (to avoid clashing with other local services).
## Tests

```bash
cd backend
uv run pytest -q
```

## Deploy notes (Cloud Run + managed Postgres)

1. Provision managed PostgreSQL and set `DATABASE_URL=postgresql+psycopg://...`.
2. Set a unique `JWT_SECRET` (≥32 chars; startup fails on placeholders). Set `CORS_ORIGINS` to your PWA origin(s).
3. Set `PUBLIC_APP_URL` to the public web app origin (used in invitation links, e.g. `https://app.example.com`).
4. `EMAIL_PROVIDER=log` (default) only logs invitation emails; plug in a real provider later.
5. Generate VAPID keys for Web Push. Keep `private_key.pem` locally and set env from it:
   `python -m scripts.print_vapid_env` → copy `VAPID_PRIVATE_KEY=base64url:…` and matching `VAPID_PUBLIC_KEY`.
   Use the `base64url:` form in Sevalla/Cloud — raw PEM often breaks when `+` becomes a space.
   `VAPID_CONTACT_EMAIL` must be `mailto:…`. Push is sent **during** the request (not after).
6. Build the Docker image and deploy to Cloud Run (or similar).
7. Run migrations on deploy: `alembic upgrade head` (Cloud Run job or startup command).
8. Single instance is enough for MVP WebSocket fan-out; add Redis later if you scale horizontally.

## Auth

- `POST /api/auth/register` — email, password, name
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `GET /api/auth/me`

Use `Authorization: Bearer <access_token>` on family-scoped routes.

## Core routes

See OpenAPI at `/docs`. Domains: families, dashboard, events, tasks, shopping, notifications, push, WebSocket `/api/ws/families/{family_id}?token=...`.

**Frontend integration guide (URLs, request bodies, responses):** [FRONTEND_API.md](./FRONTEND_API.md)
