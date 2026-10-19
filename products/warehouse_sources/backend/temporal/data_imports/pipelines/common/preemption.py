"""Preemption: the pipeline stops waiting for a source that does not hand off at a worker shutdown.

The pipeline sees a shutdown only when the source yields an item or reaches a safe point. A source
that is inside one long call does neither, so the run holds its worker until the call returns.
`SourcePreemptor` waits for the next item and for the shutdown at the same time. After a shutdown
it gives the source a quiet period to hand off in the usual way, and then it raises
`SourcePreemptedError` from the event loop and leaves the source behind.
"""

import time
import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterable
from typing import Any, TypeVar

from structlog.types import FilteringBoundLogger
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.shutdown import ShutdownMonitor, WorkerShuttingDownError

from products.warehouse_sources.backend.temporal.data_imports.metrics import (
    get_import_not_preempted_metric,
    get_import_preempted_metric,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.abandonable_iterate import (
    AbandonableSourcePuller,
    PulledItem,
)

T = TypeVar("T")


@frozen
class PreemptionConfig:
    quiet_period_seconds: float
    # Whether the next attempt of an incremental run reads the value this attempt records.
    watermark_carry_over_enabled: bool


@frozen
class PreemptionDecision:
    eligible: bool
    # A metric label: why the run can continue on another worker, or why it cannot.
    reason: str


class SourcePreemptedError(WorkerShuttingDownError):
    """The pipeline stopped waiting for the source because the worker is shutting down."""

    @classmethod
    def build(cls) -> "SourcePreemptedError":
        if activity.in_activity():
            return cls.from_activity_context()
        return cls("unknown", "unknown", "unknown", 1, None, None)


class ShutdownStopwatch:
    """Measures the time since the worker started to shut down."""

    def __init__(self, shutdown_monitor: ShutdownMonitor, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._started_at: float | None = None
        shutdown_monitor.run_on_shutdown(self.start)

    def start(self) -> None:
        if self._started_at is None:
            self._started_at = self._clock()

    def elapsed_seconds(self) -> float | None:
        return None if self._started_at is None else self._clock() - self._started_at


class SourcePreemptor:
    def __init__(
        self,
        *,
        config: PreemptionConfig,
        shutdown_monitor: ShutdownMonitor,
        stopwatch: ShutdownStopwatch,
        decide: Callable[[], PreemptionDecision],
        fence_source: Callable[[], Awaitable[bool]],
        source_type: str,
        logger: FilteringBoundLogger,
    ) -> None:
        self._config = config
        self._shutdown_monitor = shutdown_monitor
        self._stopwatch = stopwatch
        self._decide = decide
        self._fence_source = fence_source
        self._source_type = source_type
        self._logger = logger
        self._decision: PreemptionDecision | None = None
        self._quiet_period_extension = 0.0

    async def iterate(self, items: Iterable[T] | AsyncIterable[T]) -> AsyncIterator[T]:
        """Yield the items of the source. Raises `SourcePreemptedError` when it preempts the source.

        Close this generator when the loop over it ends for any reason. The close is what stops
        the thread of the source.
        """
        puller: AbandonableSourcePuller[T] = AbandonableSourcePuller(items)
        shutdown_wait = asyncio.ensure_future(self._shutdown_monitor.wait_for_worker_shutdown())
        abandon = False
        try:
            while True:
                pull = puller.pull()
                await self._wait_for_item_or_preempt(pull, shutdown_wait)
                has_value, item = pull.result()
                if not has_value:
                    return
                assert item is not None
                yield item
        except SourcePreemptedError:
            abandon = True
            raise
        finally:
            shutdown_wait.cancel()
            await puller.stop(abandon=abandon)

    async def _wait_for_item_or_preempt(
        self, pull: "asyncio.Future[PulledItem[T]]", shutdown_wait: "asyncio.Future[None]"
    ) -> None:
        while not pull.done():
            if not (shutdown_wait.done() or self._shutdown_monitor.is_worker_shutdown()):
                either: set[asyncio.Future[Any]] = {pull, shutdown_wait}
                await asyncio.wait(either, return_when=asyncio.FIRST_COMPLETED)
                continue

            self._stopwatch.start()
            decision = await self._decision_at_shutdown()
            if not decision.eligible:
                await asyncio.wait({pull})
                return

            elapsed = self._stopwatch.elapsed_seconds() or 0.0
            remaining = self._config.quiet_period_seconds + self._quiet_period_extension - elapsed
            if remaining > 0:
                # An item or a safe point in this time hands the run off in the usual way.
                await asyncio.wait({pull}, timeout=remaining)
                continue

            if not await self._fence_source():
                # The source is in the middle of a write of its resume state. A hand-off now could
                # let that write land after the next attempt starts.
                self._quiet_period_extension += self._config.quiet_period_seconds
                await self._logger.awarning(
                    "Could not stop the writes of the source, waiting another quiet period before preemption",
                    quiet_period_seconds=self._config.quiet_period_seconds,
                )
                continue

            # The source can no longer store resume state, so the run must leave this worker now,
            # also when an item arrived during the fence. The next attempt reads that item again.
            if activity.in_activity():
                get_import_preempted_metric(self._source_type, decision.reason).add(1)
            await self._logger.ainfo(
                "Preempting the import because the source did not hand off in the quiet period",
                preemption_reason=decision.reason,
                quiet_period_seconds=self._config.quiet_period_seconds,
                seconds_since_shutdown=round(self._stopwatch.elapsed_seconds() or 0.0, 1),
            )
            raise SourcePreemptedError.build()

    async def _decision_at_shutdown(self) -> PreemptionDecision:
        # Decided once, at the shutdown. A run that was young then stays eligible for the whole
        # quiet period.
        if self._decision is None:
            self._decision = self._decide()
            if self._decision.eligible:
                await self._logger.ainfo(
                    "Worker is shutting down, the source has a quiet period to hand off before preemption",
                    preemption_reason=self._decision.reason,
                    quiet_period_seconds=self._config.quiet_period_seconds,
                )
            else:
                if activity.in_activity():
                    get_import_not_preempted_metric(self._source_type, self._decision.reason).add(1)
                await self._logger.ainfo(
                    "Not preempting the import at worker shutdown",
                    not_preempted_reason=self._decision.reason,
                )
        return self._decision
