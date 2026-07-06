from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class EmailOctopusEndpointConfig:
    name: str
    # Path on the v2 API. For fan-out endpoints this is a template with a `{list_id}` placeholder.
    path: str
    incremental_fields: list[IncrementalField]
    # A stable creation-time field used for datetime partitioning. Never `last_updated_at`,
    # which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Fan out one paginated request per synced list, materializing each list's contacts. When True,
    # `path` is a template with a `{list_id}` placeholder and rows carry their `list_id`.
    fan_out_over_lists: bool = False


# EmailOctopus contacts carry a status and the API returns only `subscribed` contacts unless asked
# otherwise, so we iterate every status to capture the full membership. A contact's id is stable
# across status changes, so merge on [list_id, id] keeps a single row per contact reflecting its
# latest status.
CONTACT_STATUSES = ("subscribed", "unsubscribed", "pending")


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


EMAILOCTOPUS_ENDPOINTS: dict[str, EmailOctopusEndpointConfig] = {
    "lists": EmailOctopusEndpointConfig(
        name="lists",
        path="/lists",
        partition_key="created_at",
        # No server-side timestamp filter on /lists, so full refresh only.
        incremental_fields=[],
    ),
    "campaigns": EmailOctopusEndpointConfig(
        name="campaigns",
        path="/campaigns",
        partition_key="created_at",
        # No server-side timestamp filter on /campaigns, so full refresh only.
        incremental_fields=[],
    ),
    # Contacts are nested under lists. The endpoint exposes genuine server-side filters
    # (`created_at.gte`, `last_updated_at.gte`), so incremental sync is real here.
    "contacts": EmailOctopusEndpointConfig(
        name="contacts",
        path="/lists/{list_id}/contacts",
        partition_key="created_at",
        primary_keys=["list_id", "id"],
        fan_out_over_lists=True,
        incremental_fields=[
            _datetime_field("last_updated_at"),
            _datetime_field("created_at"),
        ],
    ),
}

ENDPOINTS = tuple(EMAILOCTOPUS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in EMAILOCTOPUS_ENDPOINTS.items()
}
