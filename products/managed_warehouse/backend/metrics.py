import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import posthoganalytics
from posthoganalytics.metrics_capture import PostHogMetrics

MetricAttributes = Mapping[str, str | int | float | bool]


def _should_record() -> bool:
    # Replay suppression only matters inside a Temporal workflow, and being in one implies
    # temporalio is already imported. Gating on that keeps the SDK off django.setup()'s import
    # path, which this module sits on via models.py -> model_observability.
    if "temporalio" not in sys.modules:
        return True

    from temporalio import workflow  # noqa: PLC0415 — keeps the Temporal SDK off the django.setup() import path

    return not (workflow.in_workflow() and workflow.unsafe.is_replaying())


def _metrics() -> PostHogMetrics | None:
    client = posthoganalytics.default_client
    return client.metrics if client is not None else None


def record_counter(
    name: str,
    value: int,
    attributes: MetricAttributes,
    *,
    unit: str | None = None,
) -> None:
    if not _should_record():
        return
    metrics = _metrics()
    if metrics is not None:
        metrics.count(name, value, unit=unit, attributes=dict(attributes))


def record_histogram(
    name: str,
    value: float,
    attributes: MetricAttributes,
    *,
    unit: str,
) -> None:
    if not _should_record():
        return
    metrics = _metrics()
    if metrics is not None:
        metrics.histogram(name, value, unit=unit, attributes=dict(attributes))


def record_gauge(
    name: str,
    value: float,
    attributes: MetricAttributes,
    *,
    unit: str | None = None,
) -> None:
    if not _should_record():
        return
    metrics = _metrics()
    if metrics is not None:
        metrics.gauge(name, value, unit=unit, attributes=dict(attributes))


@contextmanager
def track_duckling_backfill(*, team_id: int, dataset: str, mode: str) -> Iterator[None]:
    attributes = {"team_id": str(team_id), "dataset": dataset, "mode": mode}
    record_counter(
        "warehouse.duckling.backfill.started",
        1,
        attributes,
    )
    started_at = time.perf_counter()
    status = "failed"
    try:
        yield
        status = "completed"
        record_gauge(
            "warehouse.duckling.backfill.last.success.timestamp",
            time.time(),
            attributes,
            unit="s",
        )
    finally:
        terminal_attributes = {**attributes, "status": status}
        record_counter(
            "warehouse.duckling.backfill.finished",
            1,
            terminal_attributes,
        )
        record_histogram(
            "warehouse.duckling.backfill.duration",
            time.perf_counter() - started_at,
            terminal_attributes,
            unit="s",
        )
        metrics = _metrics()
        if metrics is not None:
            metrics.flush()


def record_duckling_backfill_workload(
    *,
    team_id: int,
    dataset: str,
    mode: str,
    files_registered: int,
    partitions_exported: int,
) -> None:
    attributes = {"team_id": str(team_id), "dataset": dataset, "mode": mode}
    record_histogram(
        "warehouse.duckling.backfill.files.registered",
        float(files_registered),
        attributes,
        unit="file",
    )
    record_histogram(
        "warehouse.duckling.backfill.partitions.exported",
        float(partitions_exported),
        attributes,
        unit="partition",
    )
