from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Eppo's public API (https://eppo.cloud/api/v1) returns a plain JSON array for every list
# endpoint below (no envelope, no total count). Endpoints with a documented "limit"/"offset"
# pair are paginated with the offset paginator; endpoints with no such params return
# everything in a single page.
ENDPOINTS = (
    "Experiments",
    "Metrics",
    "MetricCollections",
    "FeatureFlags",
    "Bandits",
    "Holdouts",
    "Teams",
    "Tags",
    "Audiences",
    "Environments",
)

# Endpoints that document `offset`/`limit` query params (https://eppo.cloud/api/docs).
# Everything else has no pagination and returns its full list in one response.
PAGINATED_ENDPOINTS = frozenset(
    {
        "Experiments",
        "Metrics",
        "FeatureFlags",
        "Holdouts",
    }
)

PAGE_LIMIT = 100

# Only "Experiments" documents a server-side timestamp filter (`created_since`/`updated_since`,
# both ISO 8601). We map to `created_since` — `created_date` is a field the response actually
# returns, so the synced watermark is verifiable, unlike `updated_since` which has no matching
# output column. Every other endpoint has no documented filter, so it stays full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Experiments": [
        {
            "label": "created_date",
            "type": IncrementalFieldType.DateTime,
            "field": "created_date",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}

# Maps an incremental field name to the query param Eppo expects it as.
INCREMENTAL_QUERY_PARAM: dict[str, str] = {
    "created_date": "created_since",
}

# Primary keys are a numeric `id`, unique per endpoint (no fan-out/parent-child endpoints here).
PRIMARY_KEYS: dict[str, list[str]] = {
    "Experiments": ["id"],
    "Metrics": ["id"],
    "MetricCollections": ["id"],
    "FeatureFlags": ["id"],
    "Bandits": ["id"],
    "Holdouts": ["id"],
    "Teams": ["id"],
    "Tags": ["id"],
    "Audiences": ["id"],
    "Environments": ["id"],
}

# A stable creation-time field to partition on, where the endpoint has one. `None` disables
# partitioning for endpoints with no such field (MetricCollections, Teams).
PARTITION_KEYS: dict[str, str | None] = {
    "Experiments": "created_date",
    "Metrics": "created_date",
    "MetricCollections": None,
    "FeatureFlags": "created_at",
    "Bandits": "created_at",
    "Holdouts": "created_at",
    "Teams": None,
    "Tags": "created_at",
    "Audiences": "created_at",
    "Environments": "created_at",
}
