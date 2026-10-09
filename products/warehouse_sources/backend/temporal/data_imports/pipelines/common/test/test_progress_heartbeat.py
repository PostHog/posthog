import re
import asyncio
import threading

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.progress_heartbeat import (
    ACTION_HEARTBEATS_STOPPED,
    ACTION_REPORTED,
    NoProgressDetector,
    NoProgressLimits,
    ProgressAwareHeartbeater,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.progress import (
    BATCH_WRITTEN,
    CHECKPOINT_STAGED,
    RETRY_WAIT,
    SAFE_POINT,
    SOURCE_ITEM,
    SOURCE_REQUEST,
    ImportProgress,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.progress_heartbeat"

LIMIT = 3600.0
FIRST_ITEM_LIMIT = 8 * 3600.0


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _detector(clock: _Clock, *, stop_heartbeats: bool) -> tuple[NoProgressDetector, MagicMock]:
    logger = MagicMock()
    detector = NoProgressDetector(
        progress=ImportProgress(clock=clock),
        limits=NoProgressLimits(seconds=LIMIT, before_first_item_seconds=FIRST_ITEM_LIMIT),
        stop_heartbeats=stop_heartbeats,
        logger=logger,
    )
    detector.source_type = "Postgres"
    return detector, logger


def _warnings(logger: MagicMock) -> list[dict]:
    return [call.kwargs for call in logger.warning.call_args_list]


@pytest.mark.parametrize(
    "item_seen,quiet_seconds,expect_heartbeat",
    [
        pytest.param(True, LIMIT, True, id="at_the_limit"),
        pytest.param(True, LIMIT + 1, False, id="past_the_limit"),
        # One query can run for hours before its first row. The attempt must survive that.
        pytest.param(False, LIMIT + 1, True, id="slow_first_row_past_the_usual_limit"),
        pytest.param(False, FIRST_ITEM_LIMIT, True, id="slow_first_row_at_its_limit"),
        pytest.param(False, FIRST_ITEM_LIMIT + 1, False, id="no_first_row_past_its_limit"),
    ],
)
def test_heartbeats_stop_only_past_the_limit_that_applies(
    item_seen: bool, quiet_seconds: float, expect_heartbeat: bool
) -> None:
    clock = _Clock()
    detector, logger = _detector(clock, stop_heartbeats=True)
    if item_seen:
        detector.progress.record(SOURCE_ITEM)

    clock.now = quiet_seconds

    assert detector.should_heartbeat() is expect_heartbeat
    assert detector.progress.is_stalled is (not expect_heartbeat)
    assert len(_warnings(logger)) == (0 if expect_heartbeat else 1)


@pytest.mark.parametrize(
    "kind", [SOURCE_ITEM, BATCH_WRITTEN, SAFE_POINT, CHECKPOINT_STAGED, SOURCE_REQUEST, RETRY_WAIT]
)
def test_each_kind_of_progress_restarts_the_limit(kind: str) -> None:
    clock = _Clock()
    detector, logger = _detector(clock, stop_heartbeats=True)
    detector.progress.record(SOURCE_ITEM)

    for _ in range(3):
        clock.now += LIMIT - 1
        detector.progress.record(kind)
        assert detector.should_heartbeat() is True

    clock.now += LIMIT + 1
    assert detector.should_heartbeat() is False
    assert _warnings(logger)[0]["last_progress_kind"] == kind


def test_stopped_heartbeats_do_not_start_again_when_the_source_returns() -> None:
    clock = _Clock()
    detector, logger = _detector(clock, stop_heartbeats=True)
    detector.progress.record(SOURCE_ITEM)
    clock.now = LIMIT + 1
    assert detector.should_heartbeat() is False

    detector.progress.record(SOURCE_ITEM)

    assert detector.should_heartbeat() is False
    assert len(_warnings(logger)) == 1


def test_report_only_mode_keeps_the_heartbeat_and_reports_each_gap_once() -> None:
    clock = _Clock()
    detector, logger = _detector(clock, stop_heartbeats=False)
    detector.progress.record(SOURCE_ITEM)

    with (
        patch(f"{_MODULE}.activity") as activity,
        patch(f"{_MODULE}.get_import_no_progress_metric") as metric,
    ):
        activity.in_activity.return_value = True
        clock.now = LIMIT + 1
        first_gap = [detector.should_heartbeat(), detector.should_heartbeat()]
        detector.progress.record(SOURCE_ITEM)
        after_progress = detector.should_heartbeat()
        clock.now += LIMIT + 1
        second_gap = detector.should_heartbeat()

    assert first_gap == [True, True]
    assert after_progress is True
    assert second_gap is True
    assert detector.progress.is_stalled is False
    assert [call.args for call in metric.call_args_list] == [("Postgres", ACTION_REPORTED)] * 2
    assert [warning["action"] for warning in _warnings(logger)] == [ACTION_REPORTED] * 2


def test_the_report_names_where_the_source_thread_is_blocked_and_no_local_values() -> None:
    clock = _Clock()
    detector, logger = _detector(clock, stop_heartbeats=True)
    release = threading.Event()
    blocked = threading.Event()

    def call_that_never_returns(api_key: str) -> None:
        blocked.set()
        release.wait()

    thread = threading.Thread(
        target=detector.progress.watched(call_that_never_returns), args=("secret-value",), name="source-thread"
    )
    thread.start()
    try:
        assert blocked.wait(5)
        clock.now = FIRST_ITEM_LIMIT + 1
        assert detector.should_heartbeat() is False
    finally:
        release.set()
        thread.join(5)

    report = _warnings(logger)[0]
    frames = report["blocked_thread_frames"]["source-thread"]
    assert report["source_type"] == "Postgres"
    assert report["action"] == ACTION_HEARTBEATS_STOPPED
    assert report["seconds_since_progress"] == FIRST_ITEM_LIMIT + 1
    assert any(frame.endswith("in call_that_never_returns") for frame in frames)
    assert all(re.fullmatch(r".+:\d+ in \S+", frame) for frame in frames)
    assert "secret-value" not in repr(report)
    # The thread is watched only for the length of the call.
    assert detector.progress.blocked_thread_frames() == {}


@pytest.mark.asyncio
async def test_the_heartbeater_stops_at_a_stall_and_runs_the_stall_callbacks_once() -> None:
    clock = _Clock()
    detector, _ = _detector(clock, stop_heartbeats=True)
    detector.progress.record(SOURCE_ITEM)
    callback_ran = threading.Event()
    callback_calls: list[int] = []

    def callback() -> None:
        callback_calls.append(1)
        callback_ran.set()

    detector.progress.on_stall(callback)
    heartbeater = ProgressAwareHeartbeater(detector)

    async def turns(count: int) -> None:
        for _ in range(count):
            await asyncio.sleep(0)

    with patch(f"{_MODULE}.activity") as activity:
        activity.in_activity.return_value = False
        task = asyncio.create_task(heartbeater._heartbeat_forever(0))
        try:
            await turns(10)
            beats_while_healthy = activity.heartbeat.call_count
            last_details = activity.heartbeat.call_args.args[-1]

            clock.now = LIMIT + 1
            await turns(5)
            assert await asyncio.to_thread(callback_ran.wait, 5)
            beats_at_stall = activity.heartbeat.call_count
            detector.progress.record(SOURCE_ITEM)
            await turns(10)
            beats_after_stall = activity.heartbeat.call_count
        finally:
            task.cancel()
            await asyncio.wait([task])

    assert beats_while_healthy > 0
    assert last_details["progress"] == SOURCE_ITEM
    assert {"host", "ts", "seconds_since_progress"} <= set(last_details)
    assert beats_after_stall == beats_at_stall
    assert callback_calls == [1]
