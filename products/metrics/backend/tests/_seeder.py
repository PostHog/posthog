"""Test-only metric row seeder for the metrics4 chain.

Inserts rows into `metrics4_input` via `sync_execute` rather than driving the
OTLP pipe, so tests don't depend on capture-logs + metrics-ingestion-consumer
running. `metrics4_input` is the Null-engine table the Kafka MV writes to, so one
insert fans out through the same MVs production uses into the metrics4 tables
that HogQL reads.

The shape mirrors what `rust/capture-logs/src/metric_record.rs` emits — every
query-runner test (filters, group-by, rate, histogram_quantile) leans on this
to plant deterministic fixtures with specific labels and timestamps.
"""

from __future__ import annotations

import json
import math
import uuid
import struct
import hashlib
import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any

from posthog.clickhouse.client import sync_execute

# The metrics4 tables hardcode their TTL on the original expiry columns
# instead of going through `ttl_period()`, so the seeder has to keep its rows
# alive itself. A far-future expiry pins that independent of the wall clock.
_EXPIRY = dt.datetime(2200, 1, 1, tzinfo=dt.UTC)
_DEFAULT_NAN_BITS = struct.unpack("<Q", struct.pack("<d", math.nan))[0]


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
    fingerprints before it stamps the synthetic `posthog.original_timestamp` attribute
    on a skewed point, so that key is left out here too. It does NOT have to
    equal the Rust hash: the seeder owns both the series and its samples, so it
    only has to be stable per label-set.
    """
    identity_attributes = sorted((k, v) for k, v in attributes.items() if k != "posthog.original_timestamp")
    return _fingerprint(
        metric_name, metric_type, service_name, sorted(resource_attributes.items()), identity_attributes
    )


def truncate_metrics_tables() -> None:
    """Clear every table the seeder's inserts fan out into, so leftovers can't
    leak between tests."""
    for table in (
        "metrics4_samples",
        "metrics4_series",
        "metrics4_names",
        "metrics4_attributes",
    ):
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
    has_labels: bool = True,
) -> None:
    """Insert one `metrics4_input` row per `(timestamp, value)` point; the
    ingest MVs write the metrics4 samples, series, names and attribute rollups
    from it.

    Every point in one call is a sample of the *same* series, since the series
    identity (`service_name`, `metric_type`, both attribute maps) is fixed per
    call. Aggregations reduce each series to one value per bucket, so several
    points in one bucket collapse to the last one. Seed distinct series with
    separate calls.

    `labels` populates the per-data-point `attributes` map and `resource_labels`
    populates `resource_attributes`.

    Histogram inputs (`histogram_bounds`, `histogram_counts`) are passed
    through verbatim; only relevant when `metric_type='histogram'`.

    `has_labels=False` seeds samples the way capture sends them after the first
    labelled sample of a window: they write no `metric_series` row.
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
                "has_labels": has_labels,
                "unit": unit,
                "aggregation_temporality": aggregation_temporality,
                "is_monotonic": is_monotonic,
                "instrumentation_scope": "",
                "resource_attributes": resource_attributes,
                "attributes": attributes,
            }
        )

    _insert_input_rows(rows)


def _nan_bits(value: Any) -> int:
    """The bits of a NaN that JSON would turn into the default NaN, or 0 for any other value."""
    if not isinstance(value, float) or not math.isnan(value):
        return 0
    bits = struct.unpack("<Q", struct.pack("<d", value))[0]
    return 0 if bits == _DEFAULT_NAN_BITS else bits


def _insert_input_rows(rows: list[dict[str, Any]]) -> None:
    if not any(_nan_bits(row["value"]) for row in rows):
        payload = "\n".join(json.dumps(row) for row in rows)
        sync_execute(f"INSERT INTO metrics4_input FORMAT JSONEachRow {payload}")
        return
    # JSON has no way to write the bits of a NaN, such as a Prometheus stale marker,
    # so they travel as an integer and become the value again in ClickHouse.
    columns = sync_execute(
        "SELECT name, type FROM system.columns WHERE database = currentDatabase() AND table = 'metrics4_input'"
    )
    structure = ", ".join(f"{name} {column_type}" for name, column_type in columns)
    payload = "\n".join(
        json.dumps({**row, "value": 0.0, "value_bits": bits} if (bits := _nan_bits(row["value"])) else row)
        for row in rows
    )
    sync_execute(
        "INSERT INTO metrics4_input SELECT * EXCEPT value_bits REPLACE "
        "(if(value_bits = 0, value, reinterpretAsFloat64(value_bits)) AS value) "
        "FROM format(JSONEachRow, %(structure)s, %(payload)s)",
        {"structure": f"{structure}, value_bits UInt64", "payload": payload},
    )


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
