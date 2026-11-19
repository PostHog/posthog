from dataclasses import field
from typing import Any, Literal

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

FanoutParent = Literal["applications", "endpoints"]


@frozen
class SvixEndpointConfig:
    name: str
    path: str
    # Primary key differs per endpoint: applications carry an opaque `id`, event types are keyed by
    # their unique `name`, and fan-out rows add the application id they were listed under.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # The resource whose rows fill the path placeholders. `endpoints` is itself listed per
    # application, so its children are a two-level fan-out (applications -> endpoints -> child).
    parent: FanoutParent | None = None
    params: dict[str, Any] = field(default_factory=dict)
    incremental_field: str | None = None
    partition_key: str | None = None
    # The endpoint answers one object per parent instead of a `{"data": [...]}` list.
    single_object: bool = False


# Paths are relative to the Management API base URL (`/api/v1`).
SVIX_ENDPOINTS: dict[str, SvixEndpointConfig] = {
    "applications": SvixEndpointConfig(name="applications", path="/app", primary_keys=["id"]),
    "event_types": SvixEndpointConfig(name="event_types", path="/event-type", primary_keys=["name"]),
    "endpoints": SvixEndpointConfig(
        name="endpoints",
        path="/app/{app_id}/endpoint",
        primary_keys=["app_id", "id"],
        parent="applications",
        partition_key="createdAt",
    ),
    "messages": SvixEndpointConfig(
        name="messages",
        path="/app/{app_id}/msg",
        primary_keys=["app_id", "id"],
        parent="applications",
        incremental_field="timestamp",
        partition_key="timestamp",
    ),
    "message_attempts": SvixEndpointConfig(
        name="message_attempts",
        path="/app/{app_id}/attempt/endpoint/{endpoint_id}",
        primary_keys=["app_id", "id"],
        parent="endpoints",
        # Without it, canceled attempts are reported as successful.
        params={"expanded_statuses": "true"},
        incremental_field="timestamp",
        partition_key="timestamp",
    ),
    "endpoint_stats": SvixEndpointConfig(
        name="endpoint_stats",
        path="/app/{app_id}/endpoint/{endpoint_id}/stats",
        primary_keys=["app_id", "endpoint_id"],
        parent="endpoints",
        single_object=True,
    ),
}

ENDPOINTS = tuple(SVIX_ENDPOINTS.keys())

# Re-read window for incremental runs. Each application (or endpoint) is walked on its own, so a
# row created in an application read early in a run can be older than the run's watermark.
INCREMENTAL_LOOKBACK_SECONDS = 60 * 60

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        IncrementalField(
            label=config.incremental_field,
            type=IncrementalFieldType.DateTime,
            field=config.incremental_field,
            field_type=IncrementalFieldType.DateTime,
        )
    ]
    for name, config in SVIX_ENDPOINTS.items()
    if config.incremental_field is not None
}
