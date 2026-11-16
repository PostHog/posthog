from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class UserbackEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Fields the API can filter on server-side (OData `filter=<field> ge '<timestamp>'`).
    # The first entry is the default cursor the schema picker offers.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning. Never an update field.
    partition_key: Optional[str] = None
    # Field to sort on during a full refresh, so rows created during the sync land on later pages
    # and do not shift earlier pages. None keeps the API default order.
    full_refresh_sort: Optional[str] = None


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


USERBACK_ENDPOINTS: dict[str, UserbackEndpointConfig] = {
    "feedback": UserbackEndpointConfig(
        name="feedback",
        path="/feedback",
        incremental_fields=[_datetime_field("modified"), _datetime_field("created")],
        partition_key="created",
        full_refresh_sort="created",
    ),
    # `/feedback/comment` lists the comments of every feedback item in the account, so it is a
    # top-level list and not a fan-out over feedback.
    "feedback_comments": UserbackEndpointConfig(
        name="feedback_comments",
        path="/feedback/comment",
        incremental_fields=[_datetime_field("modified"), _datetime_field("created")],
        partition_key="created",
        full_refresh_sort="created",
    ),
    "session_recordings": UserbackEndpointConfig(
        name="session_recordings",
        path="/sessionRecording",
        incremental_fields=[_datetime_field("created")],
        partition_key="created",
        full_refresh_sort="created",
    ),
    "projects": UserbackEndpointConfig(
        name="projects",
        path="/project",
        partition_key="created",
        full_refresh_sort="created",
    ),
    "members": UserbackEndpointConfig(
        name="members",
        path="/member",
    ),
    "workflows": UserbackEndpointConfig(
        name="workflows",
        path="/workflow",
    ),
}

ENDPOINTS = tuple(USERBACK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in USERBACK_ENDPOINTS.items() if config.incremental_fields
}
