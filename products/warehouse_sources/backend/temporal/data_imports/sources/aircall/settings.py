from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class AircallEndpointConfig:
    name: str
    path: str
    # Key the list of objects is nested under in the response body (e.g. {"calls": [...]}).
    data_key: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # When set, the transport re-anchors the `from` query param to the latest value of this
    # field once a page chain ends, to page around Aircall's hard 10k-record-per-query cap on
    # calls/contacts. Must be the same stable creation-time field the API's `from` filter
    # applies to.
    reanchor_field: Optional[str] = None


# Aircall timestamps are UNIX epoch seconds, so candidate incremental fields are stored as
# integers even though the UI presents them as datetimes. The `from`/`to` list filters take
# UNIX timestamps and filter on the resource's creation date, so incremental sync is only
# enabled where the cursor field lines up with what `from` actually filters on (calls ->
# started_at, contacts -> created_at). Everything else is full refresh.
AIRCALL_ENDPOINTS: dict[str, AircallEndpointConfig] = {
    "calls": AircallEndpointConfig(
        name="calls",
        path="/calls",
        data_key="calls",
        partition_key="started_at",
        reanchor_field="started_at",
        incremental_fields=[
            {
                "label": "started_at",
                "type": IncrementalFieldType.DateTime,
                "field": "started_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "contacts": AircallEndpointConfig(
        name="contacts",
        path="/contacts",
        data_key="contacts",
        partition_key="created_at",
        reanchor_field="created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "users": AircallEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        partition_key="created_at",
    ),
    "teams": AircallEndpointConfig(
        name="teams",
        path="/teams",
        data_key="teams",
    ),
    "numbers": AircallEndpointConfig(
        name="numbers",
        path="/numbers",
        data_key="numbers",
        partition_key="created_at",
    ),
    "tags": AircallEndpointConfig(
        name="tags",
        path="/tags",
        data_key="tags",
    ),
}

ENDPOINTS = tuple(AIRCALL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AIRCALL_ENDPOINTS.items() if config.incremental_fields
}
