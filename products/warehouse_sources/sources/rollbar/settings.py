from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class RollbarEndpointConfig:
    name: str
    path: str
    # Key the rows live under inside the response `result`. Every Rollbar list
    # endpoint nests its rows under a key (e.g. `result.environments`); `None`
    # is only for the defensive case where `result` is itself a bare list.
    data_key: Optional[str]
    primary_key: str = "id"
    pagination: Literal["page", "keyset", "time_series"] = "page"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable event-time field used for datetime partitioning.
    partition_key: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)


_TIMESTAMP_INCREMENTAL_FIELD: IncrementalField = {
    "label": "timestamp",
    "type": IncrementalFieldType.Integer,
    "field": "timestamp",
    "field_type": IncrementalFieldType.Integer,
}

# Rollbar's project-scoped API (api.rollbar.com/api/1, X-Rollbar-Access-Token
# header with a read-scope project token). No list endpoint has a server-side
# timestamp filter; occurrences are strictly descending by id, so they get an
# id high-water-mark incremental (walk from the head until crossing the
# watermark). Items mutate in place (counters), so they stay full refresh.
# The count reports return one fixed window of recent daily buckets in a single
# request, so an incremental sync re-reads that window and merges on
# `timestamp`, which keeps the buckets that later fall out of the window.
ROLLBAR_ENDPOINTS: dict[str, RollbarEndpointConfig] = {
    "items": RollbarEndpointConfig(
        name="items",
        path="/items",
        data_key="items",
    ),
    "occurrences": RollbarEndpointConfig(
        name="occurrences",
        path="/instances",
        data_key="instances",
        pagination="keyset",
        partition_key="timestamp",
        incremental_fields=[
            {
                "label": "id",
                "type": IncrementalFieldType.Integer,
                "field": "id",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "deploys": RollbarEndpointConfig(
        name="deploys",
        path="/deploys",
        data_key="deploys",
    ),
    "environments": RollbarEndpointConfig(
        name="environments",
        path="/environments",
        data_key="environments",
    ),
    "occurrence_counts": RollbarEndpointConfig(
        name="occurrence_counts",
        path="/reports/occurrence_counts",
        data_key=None,
        primary_key="timestamp",
        pagination="time_series",
        # The API counts only error and critical occurrences unless `min_level` is lower.
        params={"bucket_size": 86400, "min_level": "debug"},
        incremental_fields=[_TIMESTAMP_INCREMENTAL_FIELD],
    ),
    "activated_item_counts": RollbarEndpointConfig(
        name="activated_item_counts",
        path="/reports/activated_counts",
        data_key=None,
        primary_key="timestamp",
        pagination="time_series",
        params={"bucket_size": 86400, "buckets": 366},
        incremental_fields=[_TIMESTAMP_INCREMENTAL_FIELD],
    ),
}

ENDPOINTS = tuple(ROLLBAR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ROLLBAR_ENDPOINTS.items() if config.incremental_fields
}
