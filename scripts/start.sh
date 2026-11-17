#!/bin/sh
# Production entrypoint.
#
# 1. Apply database migrations ONCE, before any web worker starts. A PostgreSQL
#    advisory lock in migrations/env.py makes concurrent runs from several
#    instances safe. Set RUN_MIGRATIONS=false when migrations run as a separate
#    deployment step instead (for example Render's pre-deploy command).
# 2. Create/update the administrator from ADMIN_EMAIL / ADMIN_PASSWORD, if set.
# 3. Start uvicorn. It binds to $PORT (Render sets this).
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "Applying database migrations..."
  alembic upgrade head
fi

python scripts/bootstrap_admin.py

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --no-server-header \
  --timeout-graceful-shutdown 20
