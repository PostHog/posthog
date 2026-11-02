from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)


@dataclass(frozen=True)
class WorkOSEndpointConfig:
    name: str
    path: str
    # `created_at` is set once and never changes, so it's a stable partition key.
    partition_key: str = "created_at"
    page_size: int = 100  # WorkOS max page size
    fanout: DependentEndpointConfig | None = None
    # Read by the shared fan-out builder. WorkOS has no server-side timestamp filter, so these stay empty.
    incremental_fields: list[str] = field(default_factory=list)
    default_incremental_field: str | None = None


# Parent of the `waitlist_entries` fan-out, not a table of its own. WorkOS returns every
# waitlist in one response and documents no `limit` param for it.
WAITLISTS_PARENT = WorkOSEndpointConfig(name="waitlists", path="/user_management/waitlists")


# WorkOS list endpoints share one cursor-paginated envelope
# ({"data": [...], "list_metadata": {"before": ..., "after": ...}}) and expose no
# server-side timestamp filter, so a polled sync is always a full refresh. Incremental
# sync on WorkOS is only possible through the /events API, which is not modeled here.
# WEBHOOK_EVENTS_BY_SCHEMA below lists the tables that leave polling behind.
WORKOS_ENDPOINTS: dict[str, WorkOSEndpointConfig] = {
    "organizations": WorkOSEndpointConfig(name="organizations", path="/organizations"),
    "users": WorkOSEndpointConfig(name="users", path="/user_management/users"),
    "connections": WorkOSEndpointConfig(name="connections", path="/connections"),
    "directories": WorkOSEndpointConfig(name="directories", path="/directories"),
    "directory_users": WorkOSEndpointConfig(name="directory_users", path="/directory_users"),
    "directory_groups": WorkOSEndpointConfig(name="directory_groups", path="/directory_groups"),
    "waitlist_entries": WorkOSEndpointConfig(
        name="waitlist_entries",
        path="/user_management/waitlists/{waitlist_id}/entries",
        fanout=DependentEndpointConfig(
            parent_name=WAITLISTS_PARENT.name,
            resolve_param="waitlist_id",
            resolve_field="id",
            # Entries already carry their own `waitlist_id`.
            include_from_parent=[],
            child_params={"limit": 100, "order": "desc"},
        ),
    ),
}

ENDPOINTS = tuple(WORKOS_ENDPOINTS.keys())

# Webhook sync replaces polling, so a table only qualifies when its events cover the whole
# create, update, and delete cycle. WorkOS publishes no `connection.updated` or `dsync.updated`
# event, which is why `connections` and `directories` stay on full refresh: under webhook sync a
# directory rename or a SAML certificate renewal would never reach the table.
WEBHOOK_EVENTS_BY_SCHEMA: dict[str, tuple[str, ...]] = {
    "users": ("user.created", "user.updated", "user.deleted"),
    "organizations": ("organization.created", "organization.updated", "organization.deleted"),
    "directory_users": ("dsync.user.created", "dsync.user.updated", "dsync.user.deleted"),
    "directory_groups": ("dsync.group.created", "dsync.group.updated", "dsync.group.deleted"),
}

WEBHOOK_EVENT_TO_SCHEMA = {event: schema for schema, events in WEBHOOK_EVENTS_BY_SCHEMA.items() for event in events}
WEBHOOK_SCHEMA_NAMES = frozenset(WEBHOOK_EVENTS_BY_SCHEMA)
ALL_WEBHOOK_EVENTS = tuple(event for events in WEBHOOK_EVENTS_BY_SCHEMA.values() for event in events)
