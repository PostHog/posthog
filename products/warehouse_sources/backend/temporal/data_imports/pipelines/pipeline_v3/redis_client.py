import time
from collections.abc import Generator
from contextlib import contextmanager

from django.conf import settings

import redis
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

# One v3 batch opens the client several times, and each failed connect costs three attempts
# of REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS. A window several times that burst holds the cost
# to one dead connect and one report per window, and delays recovery by at most one window.
CONNECT_FAILURE_COOLDOWN_SECONDS = 30.0

_cooldown_until = 0.0


@retry(
    retry=retry_if_exception_type((redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.1, max=1),
    reraise=True,
)
def _connect_and_ping(redis_client: redis.Redis) -> None:
    redis_client.ping()


@contextmanager
def get_redis_client() -> Generator[redis.Redis | None]:
    """Yield a client for the warehouse Redis instance, or None when it is unreachable.

    Callers that hold the lock run with a single Temporal attempt (see
    external_data_job.py), so a bare DNS/connection blip has no outer retry and would
    skip the whole scheduled sync run. Absorb a few quick retries before falling back to
    the fail-closed/fail-silent behavior every caller relies on.
    """
    global _cooldown_until

    if time.monotonic() < _cooldown_until:
        yield None
        return

    redis_client: redis.Redis | None
    try:
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for warehouse pipelines: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis_client = get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        _connect_and_ping(redis_client)
    except Exception as e:
        _cooldown_until = time.monotonic() + CONNECT_FAILURE_COOLDOWN_SECONDS
        logger.exception("warehouse_pipeline_redis_unavailable", error=str(e))
        capture_exception(e)
        redis_client = None

    yield redis_client
