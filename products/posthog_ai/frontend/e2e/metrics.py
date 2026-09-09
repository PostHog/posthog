from __future__ import annotations

import time
import resource
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class ResourceMonitor:
    interval = 0.1

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.peak_used_bytes = 0
        self.total_bytes = 0
        self.stages: list[dict[str, str | float]] = []
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()

    def _sample(self) -> None:
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            fields = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in meminfo.read_text().splitlines()}
            self.total_bytes = fields["MemTotal"]
            self.peak_used_bytes = max(self.peak_used_bytes, self.total_bytes - fields["MemAvailable"])

    def _monitor(self) -> None:
        while not self.stopped.is_set():
            self._sample()
            self.stopped.wait(self.interval)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.monotonic()
        try:
            yield
        finally:
            self.stages.append({"name": name, "seconds": time.monotonic() - started})

    def finish(self) -> dict[str, float | int | list[dict[str, str | float]]]:
        self.stopped.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError("Resource monitor did not stop")
        self._sample()
        metrics: dict[str, float | int | list[dict[str, str | float]]] = {
            "runtime_seconds": time.monotonic() - self.started,
            "launcher_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "child_peak_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            "stages": self.stages,
        }
        if self.total_bytes:
            metrics.update(
                runner_sampled_peak_used_bytes=self.peak_used_bytes,
                runner_total_memory_bytes=self.total_bytes,
                memory_sample_interval_seconds=self.interval,
            )
        return metrics
