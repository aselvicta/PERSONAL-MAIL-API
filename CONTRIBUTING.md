# Contributing to Personal Mail API

Thanks for helping! This project aims to stay **small, secure and easy to self-host**.
Please read the [core principles](#scope) before proposing large features.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
docker compose up -d db
alembic upgrade head
pytest
```

## Making changes

- **Database changes** need an Alembic migration:
  `alembic revision --autogenerate -m "describe change"`. Review the generated
  file by hand. `tests/test_database.py` fails if models and migrations drift apart.
- **New endpoints** belong in `app/api/v1/`. Business logic belongs in
  `app/services/`, and only `app/services/resend_service.py` may import the Resend SDK.
- **Tests:** every change needs tests. Never send real email from tests;
  use the `fake_resend` fixture.
- **Style:** `ruff check .` and `ruff format .` must pass.

## Pull request checklist

- [ ] Focused on one change, with a clear description of *why*
- [ ] Tests added or updated; `pytest` passes
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] Migration included if models changed
- [ ] README / `.env.example` updated for new settings or endpoints
- [ ] No secrets, real email addresses or personal data in code, tests or fixtures

## Reporting issues

Open a GitHub issue with steps to reproduce, the expected and actual behaviour,
and your version (`GET /health`). Redact API keys, tokens and `.env` values.
For security issues, follow [SECURITY.md](SECURITY.md) instead.

## Scope

In scope: reliability, security, documentation, templates, integration examples.
Out of scope by design: a web dashboard, billing, additional email providers,
Redis, queues or microservices. Please open a discussion before working on
anything in that list.
