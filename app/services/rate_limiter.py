"""PostgreSQL-backed fixed-window rate limiting (no Redis required).

Each check is one ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING count``
statement. It is atomic across processes and workers, so limits hold when the
app runs more than one worker or instance. Expired buckets are pruned now and
then.

The limiter commits its own work, so a hit counts even if the request
later fails. Otherwise failing requests could be retried without limit.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import RateLimitExceededError
from app.models.rate_limit import RateLimitBucket

_PRUNE_PROBABILITY = 0.01


@dataclass(frozen=True, slots=True)
class RateLimit:
    key: str
    limit: int
    window_seconds: int


class RateLimiter:
    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._enabled = settings.RATE_LIMIT_ENABLED

    def hit(self, *limits: RateLimit) -> None:
        """Count one request against every limit. Raises when any is exceeded."""
        if not self._enabled:
            return
        now = datetime.now(UTC)
        retry_after = 0
        for rl in limits:
            epoch = int(now.timestamp())
            window_start_ts = epoch - (epoch % rl.window_seconds)
            window_start = datetime.fromtimestamp(window_start_ts, UTC)
            expires_at = window_start + timedelta(seconds=rl.window_seconds)

            stmt = (
                insert(RateLimitBucket)
                .values(key=rl.key, window_start=window_start, count=1, expires_at=expires_at)
                .on_conflict_do_update(
                    index_elements=[RateLimitBucket.key, RateLimitBucket.window_start],
                    set_={"count": RateLimitBucket.count + 1},
                )
                .returning(RateLimitBucket.count)
            )
            count = self._db.execute(stmt).scalar_one()
            if count > rl.limit:
                retry_after = max(retry_after, math.ceil((expires_at - now).total_seconds()))

        if random.random() < _PRUNE_PROBABILITY:  # noqa: S311 (not security-sensitive)
            self._db.execute(delete(RateLimitBucket).where(RateLimitBucket.expires_at < now))
        self._db.commit()

        if retry_after:
            raise RateLimitExceededError(headers={"Retry-After": str(max(retry_after, 1))})
