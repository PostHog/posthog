from typing import Any, cast

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.preemption import ShutdownStopwatch
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.ride_out import (
    DurableProgress,
    HandoffGate,
    RideOutConfig,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Monitor:
    def __init__(self, shutting_down: bool, shutdown_age: float | None = None) -> None:
        self.shutting_down = shutting_down
        self.shutdown_age = shutdown_age

    def run_on_shutdown(self, callback: Any) -> None:
        pass

    def is_worker_shutdown(self) -> bool:
        return self.shutting_down

    def seconds_since_shutdown(self) -> float | None:
        return self.shutdown_age

    def raise_if_is_worker_shutdown(self) -> None:
        if self.shutting_down:
            raise RuntimeError("worker shutting down")


def _gate(
    *,
    shutting_down: bool = True,
    ride_out: bool = True,
    progress: bool = False,
    age: float | None = 600.0,
    legacy: bool = True,
    restarts_from_scratch: bool = False,
    shutdown_age: float | None = None,
) -> tuple[HandoffGate, _Clock, DurableProgress]:
    clock = _Clock()
    monitor = _Monitor(shutting_down, shutdown_age)
    durable = DurableProgress()
    if progress:
        durable.mark("resume_commit")
    gate = HandoffGate(
        shutdown_monitor=cast(Any, monitor),
        stopwatch=ShutdownStopwatch(cast(Any, monitor), clock=clock),
        progress=durable,
        config=RideOutConfig(grace_seconds=7200.0, max_seconds=3600.0) if ride_out else None,
        legacy_wants_handoff=lambda: legacy,
        logger=MagicMock(),
        restarts_from_scratch=lambda: restarts_from_scratch,
        execution_age_seconds=lambda: age,
    )
    return gate, clock, durable


@pytest.mark.parametrize(
    "kwargs,elapsed,expected",
    [
        pytest.param({"shutting_down": False}, 0.0, (False, None), id="worker_running"),
        pytest.param({"ride_out": False, "legacy": True}, 0.0, (True, "legacy"), id="kill_switch_off_legacy_hands_off"),
        pytest.param({"ride_out": False, "legacy": False}, 7200.0, (False, None), id="kill_switch_off_legacy_waits"),
        pytest.param({"progress": True}, 0.0, (True, "progress"), id="durable_progress_hands_off_at_once"),
        pytest.param({"age": 10.0}, 0.0, (True, "young"), id="young_execution_hands_off_at_once"),
        pytest.param({}, 3599.0, (False, None), id="no_progress_rides_out_before_the_deadline"),
        pytest.param({}, 3600.0, (True, "deadline"), id="no_progress_hands_off_at_the_deadline"),
        pytest.param({"age": None}, 0.0, (False, None), id="unknown_age_rides_out"),
        # A run that restarts from scratch either way keeps the whole grace period, not the ride-out cap.
        pytest.param({"restarts_from_scratch": True}, 6299.0, (False, None), id="from_scratch_waits_past_the_cap"),
        pytest.param(
            {"restarts_from_scratch": True}, 6300.0, (True, "deadline"), id="from_scratch_leaves_before_grace_ends"
        ),
    ],
)
def test_the_gate_hands_off_only_when_a_restart_loses_nothing(
    kwargs: dict[str, Any], elapsed: float, expected: tuple[bool, str | None]
) -> None:
    gate, clock, progress = _gate(**kwargs)

    gate.should_hand_off_now()
    clock.now = elapsed
    hands_off = gate.should_hand_off_now()

    assert (hands_off, progress.handoff_reason) == expected


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        pytest.param({}, 3500.0, id="no_progress"),
        pytest.param({"progress": True}, 0.0, id="progress"),
        pytest.param({"age": 10.0}, 0.0, id="young"),
        pytest.param({"restarts_from_scratch": True}, 6200.0, id="from_scratch"),
    ],
)
def test_the_preemptor_waits_exactly_as_long_as_the_gate_would(kwargs: dict[str, Any], expected: float) -> None:
    gate, clock, _ = _gate(**kwargs)
    gate.should_hand_off_now()
    clock.now = 100.0

    assert gate.seconds_until_deadline() == expected


def test_a_gate_opened_after_the_shutdown_counts_its_deadline_from_the_shutdown() -> None:
    # A source setup that runs past the shutdown builds the pipeline, and so the stopwatch, after
    # the monitor's callbacks already ran. The deadline must still land inside the grace period.
    gate, clock, _ = _gate(restarts_from_scratch=True, shutdown_age=1200.0)

    # The first question starts the stopwatch, backdated to the shutdown 1200 s ago.
    assert gate.should_hand_off_now() is False

    clock.now = 6300.0 - 1200.0 - 1.0
    assert gate.should_hand_off_now() is False

    clock.now = 6300.0 - 1200.0
    assert gate.should_hand_off_now() is True


def test_a_staged_carry_over_value_counts_as_progress_only_when_the_next_execution_reads_it() -> None:
    counted, ignored = DurableProgress(carry_over_counts=True), DurableProgress(carry_over_counts=False)
    counted.mark("carry_over_staged")
    ignored.mark("carry_over_staged")
    assert (counted.has_progress, ignored.has_progress) == (True, False)


def test_the_first_handoff_reason_sticks() -> None:
    # An abandoned source thread can still ask the gate after a preemption; its answer must not
    # overwrite why the run really left.
    gate, clock, progress = _gate()
    gate.should_hand_off_now()
    gate.record_preemption("deadline")
    clock.now = 7200.0

    assert gate.should_hand_off_now() is True
    assert progress.handoff_reason == "preempted_deadline"


def test_progress_that_lands_during_a_ride_out_ends_it() -> None:
    gate, clock, progress = _gate()
    assert gate.should_hand_off_now() is False
    clock.now = 100.0

    progress.mark("carry_over_staged")

    assert gate.should_hand_off_now() is True
    assert gate.seconds_until_deadline() == 0.0
    assert progress.handoff_reason == "progress"
    assert gate.rode_out is True


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        # With the ride-out off the monitor still owns the shutdown flag, so the hand-off point is
        # reached whether or not the worker is shutting down yet.
        pytest.param({"ride_out": False, "shutting_down": False}, True, id="kill_switch_off_asks_the_monitor"),
        pytest.param(
            {"ride_out": False, "shutting_down": False, "legacy": False}, False, id="kill_switch_off_run_waits"
        ),
        pytest.param({"shutting_down": False}, False, id="ride_out_on_reads_the_flag"),
        pytest.param({"progress": True}, True, id="ride_out_on_hands_off_with_progress"),
    ],
)
def test_the_handoff_point_leaves_the_shutdown_flag_to_the_monitor(kwargs: dict[str, Any], expected: bool) -> None:
    gate, _, _ = _gate(**kwargs)

    assert gate.may_hand_off() is expected


def test_the_legacy_handoff_check_asks_the_monitor_to_raise() -> None:
    # Today's behaviour, which the kill switch keeps: the check asks the monitor to raise instead of
    # deciding on its flag first, so a monitor whose raise is what reports the shutdown still works.
    monitor = MagicMock()
    monitor.is_worker_shutdown.return_value = False
    monitor.raise_if_is_worker_shutdown.side_effect = RuntimeError("worker shutting down")
    gate = HandoffGate(
        shutdown_monitor=cast(Any, monitor),
        stopwatch=ShutdownStopwatch(cast(Any, monitor), clock=_Clock()),
        progress=DurableProgress(),
        config=None,
        legacy_wants_handoff=lambda: True,
        logger=MagicMock(),
    )

    with pytest.raises(RuntimeError, match="worker shutting down"):
        gate.raise_if_should_hand_off()

    # Not even to decide: a caller that counts the checks must see the same calls it always did.
    assert monitor.is_worker_shutdown.call_count == 0


def test_raise_if_should_hand_off_raises_through_the_monitor_only_at_a_hand_off() -> None:
    gate, clock, _ = _gate()
    gate.raise_if_should_hand_off()

    clock.now = 3600.0
    with pytest.raises(RuntimeError, match="worker shutting down"):
        gate.raise_if_should_hand_off()


@pytest.mark.parametrize(
    "grace,max_seconds,restarts_from_scratch,expected",
    [
        pytest.param(7200.0, 3600.0, False, 3600.0, id="max_below_grace"),
        pytest.param(7200.0, 3600.0, True, 6300.0, id="from_scratch_ignores_max"),
        pytest.param(1500.0, 3600.0, False, 600.0, id="grace_minus_margin_below_max"),
        pytest.param(300.0, 3600.0, False, 0.0, id="grace_shorter_than_the_margin"),
    ],
)
def test_the_deadline_stays_below_the_grace_period(
    grace: float, max_seconds: float, restarts_from_scratch: bool, expected: float
) -> None:
    config = RideOutConfig(grace_seconds=grace, max_seconds=max_seconds)
    assert config.deadline_seconds_after_shutdown(restarts_from_scratch=restarts_from_scratch) == expected
