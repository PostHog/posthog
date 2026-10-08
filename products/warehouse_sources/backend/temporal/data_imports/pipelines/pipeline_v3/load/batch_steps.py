import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    BATCH_STEP_DURATION_SECONDS,
)

BatchStep = Literal[
    "job_load",
    "idempotency_check",
    "deliver",
    "parquet_read",
    "table_open",
    "table_refresh",
    "partition",
    "cdc_resolve",
    "schema_evolve",
    "ownership_check",
    "write",
    "mark_processed",
    "post_write",
]


class BatchStepTimer:
    """Wall-clock time of each step of one batch load, for the batch's log line and a histogram."""

    def __init__(self) -> None:
        self._seconds: dict[str, float] = {}

    @contextmanager
    def step(self, name: BatchStep) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            self._seconds[name] = self._seconds.get(name, 0.0) + elapsed
            BATCH_STEP_DURATION_SECONDS.labels(step=name).observe(elapsed)

    def log_fields(self) -> dict[str, int]:
        return {f"{name}_ms": round(seconds * 1000) for name, seconds in self._seconds.items()}
