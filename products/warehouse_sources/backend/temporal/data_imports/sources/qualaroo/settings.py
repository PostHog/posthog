from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The Reporting API caps a page at 500 records; the largest page minimises round trips.
PAGE_SIZE = 500


@dataclass(frozen=False)
class QualarooEndpointConfig:
    name: str
    path: str
    # Qualaroo nudge (survey) IDs are unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None


# Qualaroo REST Reporting API endpoints. `nudges` is the account-wide survey list. `responses` is
# listed once per nudge at /nudges/{nudge_id}/responses.json.
#
# The nudges list has no server-side timestamp filter, so it is full refresh only. Responses take
# a `start_date` filter in UNIX seconds against the submission `time`, so they sync incrementally.
QUALAROO_ENDPOINTS: dict[str, QualarooEndpointConfig] = {
    "nudges": QualarooEndpointConfig(name="nudges", path="/nudges.json"),
    # The docs do not say that a response id is unique across nudges, so the nudge id is part of the key.
    "responses": QualarooEndpointConfig(
        name="responses",
        path="/nudges/{nudge_id}/responses.json",
        primary_keys=["nudge_id", "id"],
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        default_incremental_field="time",
        fanout=DependentEndpointConfig(
            parent_name="nudges",
            resolve_param="nudge_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "nudge_id"},
            # Without `order=asc` the API returns newest first, so a response submitted mid-sync
            # shifts the offset pages and one row is read twice while another is skipped.
            child_params={"order": "asc"},
            # The API answers 404 for a nudge deleted between the nudge listing and this request.
            # That nudge has no responses to sync, so it must not fail the nudges that remain.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(QUALAROO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in QUALAROO_ENDPOINTS.items() if config.incremental_fields
}
