from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

APIFY_BASE_URL = "https://api.apify.com/v2"

# Apify exposes the rows produced by an Actor run as a single dataset. The dataset is addressed by a
# datasetId (or the `username~dataset-name` shorthand) and queried via GET /datasets/{id}/items. The
# rows are arbitrary Actor output, so this table's columns are whatever the Actor stored.
DATASET_ITEMS_ENDPOINT = "dataset_items"

# The rest of the tables are account-level: they are addressed by the API token alone and describe
# the whole Apify account rather than the one configured dataset — the runs it has executed, the
# Actors and datasets those runs reference, and what the account has spent.
ACTOR_RUNS_ENDPOINT = "actor_runs"
ACTORS_ENDPOINT = "actors"
DATASETS_ENDPOINT = "datasets"
USAGE_MONTHLY_ENDPOINT = "usage_monthly"

ENDPOINTS = (
    DATASET_ITEMS_ENDPOINT,
    ACTOR_RUNS_ENDPOINT,
    ACTORS_ENDPOINT,
    DATASETS_ENDPOINT,
    USAGE_MONTHLY_ENDPOINT,
)

# Dataset rows have no field the API guarantees to be present or unique (the shape is defined by the
# Actor, not Apify), so there is no primary key to merge on. Combined with the lack of a server-side
# timestamp filter, the table is full-refresh only and the whole dataset is replaced on every sync.
PRIMARY_KEYS: dict[str, list[str] | None] = {
    DATASET_ITEMS_ENDPOINT: None,
    ACTOR_RUNS_ENDPOINT: ["id"],
    ACTORS_ENDPOINT: ["id"],
    DATASETS_ENDPOINT: ["id"],
    # One row per day of a usage cycle, and a day belongs to exactly one cycle.
    USAGE_MONTHLY_ENDPOINT: ["date"],
}

# Only `/actor-runs` carries a server-side lower-bound filter (`startedAfter`), so it is the only
# table that can sync incrementally. The others page their full collection every run, and dataset
# items have no timestamp at all — leaving an endpoint out of this map keeps `build_endpoint_schemas`
# from advertising incremental sync for it.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ACTOR_RUNS_ENDPOINT: [incremental_field("startedAt")],
}


@frozen
class ApifyPlatformEndpointConfig:
    path: str
    # Every platform list endpoint answers `{"data": {"items": [...], "total": N, ...}}`.
    data_selector: str = "data.items"
    total_path: Optional[str] = "data.total"
    paginated: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    # Stable creation-time field to partition on. Never a field that can move (`modifiedAt`,
    # `accessedAt`, `stats.lastRunStartedAt`), which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Query param that filters the collection to rows at or after a timestamp, and the field it
    # filters on. Set only where Apify documents a real server-side filter.
    incremental_param: Optional[str] = None
    incremental_cursor: Optional[str] = None


PLATFORM_ENDPOINTS: dict[str, ApifyPlatformEndpointConfig] = {
    ACTOR_RUNS_ENDPOINT: ApifyPlatformEndpointConfig(
        path="/actor-runs",
        partition_key="startedAt",
        incremental_param="startedAfter",
        incremental_cursor="startedAt",
    ),
    ACTORS_ENDPOINT: ApifyPlatformEndpointConfig(
        path="/actors",
        partition_key="createdAt",
    ),
    DATASETS_ENDPOINT: ApifyPlatformEndpointConfig(
        path="/datasets",
        # An Actor run stores its output in an unnamed dataset, and those are the datasets whose
        # rows `dataset_items` syncs. The endpoint lists only named datasets unless asked.
        params={"unnamed": "true"},
        partition_key="createdAt",
    ),
    USAGE_MONTHLY_ENDPOINT: ApifyPlatformEndpointConfig(
        path="/users/me/usage/monthly",
        # A single object holding the cycle totals and a daily breakdown, not a paginated list.
        data_selector="data",
        total_path=None,
        paginated=False,
    ),
}
