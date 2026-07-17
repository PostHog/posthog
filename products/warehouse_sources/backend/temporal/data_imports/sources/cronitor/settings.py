from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://cronitor.io/api"

# The monitors list paginates with `page`/`pageSize`; the docs publish no maximum, so stay on a
# conservative size and stop on the first short page.
PAGE_SIZE = 50

# Metrics API constraints from the public docs: at most 50 monitor keys per request, and the
# start/end span must be between one hour and one year.
METRICS_MAX_MONITORS_PER_REQUEST = 50
METRICS_MIN_WINDOW_SECONDS = 3600
METRICS_MAX_LOOKBACK_SECONDS = 365 * 24 * 3600
# Chunk backfills into 30-day windows so a crash mid-backfill only re-fetches one window.
METRICS_WINDOW_SECONDS = 30 * 24 * 3600

# Metric fields verified against the public Metrics API docs. The API documents more (fail_count,
# complete_count, duration_p99, ...) but some may be plan-gated, so start with the core set.
METRICS_FIELDS = ("duration_p50", "duration_p90", "success_rate", "run_count")


@dataclass
class CronitorEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field to partition by. None when the endpoint has no reliably parseable timestamp.
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"


CRONITOR_ENDPOINTS: dict[str, CronitorEndpointConfig] = {
    "monitors": CronitorEndpointConfig(
        name="monitors",
        primary_keys=["key"],
        # The list has no updated-since/created-since filter, so it's full refresh only.
        partition_key="created",
    ),
    "invocations": CronitorEndpointConfig(
        name="invocations",
        # `series` links a run/complete telemetry pair, but the docs don't state its uniqueness
        # scope, so include the monitor key and start time to keep the key unique table-wide.
        primary_keys=["monitor_key", "series", "started_at"],
    ),
    "metrics": CronitorEndpointConfig(
        name="metrics",
        primary_keys=["monitor_key", "dimension", "stamp"],
        incremental_fields=[
            {
                "label": "stamp",
                "type": IncrementalFieldType.DateTime,
                "field": "stamp",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        partition_key="stamp",
        # Rows are yielded per monitor batch per window, so stamps are not globally ascending;
        # desc persists the incremental watermark only once the job completes.
        sort_mode="desc",
    ),
}

ENDPOINTS = tuple(CRONITOR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CRONITOR_ENDPOINTS.items()
}
