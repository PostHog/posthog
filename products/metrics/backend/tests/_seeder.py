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
import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any

from posthog.clickhouse.client import sync_execute


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
