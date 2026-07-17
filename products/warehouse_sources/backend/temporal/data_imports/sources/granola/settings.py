from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class GranolaEndpointConfig:
    name: str
    path: str
    # Key that wraps the list of rows in the JSON response body (e.g. {"notes": [...]}).
    data_key: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field to partition on. Never use updated_at - it changes and rewrites partitions.
    partition_key: Optional[str] = None
    # Maps an advertised incremental field name to the server-side query param that filters on it.
    incremental_query_params: dict[str, str] = field(default_factory=dict)


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


GRANOLA_ENDPOINTS: dict[str, GranolaEndpointConfig] = {
    # https://docs.granola.ai/api-reference/list-notes
    # Only returns notes that already have a generated AI summary + transcript.
    # Both created_after and updated_after are genuine server-side filters per the OpenAPI spec.
    "notes": GranolaEndpointConfig(
        name="notes",
        path="/v1/notes",
        data_key="notes",
        partition_key="created_at",
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
        incremental_query_params={"updated_at": "updated_after", "created_at": "created_after"},
    ),
    # https://docs.granola.ai/api-reference/list-folders
    # No timestamp fields and no server-side time filter - full refresh only.
    "folders": GranolaEndpointConfig(
        name="folders",
        path="/v1/folders",
        data_key="folders",
    ),
}

ENDPOINTS = tuple(GRANOLA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GRANOLA_ENDPOINTS.items()
}
