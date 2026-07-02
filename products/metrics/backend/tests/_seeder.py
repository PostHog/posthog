"""Test-only metric row seeder for `metrics1`.

Inserts rows directly via `sync_execute` rather than driving the OTLP pipe,
so tests don't depend on capture-logs + metrics-ingestion-consumer running.

The shape mirrors what `rust/capture-logs/src/metric_record.rs` emits — every
later query-runner PR (filters, group-by, rate, histogram_quantile) leans on
this to plant deterministic fixtures with specific labels and timestamps.
"""

from __future__ import annotations

import json
import uuid
import hashlib
import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any

from posthog.clickhouse.client import sync_execute


def _series_fingerprint(
    metric_name: str, service_name: str, resource_attributes: Mapping[str, str], attributes: Mapping[str, str]
) -> int:
    """A deterministic UInt64 fingerprint for the (metric, label-set) tuple.

    The seeder owns both the series and its samples, so this only has to be
    stable per label-set (distinct sets -> distinct fingerprints) — it does NOT
    have to equal ClickHouse's `cityHash64`, which the real ingest MV computes.
    """
    key = repr((metric_name, service_name, sorted(resource_attributes.items()), sorted(attributes.items())))
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")


def _attribute_map_str_with_type_tags(labels: Mapping[str, str]) -> dict[str, str]:
    """`attributes_map_str` stores keys with a trailing 5-char type tag (e.g.
    `container__str`), matching the Kafka MV's `concat(k, '__str')`. The
    ClickHouse table exposes a stripped ALIAS column `attributes` via
    `left(k, -5)`. The seeder accepts user-friendly names (`container`) and
    appends the `__str` tag so lookups via the ALIAS work as expected.
    """
    return {f"{key}__str": value for key, value in labels.items()}


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
) -> None:
    """Insert one row per `(timestamp, value)` point into `metrics1`.

    `labels` populates the per-data-point `attributes_map_str` map (with the
    `__str` type-tag suffix the schema expects). `resource_labels` populates
    `resource_attributes` directly — those are tag-free.

    Histogram inputs (`histogram_bounds`, `histogram_counts`) are passed
    through verbatim; only relevant when `metric_type='histogram'`.
    """
    attributes_map_str = _attribute_map_str_with_type_tags(labels or {})
    resource_attributes = dict(resource_labels or {})

    rows: list[dict[str, Any]] = []
    for timestamp, value in points:
        rows.append(
            {
                "uuid": str(uuid.uuid4()),
                "team_id": team_id,
                "trace_id": "",
                "span_id": "",
                "trace_flags": 0,
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
                "observed_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
                "service_name": service_name,
                "metric_name": metric_name,
                "metric_type": metric_type,
                "value": value,
                "count": 1,
                "histogram_bounds": histogram_bounds or [],
                "histogram_counts": histogram_counts or [],
                "unit": unit,
                "aggregation_temporality": aggregation_temporality,
                "is_monotonic": is_monotonic,
                "resource_attributes": resource_attributes,
                "instrumentation_scope": "",
                "attributes_map_str": attributes_map_str,
                "attributes_map_float": {},
            }
        )

    if not rows:
        return

    payload = "\n".join(json.dumps(row) for row in rows)
    sync_execute(f"INSERT INTO metrics1 FORMAT JSONEachRow {payload}")


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
) -> None:
    """Insert one `metric_samples` row per `(timestamp, value)` point plus the
    matching `metric_series` row, the way the ingest MVs split a metric.

    All points here share one label-set, so they share one `series_fingerprint`
    and one series row that the samples reference.
    """
    attributes = dict(attributes or {})
    resource_attributes = dict(resource_attributes or {})
    points = list(points)
    if not points:
        return

    fingerprint = _series_fingerprint(metric_name, service_name, resource_attributes, attributes)

    sample_rows: list[dict[str, Any]] = [
        {
            "team_id": team_id,
            "metric_name": metric_name,
            "series_fingerprint": fingerprint,
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "value": value,
            "trace_id": trace_id,
            "span_id": span_id,
            "trace_flags": 0,
        }
        for timestamp, value in points
    ]
    series_row = {
        "team_id": team_id,
        "metric_name": metric_name,
        "series_fingerprint": fingerprint,
        "metric_type": metric_type,
        "unit": unit,
        "service_name": service_name,
        "resource_attributes": resource_attributes,
        "attributes": attributes,
        "last_seen": max(ts for ts, _ in points).strftime("%Y-%m-%d %H:%M:%S.%f"),
    }

    sync_execute("INSERT INTO metric_samples1 FORMAT JSONEachRow " + "\n".join(json.dumps(r) for r in sample_rows))
    sync_execute("INSERT INTO metric_series1 FORMAT JSONEachRow " + json.dumps(series_row))
