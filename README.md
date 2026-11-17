# Personal Mail API

> **One API. All your applications. Your email infrastructure.**

A lightweight, open-source, self-hostable email API built with **FastAPI** and
**Resend**. Deploy it once, register your applications, and send contact-form
messages, notifications and transactional email through one service.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Contents

- [Why](#why)
- [Features](#features)
- [Architecture](#architecture)
- [Quick start (Docker)](#quick-start-docker)
- [Installation (without Docker)](#installation-without-docker)
- [Resend setup](#resend-setup)
- [Supabase setup](#supabase-setup)
- [Deployment](#deployment)
- [Admin web page](#admin-web-page)
- [API usage](#api-usage)
- [Frontend integration](#frontend-integration)
- [Configuration reference](#configuration-reference)
- [Security model](#security-model)
- [Testing](#testing)
- [Open source](#open-source)

## Why

Developers often build the same email plumbing again and again: one contact
form for the portfolio, another for the business site, a welcome-email
service for the SaaS app. Personal Mail API replaces all of them with **one
backend**. Every application is a *project* with its own API key, recipient,
permissions and limits.

## Features

- **Multi-project.** Isolated projects, each with a hashed API key, recipient, sender identity, permissions, rate limit and daily quota.
- **Public contact form endpoint.** No secrets in browser code. Protected by origin checks, rate limiting, a honeypot field and optional Cloudflare Turnstile.
- **Transactional email.** Raw HTML/text or built-in templates (welcome, password reset, email verification, notification).
- **Owner notifications.** New sign-ups, enquiries and system events go to the project's configured recipient.
- **Delivery tracking.** Every email is logged. Signed Resend webhooks update the status (`sent`, `delivered`, `bounced`, `complained`, and so on) idempotently.
- **Secure by default.** Argon2 admin passwords, short-lived JWTs, SHA-256-hashed API keys shown once, header-injection protection, autoescaped templates, fixed sender identities, PostgreSQL-backed rate limiting (no Redis), request size limits.
- **Simple to run.** One FastAPI service, one PostgreSQL database (Supabase in production), Alembic migrations, Docker, a Render blueprint, Swagger docs at `/docs`.

## Architecture

```
 Portfolio ─┐                    ┌──────────────── Personal Mail API ────────────────┐
 CareerDocs ─┼── HTTPS (JSON) ──▶ │ api/       routing, auth, validation, envelopes   │──▶ Resend
 Safari AI ─┤                    │ services/  permissions, quotas, templates, logs   │
 Others  ───┘                    │ models/    SQLAlchemy 2.0                         │──▶ Supabase PostgreSQL
 Resend webhooks ───────────────▶│ /api/v1/webhooks/resend (Svix-signed)             │
                                 └───────────────────────────────────────────────────┘
```

A modular monolith with no queues, no Redis and no microservices. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for layers, the database schema
and the email status lifecycle.

| Caller | Credential | Endpoints |
|---|---|---|
| Browser contact form | Public project **slug** | `POST /api/v1/contact` |
| Your backend / serverless function | Project API key `Authorization: Bearer pmk_...` | `/api/v1/emails/*`, `/api/v1/notifications` |
| Administrator | JWT from `/api/v1/auth/login` | `/api/v1/admin/projects/*` |
| Resend | Svix signature | `/api/v1/webhooks/resend` |

## Quick start (Docker)

```bash
git clone https://github.com/<you>/personal-mail-api.git
cd personal-mail-api
cp .env.example .env     # set RESEND_API_KEY, DEFAULT_FROM_EMAIL, JWT_SECRET_KEY
docker compose up --build
```

The API is now on <http://localhost:8000> (Swagger UI at `/docs`). Migrations
run automatically on start. Create the first administrator in one of two ways:

- **Environment variables** (works anywhere, including hosts without a shell):
  set `ADMIN_EMAIL` and `ADMIN_PASSWORD` (12+ characters) in `.env` and restart.
  The admin is created on start. Changing `ADMIN_PASSWORD` and restarting
  updates the password.
- **CLI:** `docker compose exec api python scripts/create_admin.py --email you@example.com`

## Installation (without Docker)

**Prerequisites:** Python 3.12+, PostgreSQL 14+ (or Docker for the bundled database), and a Resend account.

```bash
git clone https://github.com/<you>/personal-mail-api.git
cd personal-mail-api

python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt  # or requirements.txt for production only

cp .env.example .env                 # then edit; see the configuration reference
docker compose up -d db              # optional: local PostgreSQL on port 5433

alembic upgrade head                 # create the tables
python scripts/create_admin.py --email you@example.com   # prompts for a password
uvicorn app.main:app --reload        # http://localhost:8000/docs
```

Generate a JWT secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Resend setup

1. Create an account at [resend.com](https://resend.com).
2. **API key:** go to *API Keys → Create API key*. "Sending access" is enough. Put it in `RESEND_API_KEY`.
3. **Verify a domain:** go to *Domains → Add domain* and use a subdomain such as `mail.example.com`.
4. **DNS:** add the records Resend shows at your DNS provider.
   - **SPF** (TXT/MX on `send.<domain>`) authorises Resend to send for your domain.
   - **DKIM** (TXT `resend._domainkey`) cryptographically signs your mail.
   - **DMARC** (recommended): a TXT record `_dmarc` with `v=DMARC1; p=none;` to start.

   Wait until the domain shows **Verified**.
5. **Sender:** set `DEFAULT_FROM_EMAIL=noreply@mail.example.com`. Projects may use
   other senders on the same domain, or on domains listed in `ALLOWED_SENDER_DOMAINS`.
6. **Webhooks (delivery tracking):** go to *Webhooks → Add endpoint*, use
   `https://<your-api>/api/v1/webhooks/resend`, and select the `email.sent`, `email.delivered`,
   `email.delivery_delayed`, `email.bounced`, `email.complained` and `email.failed`
   events. Copy the signing secret (`whsec_...`) into `RESEND_WEBHOOK_SECRET`.

> **Testing without a domain:** `DEFAULT_FROM_EMAIL=onboarding@resend.dev` works,
> but Resend then only delivers to your own account email (or to the
> `delivered@resend.dev` test address).

## Supabase setup

1. Create a project at [supabase.com](https://supabase.com) and note the database password.
2. Open **Connect** (top bar) and copy a connection string:
   - **Session pooler** (port 5432, IPv4) is **recommended for Render**:
     `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`
   - Direct connection (`db.<ref>.supabase.co:5432`) is IPv6-only unless you buy the IPv4 add-on.
   - Transaction pooler (port 6543) also works. Prepared statements are disabled automatically.
3. Set `DATABASE_URL` to that string. SSL is **required automatically** when
   `APP_ENV=production`. To verify the server certificate, download the CA from
   *Database settings → SSL* and use `?sslmode=verify-full&sslrootcert=...`.
4. Run the migrations against Supabase once from your machine (or let the
   container do it on start):

   ```bash
   DATABASE_URL="postgresql://..." alembic upgrade head
   ```

The app talks to PostgreSQL directly through SQLAlchemy. Supabase's REST API,
auth and Row Level Security are not used, so keep the database credentials private.

## Deployment

### Docker (any host)

```bash
docker build -t personal-mail-api .
docker run -d -p 8000:8000 --env-file .env -e APP_ENV=production personal-mail-api
```

The image runs as a non-root user, has a `HEALTHCHECK` on `/health`, and its
entrypoint (`scripts/start.sh`) runs `alembic upgrade head` **once** before
starting uvicorn workers. A PostgreSQL advisory lock serialises migrations when
several instances start at the same time. Set `RUN_MIGRATIONS=false` to run
migrations as a separate step instead.

### Render

1. Push the repository to GitHub.
2. In Render, choose **New → Blueprint** and select the repository. `render.yaml`
   defines a Docker web service with health check path `/health`.
   (Or **New → Web Service → Docker** and set the same values by hand.)
3. Fill in the secret environment variables: `DATABASE_URL` (Supabase session
   pooler), `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `DEFAULT_FROM_EMAIL`
   and optionally `ALLOWED_SENDER_DOMAINS` and `TURNSTILE_SECRET_KEY`.
   `JWT_SECRET_KEY` is generated automatically.
   Also set `ADMIN_EMAIL` and `ADMIN_PASSWORD`. No shell is needed (the free
   plan has none): the administrator is created on every start if missing,
   and its password is kept in sync with `ADMIN_PASSWORD`.
4. Deploy. The logs show `Applying database migrations...` and then
   `Admin bootstrap: administrator you@example.com created.`
5. Point the Resend webhook at `https://<service>.onrender.com/api/v1/webhooks/resend`.

`TRUSTED_PROXY_COUNT=1` is preset so rate limits use the real client IP behind
Render's proxy. Use `2` if Cloudflare is in front of Render. Do not create a
Render PostgreSQL database; Supabase is the database.

### Production environment checklist

| Variable | Production value |
|---|---|
| `APP_ENV` | `production` (startup fails if secrets are missing or weak) |
| `DATABASE_URL` | Supabase connection string |
| `RESEND_API_KEY` | Resend key |
| `DEFAULT_FROM_EMAIL` | Address on a verified domain |
| `JWT_SECRET_KEY` | 32+ random characters |
| `RESEND_WEBHOOK_SECRET` | `whsec_...` from Resend |
| `TRUSTED_PROXY_COUNT` | `1` on Render |
| `CORS_ORIGINS` | Usually empty (see [Frontend integration](#frontend-integration)) |

## Admin web page

Open `https://<your-api>/admin` (the root URL redirects there) and sign in
with `ADMIN_EMAIL` / `ADMIN_PASSWORD`. From there you can:

* create projects and edit their settings,
* add the websites allowed to use a project's contact form (`allowed_origins`;
  `mysite.vercel.app` is accepted and stored as `https://mysite.vercel.app`),
* generate or revoke API keys (a new key is shown once),
* see today's usage, recent emails with their delivery status, and recent
  contact messages.

The page is static HTML and JavaScript that calls the same admin API
endpoints, so every check stays on the server. It uses a strict
Content-Security-Policy (same-origin only, no inline scripts) and keeps the
login token in `sessionStorage`, so closing the tab signs you out. Set
`ADMIN_UI_ENABLED=false` to turn it off.

## API usage

Every response uses the same envelope:

```json
{ "success": true,  "message": "Email accepted for delivery.", "data": { "...": "..." } }
{ "success": false, "message": "Too many requests. Please try again later.", "error": { "code": "RATE_LIMIT_EXCEEDED" } }
```

Full interactive documentation is at `/docs` (Swagger) and `/redoc`.

### 1. Log in as administrator

```bash
API=http://localhost:8000
TOKEN=$(curl -s $API/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"your-password"}' | jq -r .data.access_token)
```

### 2. Register projects

```bash
curl -s $API/api/v1/admin/projects -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
    "name": "Portfolio",
    "slug": "portfolio",
    "recipient_email": "you@example.com",
    "allowed_origins": ["https://yourportfolio.com", "http://localhost:3000"],
    "acknowledgement_enabled": false
  }'
```

The response contains `data.api_key.api_key` (`pmk_...`). **It is shown only
once.** Store it in your application's server-side secrets.

```bash
curl -s $API/api/v1/admin/projects -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
    "name": "CareerDocs",
    "slug": "careerdocs",
    "recipient_email": "team@careerdocs.example.com",
    "sender_name": "CareerDocs",
    "sender_email": "hello@mail.example.com",
    "transactional_enabled": true,
    "allowed_recipient_domains": [],
    "rate_limit": 120,
    "daily_quota": 2000
  }'
```

### 3. Manage projects and API keys

| Action | Request |
|---|---|
| List projects | `GET /api/v1/admin/projects?limit=50&offset=0` |
| View project | `GET /api/v1/admin/projects/{id}` |
| Update configuration | `PATCH /api/v1/admin/projects/{id}` with any subset of fields |
| Disable / re-enable | `POST /api/v1/admin/projects/{id}/disable` / `.../enable` |
| Delete (with all data) | `DELETE /api/v1/admin/projects/{id}` |
| List keys | `GET /api/v1/admin/projects/{id}/api-keys` |
| Regenerate key (revokes old keys) | `POST /api/v1/admin/projects/{id}/api-keys` |
| Revoke a key | `DELETE /api/v1/admin/projects/{id}/api-keys/{key_id}` |
| Usage | `GET /api/v1/admin/projects/{id}/usage` |
| Email logs | `GET /api/v1/admin/projects/{id}/emails?status=bounced` |
| Contact submissions | `GET /api/v1/admin/projects/{id}/contact-submissions` |

### 4. Contact form (public)

```bash
curl -s $API/api/v1/contact -H 'Content-Type: application/json' \
  -H 'Origin: https://yourportfolio.com' -d '{
    "project": "portfolio",
    "name": "John Doe",
    "email": "john@example.com",
    "subject": "Software Development Opportunity",
    "message": "I would like to discuss a project with you."
  }'
```

The message is stored and emailed to the project's `recipient_email` with
**Reply-To set to the sender**, so you can reply straight from your inbox.

### 5. Transactional email (private key)

```bash
KEY=pmk_...
# Raw content
curl -s $API/api/v1/emails/send -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{
    "to": "user@example.com",
    "subject": "Welcome to CareerDocs",
    "html": "<h1>Welcome!</h1>",
    "text": "Welcome to CareerDocs.",
    "reply_to": "support@example.com"
  }'

# Built-in template (app_name defaults to the project name)
curl -s $API/api/v1/emails/send -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{
    "to": "user@example.com",
    "template": "password_reset",
    "variables": { "name": "Jane", "reset_url": "https://app.example.com/reset?token=abc", "expires_in_minutes": 30 }
  }'
```

| Template | Required variables | Optional variables |
|---|---|---|
| `welcome` | none | `name`, `message`, `action_url`, `action_text`, `app_name` |
| `password_reset` | `reset_url` | `name`, `expires_in_minutes`, `app_name` |
| `email_verification` | none | `verification_url`, `code`, `name`, `expires_in_minutes`, `app_name` |
| `notification` | `notification_type`, `title`, `message` | `project_name`, `app_name` |

`202 Accepted` means **Resend accepted the request**, not that the email reached
the inbox. Delivery is reported through webhooks.

### 6. Notifications to yourself (private key)

```bash
curl -s $API/api/v1/notifications -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{
    "type": "user.registered",
    "subject": "New user registration",
    "message": "Jane just signed up.",
    "details": { "Email": "jane@example.com", "Plan": "Pro" }
  }'
```

### 7. Email logs and delivery status

```bash
curl -s "$API/api/v1/emails?limit=20&status=delivered" -H "Authorization: Bearer $KEY"
curl -s "$API/api/v1/emails/<email-id>" -H "Authorization: Bearer $KEY"   # includes webhook events
```

A project can only see its own logs.

### Error codes

| HTTP | Code | Meaning |
|---|---|---|
| 401 | `API_KEY_REQUIRED`, `INVALID_API_KEY`, `INVALID_TOKEN`, `INVALID_CREDENTIALS` | Authentication failed |
| 403 | `TRANSACTIONAL_DISABLED`, `NOTIFICATIONS_DISABLED`, `RECIPIENT_NOT_ALLOWED`, `ORIGIN_NOT_ALLOWED`, `TURNSTILE_FAILED`, `PROJECT_DISABLED` | Not permitted |
| 404 | `PROJECT_NOT_FOUND`, `EMAIL_NOT_FOUND` | Unknown resource |
| 413 | `PAYLOAD_TOO_LARGE` | Body exceeds `MAX_REQUEST_BODY_BYTES` |
| 422 | `VALIDATION_ERROR` | Invalid request (see `error.details`) |
| 400 | `INVALID_TEMPLATE_VARIABLES` | Template variables missing, unknown or unsafe |
| 429 | `RATE_LIMIT_EXCEEDED`, `DAILY_QUOTA_EXCEEDED` | Slow down (`Retry-After` header) |
| 502 | `EMAIL_DELIVERY_FAILED` | Resend rejected the email (for example, unverified domain) |
| 503 | `EMAIL_PROVIDER_UNAVAILABLE`, `SERVICE_MISCONFIGURED` | Retry later / fix configuration |
| 504 | `EMAIL_PROVIDER_TIMEOUT` | Resend did not answer; status unknown (retrying is safe) |

## Frontend integration

Complete examples live in [`examples/`](examples):

| Example | What it shows |
|---|---|
| [`examples/nextjs`](examples/nextjs) | Portfolio contact form component; server-only client; route handler sending a welcome email and notification |
| [`examples/react`](examples/react) | Drop-in contact form for any React app |
| [`examples/python`](examples/python) | `httpx` client for Django/Flask/FastAPI backends and scripts |

**The golden rule:** a project API key (`pmk_...`) is a password. **Never put
it in browser code**, `NEXT_PUBLIC_*` / `VITE_*` variables, or mobile apps. Only
the public contact endpoint is meant to be called from browsers, and it needs
only the project slug. Everything else goes through your backend or a
serverless function.

Browser calls to `/api/v1/contact` get CORS headers automatically. The
per-project `allowed_origins` list is enforced server-side. `CORS_ORIGINS` only
matters if you deliberately call other endpoints from a browser, which you
should not.

## Configuration reference

All settings are environment variables; see [`.env.example`](.env.example).

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test` or `production` (strict checks) |
| `DATABASE_URL` | *required* | PostgreSQL URL (`postgres://`, `postgresql://` accepted) |
| `DATABASE_SSL_MODE` | `require` in production | libpq sslmode |
| `DATABASE_TRANSACTION_POOLER` | auto (port 6543) | Disable prepared statements |
| `DATABASE_POOL_SIZE` / `_MAX_OVERFLOW` | 5 / 5 | Per worker |
| `RESEND_API_KEY` | none | Required in production |
| `RESEND_TIMEOUT_SECONDS` | 10 | Provider timeout |
| `RESEND_WEBHOOK_SECRET` | none | `whsec_...`; webhooks are rejected without it |
| `DEFAULT_FROM_EMAIL` / `DEFAULT_FROM_NAME` | none / Personal Mail API | Default sender |
| `ALLOWED_SENDER_DOMAINS` | DEFAULT_FROM_EMAIL's domain | Domains projects may send from |
| `JWT_SECRET_KEY` | *required* | 32+ characters in production |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | Admin token lifetime |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | none | Bootstrap administrator, created or updated at container start |
| `TURNSTILE_SECRET_KEY` | none | Needed by projects with `turnstile_enabled` |
| `RATE_LIMIT_ENABLED` | true | Global switch |
| `CONTACT_RATE_LIMIT_PER_IP` | 5 | Per IP, per project, per hour |
| `LOGIN_RATE_LIMIT_PER_IP` | 10 | Per IP and per email, per 15 minutes |
| `MAX_REQUEST_BODY_BYTES` | 524288 | Request size limit |
| `TRUSTED_PROXY_COUNT` | 0 | Proxies appending to X-Forwarded-For |
| `DOCS_ENABLED` | true | Serve `/docs`, `/redoc`, `/openapi.json` |
| `ADMIN_UI_ENABLED` | true | Serve the admin web page at `/admin` |
| `RUN_MIGRATIONS` / `WEB_CONCURRENCY` | true / 2 | Container entrypoint |

## Security model

- **No open relay.** Transactional sending is opt-in per project. Recipients can be limited to an allowlist of domains. The From address always comes from administrator configuration; callers can set only a display name.
- **Fixed recipients.** Contact and notification emails always go to the project's `recipient_email`.
- **Abuse limits.** Per-project requests per minute and emails per day; contact submissions per IP; admin logins per IP and per email. All are stored in PostgreSQL, so they hold across workers.
- **Spam protection.** Honeypot field, origin allowlist, optional Turnstile (fails closed), and size limits on every field. Acknowledgement emails contain no submitter-controlled text, so they cannot be used to spam third parties.
- **Injection.** CR/LF is rejected in every header-bound value. HTML templates are autoescaped. Template URLs must be `http(s)`.
- **Secrets.** API keys are SHA-256 hashed and shown once. Passwords use Argon2id. JWTs are signed with a pinned algorithm and have an audience and expiry. Logs redact keys, tokens and database passwords. Error responses never include stack traces.
- **Webhooks.** Svix HMAC signature verification with timestamp tolerance, constant-time comparison and idempotent processing.

Found a vulnerability? See [SECURITY.md](SECURITY.md).

## Testing

```bash
docker compose up -d db     # provides the isolated personal_mail_test database
pytest                      # 200+ tests; Resend is always mocked
ruff check . && ruff format --check .
```

`TEST_DATABASE_URL` selects another database. Its name must end in `_test`,
because the suite drops and rebuilds its schema.

## Open source

- **License:** [MIT](LICENSE).
- **Contributing:** see [CONTRIBUTING.md](CONTRIBUTING.md) (setup, coding standards, pull request checklist).
- **Issues:** open a GitHub issue with steps to reproduce, the expected and actual behaviour, and the version (`GET /health`). **Never paste API keys, `.env` contents or email addresses of real users.** Report security problems privately as described in [SECURITY.md](SECURITY.md).
- **Pull requests:** keep them focused, include tests, and make sure `pytest` and `ruff` pass.
