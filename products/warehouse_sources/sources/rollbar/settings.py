from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class RollbarEndpointConfig:
    name: str
    path: str
    # Key the rows live under inside the response `result`. Every Rollbar list
    # endpoint nests its rows under a key (e.g. `result.environments`); `None`
    # is only for the defensive case where `result` is itself a bare list.
    data_key: Optional[str]
    primary_key: str = "id"
    pagination: Literal["page", "keyset"] = "page"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable event-time field used for datetime partitioning.
    partition_key: Optional[str] = None


# Rollbar's project-scoped API (api.rollbar.com/api/1, X-Rollbar-Access-Token
# header with a read-scope project token). No list endpoint has a server-side
# timestamp filter; occurrences are strictly descending by id, so they get an
# id high-water-mark incremental (walk from the head until crossing the
# watermark). Items mutate in place (counters), so they stay full refresh.
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
}

ENDPOINTS = tuple(ROLLBAR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ROLLBAR_ENDPOINTS.items() if config.incremental_fields
}
