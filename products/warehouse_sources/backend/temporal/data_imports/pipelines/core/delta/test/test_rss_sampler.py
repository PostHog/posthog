import time
import threading
from pathlib import Path

import pytest
from unittest.mock import mock_open, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta import rss_sampler
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.rss_sampler import (
    MB,
    RssPeakSampler,
    RssWindow,
    read_process_rss_mb,
)

_THREAD_NAME = "deltalite-rss-sampler"


class _Readings:
    """Returns the queued readings in order, then repeats the last one. Counts the reads."""

    def __init__(self, *values: float | None) -> None:
        self._values = list(values)
        self._lock = threading.Lock()
        self.reads = 0

    def __call__(self) -> float | None:
        with self._lock:
            self.reads += 1
            return self._values.pop(0) if len(self._values) > 1 else self._values[0]


def _raise_oserror() -> float | None:
    raise OSError("gone")


def _wait_for(condition, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.001)


def _sampler_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == _THREAD_NAME]


def _stopped(sampler: RssPeakSampler, thread: threading.Thread | None) -> bool:
    assert thread is not None
    thread.join(timeout=5)
    return not thread.is_alive() and sampler.thread() is None


class TestRssPeakSampler:
    def test_window_keeps_the_start_and_the_highest_sample(self):
        readings = _Readings(100.0, 300.0, 200.0, 150.0)
        sampler = RssPeakSampler(0.001, read_rss_mb=readings)
        with sampler.window() as window:
            _wait_for(lambda: readings.reads >= 4)
        assert (window.start_mb, window.peak_mb, window.delta_mb) == (100.0, 300.0, 200.0)
        assert window.samples >= 4

    def test_thread_runs_only_while_a_window_is_open(self):
        sampler = RssPeakSampler(0.001, read_rss_mb=_Readings(1.0))
        assert sampler.thread() is None
        with sampler.window():
            first = sampler.thread()
            with sampler.window():
                # Overlapping windows share the one thread.
                assert sampler.thread() is first
            assert first is not None and first.is_alive()
        assert _stopped(sampler, first)

    def test_no_thread_leaks_over_many_windows(self):
        sampler = RssPeakSampler(0.001, read_rss_mb=_Readings(1.0))
        before = len(_sampler_threads())
        threads = []
        for _ in range(25):
            with sampler.window():
                threads.append(sampler.thread())
        for thread in threads:
            assert thread is not None
            thread.join(timeout=5)
        assert sampler.thread() is None
        assert len(_sampler_threads()) == before

    def test_a_long_interval_still_stops_at_once(self):
        # Closing the last window wakes the thread, so it never lingers for a full interval.
        sampler = RssPeakSampler(3600.0, read_rss_mb=_Readings(1.0))
        with sampler.window():
            thread = sampler.thread()
        started = time.monotonic()
        assert _stopped(sampler, thread)
        assert time.monotonic() - started < 5

    def test_concurrent_windows_report_the_overlap(self):
        sampler = RssPeakSampler(3600.0, read_rss_mb=_Readings(1.0))
        with sampler.window() as a:
            with sampler.window() as b:
                pass
            with sampler.window() as c:
                pass
        with sampler.window() as alone:
            pass
        assert (a.max_concurrent, b.max_concurrent, c.max_concurrent, alone.max_concurrent) == (2, 2, 2, 1)

    def test_window_closes_when_the_upsert_raises(self):
        sampler = RssPeakSampler(0.001, read_rss_mb=_Readings(10.0, 20.0))
        with pytest.raises(RuntimeError):
            with sampler.window():
                thread = sampler.thread()
                raise RuntimeError("upsert failed")
        assert _stopped(sampler, thread)

    @parameterized.expand(
        [
            ("raises", _raise_oserror),
            ("unknown", lambda: None),
        ]
    )
    def test_failed_reads_are_missing_samples(self, _name, reader):
        sampler = RssPeakSampler(0.001, read_rss_mb=reader)
        with sampler.window() as window:
            thread = sampler.thread()
            time.sleep(0.01)
        assert (window.start_mb, window.peak_mb, window.delta_mb, window.samples) == (None, None, None, 0)
        assert _stopped(sampler, thread)


class TestRssWindow:
    @parameterized.expand(
        [
            ("rises", 100.0, [150.0, 120.0], 150.0, 50.0),
            ("never_rises", 100.0, [90.0], 100.0, 0.0),
            ("no_start", None, [90.0], 90.0, None),
            ("rounds_to_a_tenth", 100.04, [100.26], 100.3, 0.3),
        ]
    )
    def test_peak_and_delta(self, _name, start, samples, peak, delta):
        window = RssWindow(start_mb=round(start, 1) if start is not None else None)
        window.observe(start)
        for value in samples:
            window.observe(value)
        assert (window.peak_mb, window.delta_mb) == (peak, delta)


class TestReadProcessRss:
    def test_reads_resident_pages_from_statm(self):
        with patch("builtins.open", mock_open(read_data=b"5000 256 100 1 0 300 0\n")):
            assert read_process_rss_mb() == 256 * rss_sampler._PAGE_SIZE / MB

    def test_falls_back_to_psutil_without_proc(self):
        with (
            patch("builtins.open", side_effect=FileNotFoundError),
            patch.object(rss_sampler, "psutil_rss_mb", return_value=42.0),
        ):
            assert read_process_rss_mb() == 42.0

    @pytest.mark.skipif(not Path("/proc/self/statm").exists(), reason="needs Linux /proc")
    def test_reads_this_process(self):
        rss = read_process_rss_mb()
        assert rss is not None and rss > 0
