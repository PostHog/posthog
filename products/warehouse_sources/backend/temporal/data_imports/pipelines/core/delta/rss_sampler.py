"""A process RSS sampler that measures the real peak of each deltalite upsert.

The governor predicts an upsert's peak before it runs; this measures it while it runs. One daemon
thread reads ``/proc/self/statm`` at a fixed interval while at least one upsert window is open,
and every open window keeps the highest value it saw.
"""

from __future__ import annotations

import resource
import threading
import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

MB = 1024 * 1024

_PAGE_SIZE = resource.getpagesize()


def psutil_rss_mb() -> float | None:
    try:
        import psutil

        return psutil.Process().memory_info().rss / MB
    except Exception:  # noqa: BLE001 - no psutil: the caller treats None as unknown
        return None


def read_process_rss_mb() -> float | None:
    """This process's resident set in MB: one small ``/proc`` read on Linux, psutil elsewhere."""
    try:
        with open("/proc/self/statm", "rb") as f:
            return int(f.read().split()[1]) * _PAGE_SIZE / MB
    except (OSError, ValueError, IndexError):
        return psutil_rss_mb()


# Identity equality: two windows with the same readings are still different upserts.
@dataclass(frozen=False, eq=False)
class RssWindow:
    """What the sampler saw while one upsert ran. RSS is process-wide, so concurrent upserts share it."""

    start_mb: float | None = None
    peak_mb: float | None = None
    #: Most upserts that had a window open at the same time as this one, itself included.
    max_concurrent: int = 1
    samples: int = 0
    #: Windows that share a group count once in ``max_concurrent``, so one caller's nested windows
    #: do not read as concurrent work.
    group: object | None = field(default=None, repr=False)

    def observe(self, rss_mb: float | None) -> None:
        if rss_mb is None:
            return
        self.samples += 1
        rss_mb = round(rss_mb, 1)
        self.peak_mb = rss_mb if self.peak_mb is None else max(self.peak_mb, rss_mb)

    @property
    def delta_mb(self) -> float | None:
        if self.start_mb is None or self.peak_mb is None:
            return None
        return round(self.peak_mb - self.start_mb, 1)


class RssPeakSampler:
    """One daemon thread that samples process RSS while at least one upsert window is open.

    The thread starts with the first open window and exits once the last one closes, so an idle
    process runs no sampler. Each sample is one ``/proc/self/statm`` read, shared by every open
    window. The peak is process-wide: with other upserts in flight it covers their memory too, so
    ``RssWindow.max_concurrent`` says when a window ran alone. glibc reuses memory it kept from
    earlier upserts without growing RSS, so a delta can also read low after a larger upsert.
    """

    def __init__(self, interval_s: float, read_rss_mb: Callable[[], float | None] = read_process_rss_mb) -> None:
        self._interval_s = interval_s
        self._read = read_rss_mb
        self._lock = threading.Lock()
        self._open: list[RssWindow] = []
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def _safe_read(self) -> float | None:
        try:
            return self._read()
        except Exception:  # noqa: BLE001 - a failed read is a missing sample, never an error
            return None

    def _run(self) -> None:
        me = threading.current_thread()
        try:
            while True:
                self._wake.wait(self._interval_s)
                rss_mb = self._safe_read()
                with self._lock:
                    self._wake.clear()
                    # Exit under the same lock that a new window checks, so a window that opens
                    # now either sees this thread still running or starts a new one.
                    if not self._open:
                        self._thread = None
                        return
                    for window in self._open:
                        window.observe(rss_mb)
        except BaseException:
            with self._lock:
                if self._thread is me:
                    self._thread = None
            raise

    @contextlib.contextmanager
    def window(self, group: object | None = None) -> Iterator[RssWindow]:
        start = self._safe_read()
        window = RssWindow(start_mb=round(start, 1) if start is not None else None, group=group)
        with self._lock:
            self._open.append(window)
            running = len({w.group if w.group is not None else w for w in self._open})
            for other in self._open:
                other.max_concurrent = max(other.max_concurrent, running)
                # A read is a sample for every open window, so an enclosing window keeps the peak
                # that a short inner window saw between two thread reads.
                other.observe(start)
            if self._thread is None:
                self._wake.clear()
                self._thread = threading.Thread(target=self._run, name="deltalite-rss-sampler", daemon=True)
                self._thread.start()
        try:
            yield window
        finally:
            end = self._safe_read()
            with self._lock:
                for other in self._open:
                    other.observe(end)
                self._open.remove(window)
                if not self._open:
                    self._wake.set()

    def thread(self) -> threading.Thread | None:
        """The running sampler thread, if any. Tests only."""
        with self._lock:
            return self._thread
