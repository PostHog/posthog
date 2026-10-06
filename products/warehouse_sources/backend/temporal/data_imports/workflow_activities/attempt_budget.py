import asyncio
from types import TracebackType
from typing import Self

from django.conf import settings

from redis import exceptions as redis_exceptions
from redis.asyncio import Redis
from structlog.types import FilteringBoundLogger
from temporalio.exceptions import ApplicationError

from posthog.redis import get_async_client
from posthog.temporal.common.activity_context import current_activity_attempt
from posthog.temporal.common.errors import NonReportableApplicationError
from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    BillingLimitsWillBeReachedException,
)
from products.warehouse_sources.backend.temporal.data_imports.retry_limits import RESUMABLE_IMPORT_DEADLINE
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException

# Reported when the attempts ran out and the last one left no error, which is what a worker that
# dies or stops heartbeating leaves behind.
ATTEMPTS_EXHAUSTED_ERROR_TYPE = "ImportAttemptsExhaustedError"

# An expired count charges every earlier hand-off as a failure, so it must outlive the import.
HANDOFF_COUNT_TTL_SECONDS = int(RESUMABLE_IMPORT_DEADLINE.total_seconds()) + 24 * 60 * 60

# The count is read before the activity heartbeats, so the read must fit in the heartbeat timeout.
REDIS_TIMEOUT_SECONDS = 10

# Temporal already stops on these: the retry policy names the first two, the last carries a flag.
_ERRORS_TEMPORAL_STOPS_ON = (NonRetryableException, BillingLimitsWillBeReachedException, ApplicationError)


class FailedAttemptBudget:
    """Caps the failed attempts of an import whose Temporal retry policy has no attempt cap.

    Temporal cannot exempt an attempt from `maximum_attempts`, so a hand-off to another worker would
    use up the cap of an import that continues from its saved cursor. The policy sets no cap and this
    class counts instead: failed attempts are the earlier attempts minus the hand-offs in Redis.
    A hand-off that Redis did not record counts as a failure, so the cap holds without Redis.
    """

    def __init__(self, *, team_id: int, run_id: str, limit: int | None, logger: FilteringBoundLogger) -> None:
        self._key = f"posthog:data_warehouse:import_worker_handoffs:{team_id}:{run_id}"
        self._limit = limit
        self._logger = logger
        self._failed_before: int | None = None
        self._attempt_can_resume = False

    def mark_attempt_resumable(self) -> None:
        """Only a hand-off from an attempt that saves a cursor is free: any other redoes the read."""
        self._attempt_can_resume = True

    async def __aenter__(self) -> Self:
        if self._limit is None:
            return self

        attempt = current_activity_attempt()
        if attempt == 1:
            self._failed_before = 0
            return self

        handoffs = await self._read_handoffs()
        if handoffs is None:
            return self

        self._failed_before = attempt - 1 - handoffs
        await self._logger.ainfo(
            "Import attempt accounting",
            attempt=attempt,
            worker_handoffs=handoffs,
            failed_attempts=self._failed_before,
            failed_attempt_limit=self._limit,
        )
        if self._failed_before >= self._limit:
            raise NonReportableApplicationError(
                f"The import stopped after {self._failed_before} attempts that ended without a result",
                type=ATTEMPTS_EXHAUSTED_ERROR_TYPE,
                non_retryable=True,
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._limit is None or not isinstance(exc, Exception) or isinstance(exc, _ERRORS_TEMPORAL_STOPS_ON):
            return
        if isinstance(exc, WorkerShuttingDownError) and self._attempt_can_resume and await self._record_handoff():
            return
        # An unread count leaves this attempt unjudged. The next attempt reads it again.
        if self._failed_before is None or self._failed_before + 1 < self._limit:
            return

        # The workflow gets the type and message it gets when Temporal exhausts `maximum_attempts`.
        raise NonReportableApplicationError(str(exc), type=type(exc).__name__, non_retryable=True) from exc

    async def _read_handoffs(self) -> int | None:
        if not _redis_configured():
            return 0
        try:
            async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
                recorded = await _redis().get(self._key)
        except (redis_exceptions.RedisError, TimeoutError) as e:
            await self._logger.awarning("Could not read the worker hand-off count for this import", error=str(e))
            return None
        return int(recorded) if recorded else 0

    async def _record_handoff(self) -> bool:
        if not _redis_configured():
            return False
        try:
            async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
                pipeline = _redis().pipeline()
                pipeline.incr(self._key)
                pipeline.expire(self._key, HANDOFF_COUNT_TTL_SECONDS)
                await pipeline.execute()
        except (redis_exceptions.RedisError, TimeoutError) as e:
            await self._logger.awarning("Could not record a worker hand-off for this import", error=str(e))
            return False
        return True


def _redis_configured() -> bool:
    return bool(settings.DATA_WAREHOUSE_REDIS_HOST and settings.DATA_WAREHOUSE_REDIS_PORT)


def _redis() -> Redis:
    return get_async_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
