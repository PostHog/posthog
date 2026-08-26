import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from django.conf import settings

import redis
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

LOCK_KEY_PREFIX = "v3_pipeline_lock"
# Holder metadata lives in a second key because the lock value must stay a bare
# run-id token — every release path compares it byte-for-byte.
LOCK_META_KEY_PREFIX = "v3_pipeline_lock_meta"
LOCK_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days, matching max workflow duration

# Atomic check-and-delete: prevents a race where workflow A's expired lock is
# acquired by workflow B, then A's delayed consumer releases B's lock.
# Replaceable with DELEX once we upgrade to Redis >= 8.4.
# Meta is deleted in the same script so it can't outlive its lock; readers must
# still ignore mismatched-run_id meta (old pods release without deleting it).
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    redis.call("del", KEYS[2])
    return redis.call("del", KEYS[1])
end
return 0
"""


def _lock_key(team_id: int, schema_id: str) -> str:
    return f"{LOCK_KEY_PREFIX}:{team_id}:{schema_id}"


def _lock_meta_key(team_id: int, schema_id: str) -> str:
    return f"{LOCK_META_KEY_PREFIX}:{team_id}:{schema_id}"


@retry(
    retry=retry_if_exception_type((redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.1, max=1),
    reraise=True,
)
def _connect_and_ping(redis_client: redis.Redis) -> None:
    redis_client.ping()


@contextmanager
def _get_redis_client() -> Generator[redis.Redis | None]:
    # The acquire/release activities run with a single Temporal attempt (see
    # external_data_job.py), so a bare DNS/connection blip here has no outer retry
    # and would skip the whole scheduled sync run. Absorb a few quick retries before
    # falling back to the fail-closed/fail-silent behavior callers rely on.
    redis_client = None
    try:
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for warehouse pipelines: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis_client = get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        _connect_and_ping(redis_client)
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


def write_v3_pipeline_lock_meta(team_id: int, schema_id: str, run_id: str, workflow_id: str) -> None:
    """Write the companion metadata for the current lock holder. Best-effort: never raises."""
    with _get_redis_client() as client:
        if client is None:
            return

        try:
            payload = json.dumps(
                {
                    "run_id": run_id,
                    "workflow_id": workflow_id,
                    "acquired_at": datetime.now(UTC).isoformat(),
                }
            )
            client.set(_lock_meta_key(team_id, schema_id), payload, ex=LOCK_TTL_SECONDS)
        except Exception as e:
            logger.warning("v3_pipeline_lock_meta_write_error", error=str(e), team_id=team_id, schema_id=schema_id)
            capture_exception(e)


def get_v3_pipeline_lock_meta(team_id: int, schema_id: str) -> dict[str, Any] | None:
    """Read the companion lock metadata; None when absent, unparseable, or Redis is down.
    Can be stale (not atomic with the lock) — callers must check run_id matches the holder."""
    with _get_redis_client() as client:
        if client is None:
            return None

        try:
            raw = client.get(_lock_meta_key(team_id, schema_id))
            if raw is None:
                return None
            parsed = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            if not isinstance(parsed, dict):
                return None
            return parsed
        except Exception as e:
            logger.warning("v3_pipeline_lock_meta_read_error", error=str(e), team_id=team_id, schema_id=schema_id)
            capture_exception(e)
            return None


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
            result = client.eval(
                _RELEASE_LOCK_SCRIPT, 2, _lock_key(team_id, schema_id), _lock_meta_key(team_id, schema_id), token
            )
            return bool(result)
        except Exception as e:
            logger.warning("v3_pipeline_lock_release_error", error=str(e), team_id=team_id, schema_id=schema_id)
            capture_exception(e)
            return False
