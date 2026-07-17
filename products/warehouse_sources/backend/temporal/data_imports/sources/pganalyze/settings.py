from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PGANALYZE_API_URL = "https://app.pganalyze.com/graphql"

# pganalyze docs ask callers not to send "more than a few times per hour" — keep request volume low
PGANALYZE_MAX_RETRY_ATTEMPTS = 3
PGANALYZE_REQUEST_TIMEOUT_SECONDS = 60


SYNCED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "synced_at",
        "type": IncrementalFieldType.DateTime,
        "field": "synced_at",
        "field_type": IncrementalFieldType.DateTime,
        "is_indexed": False,
    },
]


@dataclass
class PgAnalyzeEndpointConfig:
    incremental_fields: list[IncrementalField]
    primary_key: str = "id"
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
PGANALYZE_ENDPOINTS: dict[str, PgAnalyzeEndpointConfig] = {
    "servers": PgAnalyzeEndpointConfig(
        incremental_fields=[],
        primary_key="humanId",
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "issues": PgAnalyzeEndpointConfig(
        incremental_fields=SYNCED_AT_INCREMENTAL_FIELDS,
    ),
}

ENDPOINTS = tuple(PGANALYZE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: cfg.incremental_fields for name, cfg in PGANALYZE_ENDPOINTS.items()
}
