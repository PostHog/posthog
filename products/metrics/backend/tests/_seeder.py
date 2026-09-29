"""Test-only metric row seeder for the metrics2 chain.

Inserts rows into `metrics2_input` via `sync_execute` rather than driving the
OTLP pipe, so tests don't depend on capture-logs + metrics-ingestion-consumer
running. `metrics2_input` is the Null-engine table the Kafka MV writes to, so one
insert fans out through the same MVs production uses: `metrics2` (data points),
`metric_series2` (labels, one row per series) and `metric_attributes2` (the
attribute rollups).

The shape mirrors what `rust/capture-logs/src/metric_record.rs` emits — every
query-runner test (filters, group-by, rate, histogram_quantile) leans on this
to plant deterministic fixtures with specific labels and timestamps.
"""

from __future__ import annotations

import json
import uuid
import hashlib
import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any

from posthog.clickhouse.client import sync_execute

# `metrics2` and `metric_series2` hardcode `TTL original_expiry_timestamp`
# instead of going through `ttl_period()`, so the seeder has to keep its rows
# alive itself. A far-future expiry pins that independent of the wall clock.
_EXPIRY = dt.datetime(2200, 1, 1, tzinfo=dt.UTC)


def _fingerprint(*parts: Any) -> int:
    key = repr(parts)
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")


def _series_fingerprint(
    metric_name: str,
    metric_type: str,
    service_name: str,
    resource_attributes: Mapping[str, str],
    attributes: Mapping[str, str],
) -> int:
    """A deterministic UInt64 fingerprint for the (metric, type, label-set) tuple.

    Same inputs as `compute_series_fingerprint` in capture-logs, so two seeded
    series collide exactly when the real ingest would merge them. Ingest
    fingerprints before it stamps the synthetic `$originalTimestamp` attribute
    on a skewed point, so that key is left out here too. It does NOT have to
    equal the Rust hash: the seeder owns both the series and its samples, so it
    only has to be stable per label-set.
    """
    identity_attributes = sorted((k, v) for k, v in attributes.items() if k != "$originalTimestamp")
    return _fingerprint(
        metric_name, metric_type, service_name, sorted(resource_attributes.items()), identity_attributes
    )


def truncate_metrics_tables() -> None:
    """Clear every table the seeder's inserts fan out into, so leftovers can't
    leak between tests."""
    for table in ("metrics2", "metric_series2", "metric_attributes2"):
        sync_execute(f"TRUNCATE TABLE IF EXISTS {table}")


def _format_timestamp(timestamp: dt.datetime) -> str:
    return timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")


def seed_metric(
    *,
    team_id: int,
    metric_name: str,
    points: Iterable[tuple[dt.datetime, float]],
    labels: Mapping[str, str] | None = None,
    resource_labels: Mapping[str, str] | None = None,
    metric_type: str = "gauge",
    service_name: str = "test-service",
    aggregation_temporality: str = "cumulative",
    is_monotonic: bool = False,
    histogram_bounds: list[float] | None = None,
    histogram_counts: list[int] | None = None,
    unit: str = "",
    trace_id: str = "",
    span_id: str = "",
    count: int = 1,
) -> None:
    """Insert one `metrics2_input` row per `(timestamp, value)` point; the
    ingest MVs write the `metrics2` rows, the `metric_series2` row and the
    `metric_attributes2` rollups from it.

    Every point in one call is a sample of the *same* series, since the series
    identity (`service_name`, `metric_type`, both attribute maps) is fixed per
    call. Aggregations reduce each series to one value per bucket, so several
    points in one bucket collapse to the last one. Seed distinct series with
    separate calls.

    `labels` populates the per-data-point `attributes` map and `resource_labels`
    populates `resource_attributes`.

    Histogram inputs (`histogram_bounds`, `histogram_counts`) are passed
    through verbatim; only relevant when `metric_type='histogram'`.
    """
    attributes = dict(labels or {})
    resource_attributes = dict(resource_labels or {})
    points = list(points)
    if not points:
        return

    fingerprint = _series_fingerprint(metric_name, metric_type, service_name, resource_attributes, attributes)
    resource_fingerprint = _fingerprint(sorted(resource_attributes.items()))

    rows: list[dict[str, Any]] = []
    for timestamp, value in points:
        rows.append(
            {
                "uuid": str(uuid.uuid4()),
                "team_id": team_id,
                "metric_name": metric_name,
                "series_fingerprint": fingerprint,
                "resource_fingerprint": resource_fingerprint,
                "timestamp": _format_timestamp(timestamp),
                "observed_timestamp": _format_timestamp(timestamp),
                "original_expiry_timestamp": _format_timestamp(_EXPIRY),
                "service_name": service_name,
                "metric_type": metric_type,
                "value": value,
                "count": count,
                "histogram_bounds": histogram_bounds or [],
                "histogram_counts": histogram_counts or [],
                "trace_id": trace_id,
                "span_id": span_id,
                "trace_flags": 0,
                "has_labels": True,
                "unit": unit,
                "aggregation_temporality": aggregation_temporality,
                "is_monotonic": is_monotonic,
                "instrumentation_scope": "",
                "resource_attributes": resource_attributes,
                "attributes": attributes,
            }
        )

    payload = "\n".join(json.dumps(row) for row in rows)
    sync_execute(f"INSERT INTO metrics2_input FORMAT JSONEachRow {payload}")


def seed_metric_event(
    *,
    team_id: int,
    metric_name: str,
    points: Iterable[tuple[dt.datetime, float]],
    metric_type: str = "sum",
    unit: str = "",
    service_name: str = "test-service",
    trace_id: str = "",
    span_id: str = "",
    attributes: Mapping[str, str] | None = None,
    resource_attributes: Mapping[str, str] | None = None,
    count: int = 1,
    aggregation_temporality: str = "cumulative",
    is_monotonic: bool = False,
    histogram_bounds: list[float] | None = None,
    histogram_counts: list[int] | None = None,
) -> None:
    """`seed_metric` under the sample-oriented names the Samples tests use:
    `attributes` / `resource_attributes` instead of `labels` / `resource_labels`,
    and a `sum` default type."""
    seed_metric(
        team_id=team_id,
        metric_name=metric_name,
        points=points,
        labels=attributes,
        resource_labels=resource_attributes,
        metric_type=metric_type,
        service_name=service_name,
        aggregation_temporality=aggregation_temporality,
        is_monotonic=is_monotonic,
        histogram_bounds=histogram_bounds,
        histogram_counts=histogram_counts,
        unit=unit,
        trace_id=trace_id,
        span_id=span_id,
        count=count,
    )
