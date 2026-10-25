"""Ride-out: an import that has nothing durable yet keeps its worker through the shutdown grace.

`HandoffGate` is the one place that decides whether an import leaves a shutting-down worker now.
Two invariants hold it up: the activity's `Heartbeater` runs on the event loop while the source runs
on its own thread, so an import that rides out keeps heartbeating and never counts as a zombie; and
the deadline stays below the SDK's graceful shutdown timeout, which cancels activities, and below the
pod's `terminationGracePeriodSeconds`.
"""

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from structlog.types import FilteringBoundLogger
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.shutdown import ShutdownMonitor

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.preemption import ShutdownStopwatch

# Covers the gap to the next item or safe point, the result flush, and the SDK's cancellation of
# activities once the graceful shutdown timeout passes. A grace period shorter than this gives a
# deadline of zero, so the import hands off at once.
# Per-schema rollout flag. Off, every hand-off follows the legacy rule.
IMPORT_RIDE_OUT_FLAG = "warehouse-import-ride-out"
RIDE_OUT_GRACE_MARGIN_SECONDS = 900.0
# An execution younger than this restarts for nearly free, so it leaves the worker at once and the
# pod keeps draining fast. Shorter than `NON_RESUMABLE_HANDOFF_MAX_ATTEMPT_AGE` on purpose: that one
# decides whether a run may hand off at all, this one only whether it is worth holding the worker.
RIDE_OUT_MIN_EXECUTION_AGE_SECONDS = 120.0


@frozen
class RideOutConfig:
    grace_seconds: float
    # How long a run that could hand off sooner may hold the worker; the grace minus the margin bounds
    # it too.
    max_seconds: float

    def deadline_seconds_after_shutdown(self, *, restarts_from_scratch: bool) -> float:
        before_grace_ends = max(self.grace_seconds - RIDE_OUT_GRACE_MARGIN_SECONDS, 0.0)
        if restarts_from_scratch:
            return before_grace_ends
        return min(before_grace_ends, self.max_seconds)


class DurableProgress:
    """What this execution has made durable, shared by the event loop and the source thread."""

    def __init__(self, *, carry_over_counts: bool = True) -> None:
        self._lock = threading.Lock()
        self._reasons: list[str] = []
        # A staged carry-over value is progress only when the next execution reads it.
        self._carry_over_counts = carry_over_counts
        self._handoff_reason: str | None = None

    def mark(self, reason: str) -> None:
        if reason == "carry_over_staged" and not self._carry_over_counts:
            return
        with self._lock:
            if reason not in self._reasons:
                self._reasons.append(reason)

    @property
    def has_progress(self) -> bool:
        with self._lock:
            return bool(self._reasons)

    @property
    def reasons(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._reasons)

    @property
    def handoff_reason(self) -> str | None:
        return self._handoff_reason

    def record_handoff_reason(self, reason: str) -> None:
        """Keep the first reason: an abandoned source thread can still ask the gate after a preemption."""
        with self._lock:
            if self._handoff_reason is None:
                self._handoff_reason = reason


def activity_execution_age_seconds() -> float | None:
    if not activity.in_activity():
        return None
    return (datetime.now(UTC) - activity.info().started_time).total_seconds()


class HandoffGate:
    """Decides whether the import leaves a shutting-down worker now.

    Every observer of the shutdown asks the gate: the item loop, the safe point handler on the
    source thread, the source's own waits, and the preemptor. With `config` None the gate is today's
    behaviour, which `legacy_wants_handoff` provides.
    """

    def __init__(
        self,
        *,
        shutdown_monitor: ShutdownMonitor,
        stopwatch: "ShutdownStopwatch",
        progress: DurableProgress,
        config: RideOutConfig | None,
        legacy_wants_handoff: Callable[[], bool],
        logger: FilteringBoundLogger,
        restarts_from_scratch: Callable[[], bool] = lambda: False,
        execution_age_seconds: Callable[[], float | None] = activity_execution_age_seconds,
    ) -> None:
        self._shutdown_monitor = shutdown_monitor
        self._stopwatch = stopwatch
        self._progress = progress
        self._config = config
        self._legacy_wants_handoff = legacy_wants_handoff
        self._logger = logger
        self._restarts_from_scratch = restarts_from_scratch
        self._execution_age_seconds = execution_age_seconds
        self._lock = threading.Lock()
        self._logged_handoff = False
        self.rode_out = False

    @property
    def ride_out_enabled(self) -> bool:
        return self._config is not None

    def should_hand_off_now(self) -> bool:
        if not self._shutdown_monitor.is_worker_shutdown():
            return False
        # The stopwatch's own callback runs on the event loop; the source thread can see the
        # shutdown before it.
        self._stopwatch.start()
        if self._config is None:
            return self._decide("legacy", self._legacy_wants_handoff())
        early_reason = self._reason_to_leave_before_the_deadline()
        if early_reason is not None:
            return self._decide(early_reason, True)
        return self._decide("deadline", self.seconds_until_deadline() <= 0.0)

    def may_hand_off(self) -> bool:
        """Whether the run may leave the worker here, with the shutdown left to the monitor.

        The item loop and the safe point ask this and then let
        `ShutdownMonitor.raise_if_is_worker_shutdown` have the last word, as the pipeline always
        has. With the ride-out off that is the legacy decision alone: reading the shutdown flag
        here first would be the same in production and a different thing to every caller that
        drives the shutdown through the monitor.
        """
        if self._config is not None:
            return self.should_hand_off_now()
        if not self._legacy_wants_handoff():
            return False
        # The stopwatch for the reason, not the monitor: it is set once the shutdown callback has
        # run, and reading it costs the monitor nothing.
        if self._stopwatch.elapsed_seconds() is not None:
            self._progress.record_handoff_reason("legacy")
        return True

    def seconds_until_deadline(self) -> float:
        """How long the preemptor must still wait for the source before it hands off. Zero when the
        gate would hand off at once."""
        if self._config is None or self._reason_to_leave_before_the_deadline() is not None:
            return 0.0
        elapsed = self._stopwatch.elapsed_seconds() or 0.0
        deadline = self._config.deadline_seconds_after_shutdown(restarts_from_scratch=self._restarts_from_scratch())
        return max(deadline - elapsed, 0.0)

    def leave_reason(self) -> str:
        """Why the gate lets the import leave now: `progress`, `young`, or the `deadline`."""
        return self._reason_to_leave_before_the_deadline() or "deadline"

    def record_preemption(self, reason: str) -> None:
        self._progress.record_handoff_reason(f"preempted_{reason}")

    def raise_if_should_hand_off(self) -> None:
        if self.may_hand_off():
            self._shutdown_monitor.raise_if_is_worker_shutdown()

    def _reason_to_leave_before_the_deadline(self) -> str | None:
        if self._progress.has_progress:
            return "progress"
        age = self._execution_age_seconds()
        if age is not None and age < RIDE_OUT_MIN_EXECUTION_AGE_SECONDS:
            return "young"
        return None

    def _decide(self, reason: str, hand_off: bool) -> bool:
        if not hand_off:
            if self._config is None:
                return False
            with self._lock:
                first_time = not self.rode_out
                self.rode_out = True
            if first_time:
                self._logger.info(
                    "Worker is shutting down and the import has no durable progress yet, riding out the grace period",
                    deadline_seconds=round(self.seconds_until_deadline(), 1),
                    execution_age_seconds=round(self._execution_age_seconds() or 0.0, 1),
                )
            return False
        self._progress.record_handoff_reason(reason)
        with self._lock:
            log_it = self.rode_out and not self._logged_handoff
            self._logged_handoff = True
        if log_it:
            self._logger.info(
                "Handing the import off after riding out the shutdown",
                handoff_reason=reason,
                seconds_since_shutdown=round(self._stopwatch.elapsed_seconds() or 0.0, 1),
                progress=list(self._progress.reasons),
            )
        return True
