from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = ("Stats",)

PRIMARY_KEYS: dict[str, list[str]] = {
    # `intervalId` is unique within a single granularity (`unit`), but the source only ever
    # syncs one selected unit at a time — `unit` is included defensively in case that changes.
    "Stats": ["unit", "intervalId"],
}

# `interval_start_ms` (Unix ms) is derived from `intervalId` (see `_add_interval_start` in
# ably.py) — Ably's own `intervalId` is a granularity-dependent string ("2024-01-15:14:05" for
# minute, "2024-01-15:14" for hour, etc), not directly usable as the `start`/`end` stats params,
# which take Unix ms. Using the same unit here means the watermark from one sync feeds straight
# back into the next sync's `start` param with no reformatting.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Stats": [
        {
            "label": "Interval start",
            "type": IncrementalFieldType.DateTime,
            "field": "interval_start_ms",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
}

# `interval_start` (ISO datetime string, also derived from `intervalId`) is used for partitioning
# instead of `interval_start_ms` — partitioning wants an actual datetime-typed column.
PARTITION_KEY = "interval_start"

# https://ably.com/docs/api/rest-api#stats
STATS_UNITS = ("minute", "hour", "day", "month")
DEFAULT_STATS_UNIT = "hour"

# Ably caps /stats page size at 1000 (default 100).
MAX_LIMIT = 1000

BASE_URL = "https://main.realtime.ably.net"
