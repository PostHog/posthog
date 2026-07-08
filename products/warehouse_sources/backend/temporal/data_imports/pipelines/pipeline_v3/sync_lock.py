from collections.abc import Generator
from contextlib import contextmanager

from django.conf import settings

import redis
import structlog

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

LOCK_KEY_PREFIX = "v3_pipeline_lock"
LOCK_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days, matching max workflow duration

# Atomic check-and-delete: prevents a race where workflow A's expired lock is
# acquired by workflow B, then A's delayed consumer releases B's lock.
# Replaceable with DELEX once we upgrade to Redis >= 8.4.
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


def _lock_key(team_id: int, schema_id: str) -> str:
    return f"{LOCK_KEY_PREFIX}:{team_id}:{schema_id}"


@contextmanager
def _get_redis_client() -> Generator[redis.Redis | None]:
    redis_client = None
    try:
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for warehouse pipelines: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis_client = get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        redis_client.ping()
    except Exception as e:
        logger.exception("redis_unavailable_for_v3_pipeline_lock", error=str(e))
        capture_exception(e)
        redis_client = None

    try:
        yield redis_client
    finally:
        pass


def acquire_v3_pipeline_lock(team_id: int, schema_id: str, token: str) -> bool:
    """Acquire an exclusive lock for a V3 pipeline run. Fail-closed on errors."""
    with _get_redis_client() as client:
        if client is None:
            logger.error(
                "v3_pipeline_lock_skip_redis_unavailable",
                team_id=team_id,
                schema_id=schema_id,
            )
            return False

        try:
            acquired = client.set(_lock_key(team_id, schema_id), token, nx=True, ex=LOCK_TTL_SECONDS)
            return bool(acquired)
        except Exception as e:
            logger.exception(
                "v3_pipeline_lock_acquire_error",
                error=str(e),
                team_id=team_id,
                schema_id=schema_id,
            )
            capture_exception(e)
            return False


def get_v3_pipeline_lock_holder(team_id: int, schema_id: str) -> str | None:
    """Return the token currently holding the lock, or None if unheld or Redis is unavailable."""
    with _get_redis_client() as client:
        if client is None:
            return None

        try:
            holder = client.get(_lock_key(team_id, schema_id))
            if holder is None:
                return None
            return holder.decode() if isinstance(holder, bytes) else str(holder)
        except Exception as e:
            logger.warning("v3_pipeline_lock_get_holder_error", error=str(e), team_id=team_id, schema_id=schema_id)
            capture_exception(e)
            return None


def release_v3_pipeline_lock(team_id: int, schema_id: str, token: str) -> bool:
    """Release the lock only if held by this token. Fail-silent on errors."""
    with _get_redis_client() as client:
        if client is None:
            return False

        try:
            result = client.eval(_RELEASE_LOCK_SCRIPT, 1, _lock_key(team_id, schema_id), token)
            return bool(result)
        except Exception as e:
            logger.warning("v3_pipeline_lock_release_error", error=str(e), team_id=team_id, schema_id=schema_id)
            capture_exception(e)
            return False
