"""A heartbeat that follows the progress of the import, not only the life of the event loop.

A source thread that is blocked in a call leaves the event loop free, so a heartbeat from a timer
continues for as long as the call blocks. Temporal then never times the attempt out, and nothing
ends the run. `ProgressAwareHeartbeater` asks a `NoProgressDetector` before each heartbeat. When
the attempt made no progress for longer than its limit, the detector reports it, and, when it is
told to, stops the heartbeats. Temporal then ends the attempt after the heartbeat timeout and
starts the next attempt on another worker.
"""

import time
import socket
import asyncio
import datetime as dt

from structlog.types import FilteringBoundLogger
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.heartbeat import LivenessHeartbeater

from products.warehouse_sources.backend.temporal.data_imports.metrics import get_import_no_progress_metric
from products.warehouse_sources.backend.temporal.data_imports.sources.common.progress import (
    ImportProgress,
    ProgressSnapshot,
)

ACTION_REPORTED = "reported"
ACTION_HEARTBEATS_STOPPED = "heartbeats_stopped"


@frozen
class NoProgressLimits:
    """How long an attempt can go without progress.

    The pipeline cannot tell a slow call from a blocked one, so both limits are much longer than
    the gaps of a healthy import.

    Before the first item, one call can run for hours and be healthy: a warehouse query that sorts
    or materializes its whole result before the first row, a count on a large view, a compaction
    of the destination table before extraction. So every attempt gets the longer limit until its
    source yields an item. A per-source declaration was the alternative. It needs each source to
    predict its own worst query, and the sources that are slow here are the ones that cannot.
    """

    seconds: float
    before_first_item_seconds: float

    def limit_for(self, snapshot: ProgressSnapshot) -> float:
        return self.seconds if snapshot.source_item_seen else self.before_first_item_seconds


class NoProgressDetector:
    def __init__(
        self,
        *,
        progress: ImportProgress,
        limits: NoProgressLimits,
        stop_heartbeats: bool,
        logger: FilteringBoundLogger,
    ) -> None:
        self.progress = progress
        # Set by the activity when it knows the source. The detector starts before that.
        self.source_type: str | None = None
        self._limits = limits
        self._stop_heartbeats = stop_heartbeats
        self._logger = logger
        self._reported = False

    def should_heartbeat(self) -> bool:
        if self.progress.is_stalled:
            return False

        snapshot = self.progress.snapshot()
        limit = self._limits.limit_for(snapshot)
        if snapshot.seconds_since_progress <= limit:
            if self._reported:
                # Only possible when the heartbeats continued. The length of the gap shows how far
                # the limit is from a healthy import.
                self._reported = False
                self._logger.info(
                    "The import makes progress again",
                    source_type=self.source_type,
                    progress_kind=snapshot.kind,
                )
            return True

        if self._reported:
            return True
        self._reported = True
        if self._stop_heartbeats:
            self.progress.mark_stalled()
        self._report(snapshot, limit)
        return not self._stop_heartbeats

    def _report(self, snapshot: ProgressSnapshot, limit: float) -> None:
        action = ACTION_HEARTBEATS_STOPPED if self._stop_heartbeats else ACTION_REPORTED
        if activity.in_activity():
            get_import_no_progress_metric(self.source_type, action).add(1)
        last_progress_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=snapshot.seconds_since_progress)
        self._logger.warning(
            "The import made no progress for longer than its limit",
            source_type=self.source_type,
            action=action,
            last_progress_kind=snapshot.kind,
            last_progress_at=last_progress_at.isoformat(timespec="seconds"),
            seconds_since_progress=round(snapshot.seconds_since_progress),
            limit_seconds=limit,
            source_item_seen=snapshot.source_item_seen,
            blocked_thread_frames=self.progress.blocked_thread_frames(),
        )


class ProgressAwareHeartbeater(LivenessHeartbeater):
    def __init__(self, detector: NoProgressDetector, factor: int = 120) -> None:
        super().__init__(factor=factor)
        self.detector = detector
        self._stall_handled = False

    async def _heartbeat_forever(self, delay: float) -> None:
        while True:
            await asyncio.sleep(delay)
            try:
                if not self.detector.should_heartbeat():
                    await self._handle_stall()
                    continue
                snapshot = self.detector.progress.snapshot()
                # The dict stays the last detail: the next attempt reads `host` and `ts` from it.
                activity.heartbeat(
                    *self.details,
                    {
                        "host": socket.gethostname(),
                        "ts": time.time(),
                        "progress": snapshot.kind,
                        "seconds_since_progress": round(snapshot.seconds_since_progress),
                    },
                )
                self.tracker.record_heartbeat()
            except Exception:
                self.logger.exception("Heartbeat failed")

    async def _handle_stall(self) -> None:
        if self._stall_handled:
            return
        self._stall_handled = True
        # A callback can wait for a lock that the thread of the source holds.
        errors = await asyncio.to_thread(self.detector.progress.run_stall_callbacks)
        for error in errors:
            self.logger.error("A stall callback of the import failed", exc_info=error)

    async def __aexit__(self, *args: object, **kwargs: object) -> None:
        if not self.detector.progress.is_stalled:
            await super().__aexit__(*args, **kwargs)
            return
        # The base class sends one more heartbeat when it exits. Temporal must not get it: the
        # attempt is over for the server, or will be when the heartbeat timeout ends.
        if self.heartbeat_task is not None:
            self.heartbeat_task.cancel()
        if self.heartbeat_on_shutdown_task is not None:
            self.heartbeat_on_shutdown_task.cancel()
        pending = [task for task in (self.heartbeat_task, self.heartbeat_on_shutdown_task) if task is not None]
        if pending:
            await asyncio.wait(pending)
        self.heartbeat_task = None
        self.heartbeat_on_shutdown_task = None
