# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Instead, use
GitHub's private vulnerability reporting (*Security → Report a vulnerability*)
on the repository. Include:

- a description of the issue and its impact
- steps to reproduce or a proof of concept
- affected version (`GET /health` → `data.version`)

You should get an acknowledgement within a few days. Fixes are released as
patch versions and credited in the changelog unless you prefer otherwise.

## Operator checklist

- Run with `APP_ENV=production`. Startup then refuses weak or missing secrets.
- Keep `JWT_SECRET_KEY`, `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET` and
  `DATABASE_URL` in your platform's secret store, never in git.
- Leave `transactional_enabled` off for projects that only need contact forms.
- Restrict `allowed_origins` and, where possible, `allowed_recipient_domains`.
- Rotate project keys with `POST /api/v1/admin/projects/{id}/api-keys` if one leaks.
- Set `TRUSTED_PROXY_COUNT` to match your proxy setup, or per-IP limits can be bypassed.
