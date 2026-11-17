# Architecture

Personal Mail API is a **modular monolith**: one FastAPI process, one
PostgreSQL database, one outbound email provider (Resend). There are no
queues, no Redis and no background workers.

```
 Portfolio ─┐                    ┌──────────────── Personal Mail API ────────────────┐
 CareerDocs ─┼── HTTPS (JSON) ──▶ │ api/      routing, auth dependencies, envelopes   │──▶ Resend (send)
 Safari AI ─┤                    │ services/ business rules, quotas, templates       │
 Others  ───┘                    │ models/   SQLAlchemy 2.0 ORM                      │──▶ Supabase PostgreSQL
                                 │ core/     config, security, errors, logging       │
 Resend webhooks ───────────────▶│ /api/v1/webhooks/resend (signed)                  │
                                 └───────────────────────────────────────────────────┘
```

## Layers

| Layer | Responsibility | May depend on |
|---|---|---|
| `app/api` | HTTP: routing, request/response schemas, auth dependencies | services, schemas, core |
| `app/services` | Business rules: permissions, quotas, sending, logging | models, core |
| `app/models` | ORM tables | database |
| `app/schemas` | Pydantic v2 request/response models | — |
| `app/core` | Settings, security primitives, exceptions, logging | — |
| `app/database` | Engine, session factory, declarative base | core |

Routers never talk to Resend directly; they call services. Only
`app/services/resend_service.py` imports the Resend SDK.

## Callers and credentials

| Caller | Credential | Endpoints |
|---|---|---|
| Browser contact forms | **Public** project slug + Origin check + optional Turnstile + rate limit + honeypot | `POST /api/v1/contact` |
| Application backends / serverless functions | **Private** project API key (`Authorization: Bearer pmk_...`) | `POST /api/v1/emails/send`, `POST /api/v1/notifications` |
| Administrator | JWT obtained from email + Argon2-hashed password | `/api/v1/auth/*`, `/api/v1/admin/projects/*` |
| Resend | Svix webhook signature | `POST /api/v1/webhooks/resend` |

Private API keys must never ship to a browser.

## Email status lifecycle

```
pending ──▶ accepted ──▶ sent ──▶ delivered
   │            │          ├────▶ delivery_delayed ──▶ delivered / bounced
   │            │          ├────▶ bounced
   │            │          └────▶ complained
   └──▶ failed (error_code: PROVIDER_REJECTED | PROVIDER_TIMEOUT | PROVIDER_UNAVAILABLE | ...)
```

`accepted` means Resend accepted the API request. It does **not** mean the
email reached an inbox. Only webhook events (`sent`, `delivered`, `bounced`,
...) move the status further.

## Database schema

All primary keys are UUIDs. All timestamps are `timestamptz`. Status columns
are `varchar` validated by Python enums, which avoids PostgreSQL enum
migration problems.

### administrators
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| email | varchar(320) | unique, stored lower-case |
| hashed_password | varchar(255) | Argon2id |
| is_active | bool | |
| created_at, updated_at | timestamptz | |

### projects
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| name | varchar(100) | |
| slug | varchar(64) | unique; the **public** identifier used by contact forms |
| description | text null | |
| recipient_email | varchar(320) | admin-configured; the public cannot change it |
| sender_name | varchar(100) null | falls back to `DEFAULT_FROM_NAME` |
| sender_email | varchar(320) null | must be on a Resend-verified domain; falls back to `DEFAULT_FROM_EMAIL` |
| allowed_origins | text[] | browser origins accepted by `/contact` |
| allowed_recipient_domains | text[] | empty means any domain (transactional only) |
| contact_enabled | bool | default true |
| transactional_enabled | bool | default **false**, so sending to arbitrary recipients must be turned on explicitly |
| notifications_enabled | bool | default true |
| acknowledgement_enabled | bool | default false; auto-reply to contact senders |
| turnstile_enabled | bool | default false |
| is_active | bool | |
| rate_limit | int | requests per minute for the project |
| daily_quota | int | maximum emails sent per day for the project |
| created_at, updated_at | timestamptz | |

### api_keys
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| project_id | uuid FK → projects, `ON DELETE CASCADE` | indexed |
| key_prefix | varchar(32) | e.g. `pmk_a1b2c3d4`, safe to display |
| key_hash | varchar(64) | unique; SHA-256 of the full key |
| is_active | bool | |
| created_at | timestamptz | |
| last_used_at | timestamptz null | |
| revoked_at | timestamptz null | |

API keys are 256-bit random secrets, so a fast SHA-256 hash with an indexed
equality lookup is appropriate. Argon2 is for low-entropy passwords only.

### contact_submissions
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| project_id | uuid FK, cascade | index `(project_id, created_at)` |
| sender_name, sender_email, subject | varchar | |
| message | text | |
| status | varchar(32) | `received`, `sent`, `failed` |
| resend_message_id | varchar(100) null | |
| created_at, updated_at | timestamptz | |

### email_logs
| column | type | notes |
|---|---|---|
| id | uuid PK | also used as the Resend idempotency key |
| project_id | uuid FK, cascade | index `(project_id, created_at)` |
| recipient | varchar(320) | |
| subject | varchar(255) | |
| email_type | varchar(32) | `contact_notification`, `contact_acknowledgement`, `transactional`, `notification` |
| provider | varchar(32) | always `resend` |
| resend_message_id | varchar(100) null | unique; webhooks find the log by this value |
| status | varchar(32) | see lifecycle above; indexed |
| error_code | varchar(64) null | machine-readable failure reason |
| error_message | text null | provider message, with secrets redacted |
| created_at, updated_at | timestamptz | |

### email_events
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| email_log_id | uuid FK null, cascade | null when the event references an unknown email |
| event_type | varchar(64) | e.g. `email.delivered` |
| provider_event_id | varchar(255) | **unique** (the Svix message id), which makes webhook processing idempotent |
| event_payload | jsonb | |
| created_at | timestamptz | |

### rate_limit_buckets
| column | type | notes |
|---|---|---|
| key | varchar(255) | PK part, e.g. `project:<id>:minute`, `contact:<project>:ip:<ip>` |
| window_start | timestamptz | PK part; start of the fixed window |
| count | int | incremented atomically with `INSERT ... ON CONFLICT DO UPDATE` |
| expires_at | timestamptz | indexed; expired rows are pruned opportunistically |

Atomic across workers and instances, with no Redis. The daily quota is counted
from `email_logs` through the `(project_id, created_at)` index.
