from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PGANALYZE_API_URL = "https://app.pganalyze.com/graphql"

# pganalyze docs ask callers not to send "more than a few times per hour" — keep request volume low
PGANALYZE_MAX_RETRY_ATTEMPTS = 3
PGANALYZE_REQUEST_TIMEOUT_SECONDS = 60

# getQueryStats aggregates over any [startTs, endTs) range; we pull one row per query per UTC day.
# A first or full-refresh sync covers yesterday and today. An incremental sync resumes at the day of
# its watermark, capped so a long-paused source does not walk back past pganalyze's retention.
QUERY_STATS_INITIAL_LOOKBACK_DAYS = 1
QUERY_STATS_MAX_CATCHUP_DAYS = 7


SYNCED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "synced_at",
        "type": IncrementalFieldType.DateTime,
        "field": "synced_at",
        "field_type": IncrementalFieldType.DateTime,
        "is_indexed": False,
    },
]

WINDOW_START_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "window_start",
        "type": IncrementalFieldType.DateTime,
        "field": "window_start",
        "field_type": IncrementalFieldType.DateTime,
        "is_indexed": False,
    },
]


@dataclass
class PgAnalyzeEndpointConfig:
    incremental_fields: list[IncrementalField]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_count: int = 1
    partition_size: int = 1
    partition_mode: PartitionMode | None = "datetime"
    partition_format: PartitionFormat | None = "week"
    partition_keys: list[str] | None = field(default_factory=lambda: ["synced_at"])


# pganalyze schemas we expose to the warehouse.
# - servers: dimensional. One row per server, no incremental.
# - issues: per-server findings (index recs, vacuum issues, slow queries, etc.).
#   pganalyze's getIssues returns no timestamps, so we tag rows with synced_at and
#   use merge-on-id for idempotent upserts.
# - query_stats: per-database query performance for one UTC day. The current day is partial and is
#   re-fetched by the next sync, so merge on (database, query, day) replaces it with the full day.
PGANALYZE_ENDPOINTS: dict[str, PgAnalyzeEndpointConfig] = {
    "servers": PgAnalyzeEndpointConfig(
        incremental_fields=[],
        primary_keys=["humanId"],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "issues": PgAnalyzeEndpointConfig(
        incremental_fields=SYNCED_AT_INCREMENTAL_FIELDS,
    ),
    "query_stats": PgAnalyzeEndpointConfig(
        incremental_fields=WINDOW_START_INCREMENTAL_FIELDS,
        primary_keys=["databaseId", "id", "window_start"],
        partition_keys=["window_start"],
    ),
}

ENDPOINTS = tuple(PGANALYZE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: cfg.incremental_fields for name, cfg in PGANALYZE_ENDPOINTS.items()
}
