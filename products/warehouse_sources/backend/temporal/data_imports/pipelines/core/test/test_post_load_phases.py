import time
import asyncio
import threading
from typing import Any

import pytest
from unittest.mock import MagicMock

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core import post_load_phases
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.rss_sampler import RssPeakSampler
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.post_load_phases import (
    MAX_PHASES,
    SUMMARY_EVENT,
    PostLoadPhaseRecorder,
    active_post_load_recorder,
    note_post_load_phase,
    post_load_phase,
    record_post_load_phases,
    recorded_phase,
)


class _FakeRss:
    """A settable RSS reading. Each window reads it once on open and once on close."""

    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self.value = value

    def __call__(self) -> float:
        with self._lock:
            return self.value


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _sampler(rss: _FakeRss) -> RssPeakSampler:
    # A long interval leaves only the open and close reads, so the fake RSS alone sets every peak.
    return RssPeakSampler(3600.0, read_rss_mb=rss)


def _summary(logger: MagicMock) -> dict[str, Any]:
    assert logger.info.call_count == 1
    assert logger.info.call_args.args == (SUMMARY_EVENT,)
    return logger.info.call_args.kwargs


def _by_name(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {phase["name"]: phase for phase in summary["phases"]}


class TestPostLoadPhaseRecorder:
    def test_phases_record_order_peak_delta_and_duration(self) -> None:
        rss = _FakeRss(1_000.0)
        clock = _FakeClock()
        recorder = PostLoadPhaseRecorder(_sampler(rss), clock=clock)
        recorder.start()

        with recorder.phase("compact"):
            clock.advance(2.0)
            rss.set(1_200.0)
        with recorder.phase("publish"):
            clock.advance(0.5)
            rss.set(1_500.0)

        summary = recorder.finish()

        assert summary["phase_names"] == ["compact", "publish"]
        phases = _by_name(summary)
        assert phases["publish"] == {
            "name": "publish",
            "duration_ms": 500,
            "rss_start_mb": 1_200.0,
            "peak_rss_mb": 1_500.0,
            "rss_delta_peak_mb": 300.0,
            "concurrent_windows_max": 1,
        }
        assert phases["compact"]["duration_ms"] == 2_000
        assert summary["total_duration_ms"] == 2_500
        assert summary["rss_start_mb"] == 1_000.0
        assert summary["peak_phase"] == "publish"

    def test_a_peak_between_reads_is_seen_by_the_sampler_thread(self) -> None:
        # The compact peak lasts only while the sampler thread reads it, as a real allocation spike does.
        rss = _FakeRss(1_000.0)
        sampler = RssPeakSampler(0.001, read_rss_mb=rss)
        recorder = PostLoadPhaseRecorder(sampler)
        recorder.start()
        with recorder.phase("compact"):
            rss.set(4_000.0)
            window = recorder.phases[0].window
            assert window is not None
            deadline = time.monotonic() + 5
            while window.peak_mb != 4_000.0:
                assert time.monotonic() < deadline, "timed out"
                time.sleep(0.001)
            rss.set(1_000.0)
        summary = recorder.finish()
        assert _by_name(summary)["compact"]["peak_rss_mb"] == 4_000.0
        assert summary["peak_phase"] == "compact"

    def test_nested_phases_name_their_parent_and_do_not_count_as_concurrent(self) -> None:
        rss = _FakeRss(1_000.0)
        recorder = PostLoadPhaseRecorder(_sampler(rss))
        recorder.start()

        with recorder.phase("delta_maintenance"):
            with recorder.phase("compact"):
                rss.set(3_000.0)
            with recorder.phase("vacuum"):
                rss.set(1_500.0)

        summary = recorder.finish()
        phases = _by_name(summary)

        assert summary["phase_names"] == ["delta_maintenance", "compact", "vacuum"]
        assert "parent" not in phases["delta_maintenance"]
        assert (phases["compact"]["parent"], phases["vacuum"]["parent"]) == ("delta_maintenance", "delta_maintenance")
        assert [phase["concurrent_windows_max"] for phase in summary["phases"]] == [1, 1, 1]
        assert phases["delta_maintenance"]["peak_rss_mb"] == 3_000.0
        # The parent holds its child's peak, so the culprit is the leaf.
        assert summary["peak_phase"] == "compact"

    def test_work_outside_the_recorder_counts_as_concurrent(self) -> None:
        sampler = _sampler(_FakeRss())
        recorder = PostLoadPhaseRecorder(sampler)
        recorder.start()

        with recorder.phase("register_table"):
            with sampler.window():
                pass

        assert _by_name(recorder.finish())["register_table"]["concurrent_windows_max"] == 2

    def test_overlapping_phases_close_in_any_order(self) -> None:
        recorder = PostLoadPhaseRecorder(_sampler(_FakeRss()))
        recorder.start()
        first = recorder.phase("copy_files")
        second = recorder.phase("remove_stale_files")
        first.__enter__()
        second.__enter__()
        first.__exit__(None, None, None)
        recorder.note(files_removed=3)
        second.__exit__(None, None, None)

        phases = _by_name(recorder.finish())

        assert phases["remove_stale_files"]["files_removed"] == 3
        assert all(phase["duration_ms"] is not None for phase in phases.values())

    def test_facts_attach_to_the_innermost_open_phase(self) -> None:
        recorder = PostLoadPhaseRecorder(_sampler(_FakeRss()))
        recorder.start()
        with recorder.phase("publish"):
            recorder.note(live_files=13_215)
            with recorder.phase("copy_files"):
                recorder.note(files_copied=1_567)
        recorder.note(outside=1)

        summary = recorder.finish()
        phases = _by_name(summary)

        assert phases["publish"]["live_files"] == 13_215
        assert phases["copy_files"]["files_copied"] == 1_567
        assert "files_copied" not in phases["publish"]
        assert summary["outside"] == 1

    def test_a_fact_cannot_overwrite_a_measured_field(self) -> None:
        recorder = PostLoadPhaseRecorder(None, clock=_FakeClock())
        with recorder.phase("compact"):
            recorder.note(duration_ms=-1, name="other")
        assert recorder.finish()["phases"][0] == {
            "name": "compact",
            "duration_ms": 0,
            "rss_start_mb": None,
            "peak_rss_mb": None,
            "rss_delta_peak_mb": None,
            "concurrent_windows_max": None,
        }

    def test_a_failed_phase_records_the_error_type_and_reraises(self) -> None:
        recorder = PostLoadPhaseRecorder(_sampler(_FakeRss()))
        with pytest.raises(OSError):
            with recorder.phase("copy_files"):
                raise OSError("S3 down")
        phase = recorder.finish()["phases"][0]
        assert (phase["error"], phase["duration_ms"] is not None) == ("OSError", True)

    def test_phases_past_the_cap_are_counted_not_listed(self) -> None:
        recorder = PostLoadPhaseRecorder(None)
        for _ in range(MAX_PHASES + 3):
            with recorder.phase("copy_files"):
                pass
        summary = recorder.finish()
        assert (len(summary["phases"]), summary["phases_dropped"]) == (MAX_PHASES, 3)

    def test_finish_closes_phases_left_open(self) -> None:
        sampler = _sampler(_FakeRss())
        recorder = PostLoadPhaseRecorder(sampler)
        recorder.start()
        recorder.phase("compact").__enter__()

        summary = recorder.finish()

        assert summary["phases"][0]["duration_ms"] is not None
        thread = sampler.thread()
        if thread is not None:
            thread.join(timeout=5)
        assert sampler.thread() is None


class TestRecordPostLoadPhases:
    @parameterized.expand([("sampling_on", True), ("sampling_off", False)])
    def test_one_summary_line_with_the_bound_ids(self, _name: str, sampling: bool) -> None:
        logger = MagicMock()
        sampler = _sampler(_FakeRss()) if sampling else None

        with record_post_load_phases(logger, sampler, team_id=2, resource_name="trades"):
            with post_load_phase("delta_maintenance"):
                pass
            with post_load_phase("publish"):
                pass

        summary = _summary(logger)
        assert summary["phase_names"] == ["delta_maintenance", "publish"]
        assert (summary["team_id"], summary["resource_name"], summary["outcome"]) == (2, "trades", "ok")
        assert summary["rss_sampling"] is sampling
        assert all(phase["duration_ms"] is not None for phase in summary["phases"])
        assert all((phase["peak_rss_mb"] is not None) is sampling for phase in summary["phases"])
        assert active_post_load_recorder() is None

    def test_the_line_is_logged_when_the_block_raises(self) -> None:
        logger = MagicMock()
        with pytest.raises(RuntimeError):
            with record_post_load_phases(logger, None):
                with post_load_phase("register_table"):
                    raise RuntimeError("chdb died")

        summary = _summary(logger)
        assert summary["outcome"] == "RuntimeError"
        assert summary["phases"][0]["error"] == "RuntimeError"

    @parameterized.expand(
        [
            ("sampler_window", "window"),
            ("log_call", "log"),
        ]
    )
    def test_a_recorder_failure_never_breaks_the_wrapped_code(self, _name: str, broken: str) -> None:
        logger = MagicMock()
        sampler: MagicMock | None = MagicMock(spec=RssPeakSampler)
        if broken == "window":
            assert sampler is not None
            sampler.window.side_effect = RuntimeError("sampler broke")
        else:
            sampler = None
            logger.info.side_effect = RuntimeError("logging broke")
        ran = []

        with record_post_load_phases(logger, sampler):
            with post_load_phase("publish"):
                note_post_load_phase(live_files=1)
                ran.append("publish")

        assert ran == ["publish"]

    def test_phase_helpers_are_no_ops_without_a_recorder(self) -> None:
        with post_load_phase("compact"):
            note_post_load_phase(files_added=1)
        assert active_post_load_recorder() is None

    def test_phases_inside_async_to_sync_and_decorated_coroutines_are_recorded(self) -> None:
        logger = MagicMock()

        @recorded_phase("register_table")
        async def register() -> str:
            note_post_load_phase(row_count=10)
            await asyncio.sleep(0)
            return "registered"

        async def post_load() -> str:
            with post_load_phase("publish"):
                await asyncio.sleep(0)
            return await register()

        with record_post_load_phases(logger, None):
            assert async_to_sync(post_load)() == "registered"

        summary = _summary(logger)
        assert summary["phase_names"] == ["publish", "register_table"]
        assert _by_name(summary)["register_table"]["row_count"] == 10

    def test_recorders_do_not_leak_between_runs(self) -> None:
        first, second = MagicMock(), MagicMock()
        with record_post_load_phases(first, None):
            with post_load_phase("compact"):
                pass
        with record_post_load_phases(second, None):
            with post_load_phase("publish"):
                pass
        assert (_summary(first)["phase_names"], _summary(second)["phase_names"]) == (["compact"], ["publish"])
        assert post_load_phases._ACTIVE.get() is None
