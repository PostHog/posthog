from dataclasses import dataclass


@dataclass
class WorkOSEndpointConfig:
    name: str
    path: str
    # `created_at` is set once and never changes, so it's a stable partition key.
    partition_key: str = "created_at"
    page_size: int = 100  # WorkOS max page size


# WorkOS list endpoints share one cursor-paginated envelope
# ({"data": [...], "list_metadata": {"before": ..., "after": ...}}) and expose no
# server-side timestamp filter, so every endpoint is full-refresh only. Incremental
# sync on WorkOS is only possible through the /events API, which is not modeled here.
WORKOS_ENDPOINTS: dict[str, WorkOSEndpointConfig] = {
    "organizations": WorkOSEndpointConfig(name="organizations", path="/organizations"),
    "users": WorkOSEndpointConfig(name="users", path="/user_management/users"),
    "connections": WorkOSEndpointConfig(name="connections", path="/connections"),
    "directories": WorkOSEndpointConfig(name="directories", path="/directories"),
    "directory_users": WorkOSEndpointConfig(name="directory_users", path="/directory_users"),
    "directory_groups": WorkOSEndpointConfig(name="directory_groups", path="/directory_groups"),
}

ENDPOINTS = tuple(WORKOS_ENDPOINTS.keys())

WEBHOOK_EVENTS_BY_SCHEMA: dict[str, tuple[str, ...]] = {
    "users": ("user.created", "user.updated", "user.deleted"),
    "organizations": ("organization.created", "organization.updated", "organization.deleted"),
    "connections": ("connection.activated", "connection.deactivated", "connection.deleted"),
    "directories": ("dsync.activated", "dsync.deleted"),
    "directory_users": ("dsync.user.created", "dsync.user.updated", "dsync.user.deleted"),
    "directory_groups": (
        "dsync.group.created",
        "dsync.group.updated",
        "dsync.group.deleted",
        "dsync.group.user_added",
        "dsync.group.user_removed",
    ),
}

WEBHOOK_EVENT_TO_SCHEMA = {event: schema for schema, events in WEBHOOK_EVENTS_BY_SCHEMA.items() for event in events}
WEBHOOK_SCHEMA_NAMES = frozenset(WEBHOOK_EVENTS_BY_SCHEMA)
ALL_WEBHOOK_EVENTS = tuple(event for events in WEBHOOK_EVENTS_BY_SCHEMA.values() for event in events)
