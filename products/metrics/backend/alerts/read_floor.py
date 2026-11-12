"""The latest instant each metrics alert has read, so a check never reads behind its last verdict.

The instant a check reads moves back when its ingestion read changes: a failed checkpoint read
falls back to the newest point, which is later, and the next checkpoint read comes back earlier.
A breach that started between the two instants then reads as recovery. A check whose instant is
behind its configuration's floor records nothing, so it stays due and reads once ingestion passes
the floor.

The floor lives in Redis, one sorted set per team scored by epoch seconds. Losing it costs only the
protection, so a Redis error is logged and the batch runs without a floor.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from redis import Redis

from posthog import redis

logger = structlog.get_logger(__name__)

# Far past the longest rewind, which a checkpoint more than 5 minutes old bounds, so a floor that
# matters is never pruned.
_RETENTION: Final = timedelta(days=1)
# The batch spends its time budget on queries, so the shared client's long default timeout on a
# stalled Redis would push the activity past its deadline and lose every verdict. One second is far
# above a healthy call, and a call that runs out of it costs only the floor.
_REDIS_TIMEOUT_SECONDS: Final = 1.0


def _client() -> Redis:
    return redis.get_client(socket_timeout=_REDIS_TIMEOUT_SECONDS, socket_connect_timeout=_REDIS_TIMEOUT_SECONDS)


def _key(team_id: int) -> str:
    return f"alerts:platform:metrics:read_floor:{team_id}"


def read_floors(team_id: int, configuration_ids: Sequence[str]) -> dict[str, datetime]:
    """Each configuration's floor, leaving out configurations without one."""
    if not configuration_ids:
        return {}
    try:
        scores = _client().zmscore(_key(team_id), list(configuration_ids))
    except Exception:
        logger.exception("Failed to read metrics alert read floors", team_id=team_id)
        return {}
    return {
        configuration_id: datetime.fromtimestamp(score, UTC)
        for configuration_id, score in zip(configuration_ids, scores)
        if score is not None
    }


def raise_read_floors(team_id: int, reads: Mapping[str, datetime], *, now: datetime) -> None:
    """Raise each configuration's floor to the instant it read. A floor never moves back."""
    if not reads:
        return
    key = _key(team_id)
    try:
        pipeline = _client().pipeline(transaction=False)
        pipeline.zadd(key, {configuration_id: at.timestamp() for configuration_id, at in reads.items()}, gt=True)
        pipeline.zremrangebyscore(key, "-inf", (now - _RETENTION).timestamp())
        pipeline.expire(key, _RETENTION)
        pipeline.execute()
    except Exception:
        logger.exception("Failed to raise metrics alert read floors", team_id=team_id)
