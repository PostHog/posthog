from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# xMatters caps `limit` at 1000; using the max reduces round-trips.
PAGE_SIZE = 1000


@dataclass(frozen=True)
class XmattersEndpointConfig:
    name: str
    path: str  # Path under the API base URL, e.g. "/events"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None  # Stable datetime field used to partition (never a mutable field)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # True only when the endpoint exposes a server-side time-window filter (`from`) on the
    # created timestamp AND accepts a `sortBy`/`sortOrder` ordering we control. Both are
    # required for safe incremental sync: the filter bounds the window and the ascending
    # sort guarantees a stable watermark. Reference/config endpoints stay full-refresh.
    supports_from: bool = False
    # The `sortBy` value that orders rows by the same timestamp `from` filters on.
    sort_by: Optional[str] = None
    # Set for per-parent endpoints; the parent is another endpoint in this catalog.
    fanout: Optional[DependentEndpointConfig] = None
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE


_CREATED_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created",
        "type": IncrementalFieldType.DateTime,
        "field": "created",
        "field_type": IncrementalFieldType.DateTime,
    },
]


_RECEIVED_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "received",
        "type": IncrementalFieldType.DateTime,
        "field": "received",
        "field_type": IncrementalFieldType.DateTime,
    },
]


# Sent explicitly so the audit table does not depend on the API's default set of types.
AUDIT_TYPES = (
    "EVENT_ANNOTATED",
    "EVENT_CREATED",
    "EVENT_SUSPENDED",
    "EVENT_RESUMED",
    "EVENT_COMPLETED",
    "EVENT_TERMINATED",
    "RESPONSE_RECEIVED",
)


# Every list response is wrapped in a `data` array with `count`, `total`, and `links`.
XMATTERS_ENDPOINTS: dict[str, XmattersEndpointConfig] = {
    "events": XmattersEndpointConfig(
        name="events",
        path="/events",
        partition_key="created",
        incremental_fields=_CREATED_INCREMENTAL,
        # `/events` accepts `from`/`to` (ISO 8601) that filter by the event's created time and a
        # `sortBy=START_TIME&sortOrder=ASCENDING` ordering we control, so incremental sync is safe.
        # Note this picks up newly *created* events only — status changes to events created before
        # the cursor are not re-fetched (xMatters filters on created time, not an updated cursor).
        supports_from=True,
        sort_by="START_TIME",
    ),
    "people": XmattersEndpointConfig(
        name="people",
        path="/people",
    ),
    "groups": XmattersEndpointConfig(
        name="groups",
        path="/groups",
    ),
    "devices": XmattersEndpointConfig(
        name="devices",
        path="/devices",
    ),
    "sites": XmattersEndpointConfig(
        name="sites",
        path="/sites",
    ),
    "roles": XmattersEndpointConfig(
        name="roles",
        path="/roles",
    ),
    "dynamic_teams": XmattersEndpointConfig(
        name="dynamic_teams",
        path="/dynamic-teams",
    ),
    "plans": XmattersEndpointConfig(
        name="plans",
        path="/plans",
    ),
    "subscriptions": XmattersEndpointConfig(
        name="subscriptions",
        path="/subscriptions",
    ),
    "services": XmattersEndpointConfig(
        name="services",
        path="/services",
    ),
    "signals": XmattersEndpointConfig(
        name="signals",
        path="/signals",
        partition_key="received",
        incremental_fields=_RECEIVED_INCREMENTAL,
        # `from` keeps signals received at or after the cursor, and RECEIVED is a documented sort.
        supports_from=True,
        sort_by="RECEIVED",
    ),
    "incidents": XmattersEndpointConfig(
        name="incidents",
        path="/incidents",
        # `from` filters on createdAt, but the sort order is undocumented and incidents change
        # status after creation, so this stays full refresh.
        partition_key="createdAt",
    ),
    "audits": XmattersEndpointConfig(
        name="audits",
        # /audits only answers for one event at a time, so it fans out over /events.
        path="/audits?eventId={event_id}",
        primary_keys=["event_id", "id"],
        partition_key="at",
        fanout=DependentEndpointConfig(
            parent_name="events",
            resolve_param="event_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "event_id"},
            parent_params={"sortBy": "START_TIME", "sortOrder": "ASCENDING"},
            child_params={"auditType": ",".join(AUDIT_TYPES), "sortOrder": "ASCENDING"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "group_members": XmattersEndpointConfig(
        name="group_members",
        path="/groups/{group_id}/members",
        primary_keys=["group_id", "member_id"],
        fanout=DependentEndpointConfig(
            parent_name="groups",
            resolve_param="group_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "group_id"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "group_shifts": XmattersEndpointConfig(
        name="group_shifts",
        path="/groups/{group_id}/shifts",
        primary_keys=["group_id", "id"],
        partition_key="created",
        fanout=DependentEndpointConfig(
            parent_name="groups",
            resolve_param="group_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "group_id"},
            # Only On-Call groups have shifts.
            parent_params={"groupType": "ON_CALL"},
            child_params={"embed": "rotation"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "user_deliveries": XmattersEndpointConfig(
        name="user_deliveries",
        # One row per notified person per event. The endpoint reads historical data only, so the
        # transport adds the required `at` timestamp per sync.
        path="/events/{event_id}/user-deliveries",
        primary_keys=["event_id", "person_id"],
        fanout=DependentEndpointConfig(
            parent_name="events",
            resolve_param="event_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "event_id"},
            parent_params={"sortBy": "START_TIME", "sortOrder": "ASCENDING"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "on_call": XmattersEndpointConfig(
        name="on_call",
        # With no timeframe, /on-call returns the shift occurrences that are on call right now.
        path="/on-call?groups={group_id}",
        primary_keys=["group_id", "shift_id", "start"],
        fanout=DependentEndpointConfig(
            parent_name="groups",
            resolve_param="group_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "group_id"},
            parent_params={"groupType": "ON_CALL"},
            # The default is 3 members per shift; 100 is the documented maximum.
            child_params={"membersPerShift": 100},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(XMATTERS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in XMATTERS_ENDPOINTS.items() if config.incremental_fields
}
