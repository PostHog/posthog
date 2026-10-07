from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Granola caps the notes page_size at 30; use the max to keep request volume low against the
# 5 req/s sustained / 25-per-5s burst rate limit.
PAGE_SIZE = 30


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
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = PAGE_SIZE
    default_incremental_field: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None


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
    # https://docs.granola.ai/api-reference/get-transcript
    # One row per transcript item, fanned out over the notes listing. Items carry no id, and the
    # endpoint has no server-side time filter, so this is full refresh only.
    "transcripts": GranolaEndpointConfig(
        name="transcripts",
        path="/v1/notes/{note_id}/transcript",
        data_key="transcript",
        partition_key="start_time",
        primary_keys=["note_id", "start_time", "end_time"],
        page_size=100,
        fanout=DependentEndpointConfig(
            parent_name="notes",
            resolve_param="note_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "note_id"},
            # A note deleted between the listing and the transcript fetch 404s; skip it.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(GRANOLA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GRANOLA_ENDPOINTS.items()
}
