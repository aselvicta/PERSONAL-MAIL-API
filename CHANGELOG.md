# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-17

### Added
- Multi-project management with hashed, regenerable and revocable API keys.
- Administrator authentication (Argon2id + JWT) and a `create_admin` CLI.
- Public contact form endpoint with origin checks, honeypot, Turnstile and rate limits.
- Transactional email (raw or templated) and owner notification endpoints.
- Responsive HTML + plain-text templates: contact notification, contact
  acknowledgement, notification, welcome, password reset, email verification.
- Email logging and Resend webhook processing (Svix signature verification,
  idempotency, status precedence).
- PostgreSQL-backed rate limiting and daily quotas; request size limits.
- Supabase-ready database configuration, Alembic migrations, Docker image,
  docker-compose, Render blueprint, CI workflow.
- Next.js, React and Python integration examples.
