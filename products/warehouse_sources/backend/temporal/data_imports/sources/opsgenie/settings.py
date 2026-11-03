from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Opsgenie's max page size is 100; the default is 20.
DEFAULT_PAGE_SIZE = 100


@dataclass(frozen=True)
class OpsgenieEndpointConfig:
    name: str
    path: str  # Path under the API base URL, including the API version, e.g. "/v2/alerts"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None  # Stable datetime field used to partition (never a mutable field)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # True for endpoints that accept `limit`/`offset` pagination params. Endpoints left
    # False (teams, schedules, escalations, integrations) return their full collection in
    # a single response.
    paginated: bool = False
    # True only for the alert/incident search endpoints, which accept a `query` search
    # param with `createdAt >= <epoch millis>` filtering AND a `sort=createdAt&order=asc`
    # ordering we control. Both are required for safe incremental sync: the filter bounds
    # the window, the sort guarantees a stable ascending watermark. These endpoints also
    # hard-cap `offset + limit` at 20,000 per query, so backfills re-slice into new
    # createdAt windows when they hit the cap.
    supports_search_window: bool = False
    page_size: int = DEFAULT_PAGE_SIZE
    default_incremental_field: Optional[str] = None
    # Set for resources only listed per parent row (e.g. a schedule's rotations); the parent is
    # re-listed each sync.
    fanout: Optional[DependentEndpointConfig] = None
    # JSON path of the rows in the response body. Every Opsgenie collection sits under `data`.
    data_selector: str = "data"
    # JSON path of the next-page cursor, for fan-out children that page with a cursor, not an offset.
    next_cursor_path: Optional[str] = None
    # JSON path of the full next-page URL, for fan-out children whose cursor sits on each row.
    next_url_path: Optional[str] = None


_CREATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "createdAt",
        "type": IncrementalFieldType.DateTime,
        "field": "createdAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


OPSGENIE_ENDPOINTS: dict[str, OpsgenieEndpointConfig] = {
    "alerts": OpsgenieEndpointConfig(
        name="alerts",
        path="/v2/alerts",
        partition_key="createdAt",
        incremental_fields=_CREATED_AT_INCREMENTAL,
        paginated=True,
        # Incremental sync only picks up newly *created* alerts — Opsgenie's search syntax
        # can filter on createdAt but not updatedAt, so status changes to alerts created
        # before the cursor are not re-fetched. Run periodic full refreshes for
        # change capture.
        supports_search_window=True,
    ),
    "incidents": OpsgenieEndpointConfig(
        name="incidents",
        path="/v1/incidents",
        partition_key="createdAt",
        incremental_fields=_CREATED_AT_INCREMENTAL,
        paginated=True,
        supports_search_window=True,
    ),
    "users": OpsgenieEndpointConfig(
        name="users",
        path="/v2/users",
        paginated=True,
    ),
    "teams": OpsgenieEndpointConfig(
        name="teams",
        path="/v2/teams",
    ),
    "schedules": OpsgenieEndpointConfig(
        name="schedules",
        path="/v2/schedules",
    ),
    "escalations": OpsgenieEndpointConfig(
        name="escalations",
        path="/v2/escalations",
    ),
    "services": OpsgenieEndpointConfig(
        name="services",
        path="/v1/services",
        paginated=True,
    ),
    "integrations": OpsgenieEndpointConfig(
        name="integrations",
        path="/v2/integrations",
    ),
    "incident_timeline_entries": OpsgenieEndpointConfig(
        name="incident_timeline_entries",
        path="/v2/incident-timelines/{incident_id}/entries",
        primary_keys=["incident_id", "id"],
        # The timeline endpoint caps `limit` at 20 and pages with an opaque `nextOffset` cursor.
        page_size=20,
        next_cursor_path="data.nextOffset",
        data_selector="data.entries",
        fanout=DependentEndpointConfig(
            parent_name="incidents",
            resolve_param="incident_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "incident_id"},
            parent_params={"sort": "createdAt", "order": "asc"},
            child_params={"order": "asc"},
        ),
    ),
    "alert_logs": OpsgenieEndpointConfig(
        name="alert_logs",
        path="/v2/alerts/{alert_id}/logs",
        # A log entry has no id; its `offset` cursor (epoch millis + nanos) is unique within the alert.
        primary_keys=["alert_id", "offset"],
        partition_key="createdAt",
        next_url_path="paging.next",
        fanout=DependentEndpointConfig(
            parent_name="alerts",
            resolve_param="alert_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "alert_id"},
            parent_params={"sort": "createdAt", "order": "asc"},
            child_params={"order": "asc", "direction": "next"},
            # An alert deleted after the alert listing returns 404; skip it rather than fail the run.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "schedule_on_calls": OpsgenieEndpointConfig(
        name="schedule_on_calls",
        path="/v2/schedules/{schedule_id}/on-calls",
        primary_keys=["schedule_id"],
        # One object per schedule. `flat=true` resolves teams and escalations down to the users
        # on call right now. `/v2/schedules/on-calls` lists every schedule at once but is deprecated.
        fanout=DependentEndpointConfig(
            parent_name="schedules",
            resolve_param="schedule_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "schedule_id"},
            child_params={"flat": "true"},
        ),
    ),
    "schedule_rotations": OpsgenieEndpointConfig(
        name="schedule_rotations",
        path="/v2/schedules/{schedule_id}/rotations",
        primary_keys=["schedule_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="schedules",
            resolve_param="schedule_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "schedule_id"},
        ),
    ),
    "schedule_overrides": OpsgenieEndpointConfig(
        name="schedule_overrides",
        path="/v2/schedules/{schedule_id}/overrides",
        # Opsgenie allows only one override with a given alias per schedule.
        primary_keys=["schedule_id", "alias"],
        fanout=DependentEndpointConfig(
            parent_name="schedules",
            resolve_param="schedule_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "schedule_id"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    # Opsgenie has no member listing endpoint; the members come embedded in the single-team read.
    "team_members": OpsgenieEndpointConfig(
        name="team_members",
        path="/v2/teams/{team_id}",
        primary_keys=["team_id", "user_id"],
        data_selector="data.members",
        fanout=DependentEndpointConfig(
            parent_name="teams",
            resolve_param="team_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "team_id"},
        ),
    ),
}

ENDPOINTS = tuple(OPSGENIE_ENDPOINTS.keys())
