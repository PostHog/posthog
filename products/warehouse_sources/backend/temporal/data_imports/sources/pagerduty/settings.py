from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class PagerDutyEndpointConfig:
    path: str  # Path under the API base URL, e.g. "/incidents"
    envelope_key: str  # Key the list of objects is wrapped under in the response body
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None  # Stable datetime field used to partition (never a mutable field)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # True only when the endpoint exposes a server-side `since` filter on created_at AND
    # accepts a `sort_by=created_at:asc` ordering we control. Both are required for safe
    # incremental sync: the filter bounds the window, the sort guarantees a stable
    # ascending watermark. Endpoints without a controllable sort stay full-refresh so the
    # cursor can't advance past unread rows.
    supports_since: bool = False
    # Names the PagerDuty feature an account needs before this endpoint answers at all, and the
    # single HTTP status that endpoint answers with when the plan lacks it (402 with error code
    # 2014, "required abilities are unavailable", or 404). The two fields are set together: a
    # config with a feature but no status is a mistake, not "accept anything". Kept endpoint-
    # specific rather than a shared {402, 404} set, because the other status is a genuine failure
    # on that endpoint (e.g. a 404 on /teams is a real missing resource, not a plan gate) and must
    # still raise instead of being swallowed as an empty table.
    plan_gated_feature: Optional[str] = None
    plan_gated_status: Optional[int] = None
    # Fan-out child: `parent` names the endpoint whose rows supply the `{id}` in `path`, and that id
    # lands on each child row as `parent_id_column`. Child ids are only documented as unique within
    # their parent, so the parent id belongs in the child's primary key.
    parent: Optional[str] = None
    parent_id_column: Optional[str] = None
    method: Literal["GET", "POST"] = "GET"
    # Static query params sent on every list request of the endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)
    # None when rows do not arrive in ascending order of the endpoint's incremental field.
    sort_mode: Optional[Literal["asc"]] = "asc"


_CREATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

_UPDATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


PAGERDUTY_ENDPOINTS: dict[str, PagerDutyEndpointConfig] = {
    "incidents": PagerDutyEndpointConfig(
        path="/incidents",
        envelope_key="incidents",
        partition_key="created_at",
        incremental_fields=_CREATED_AT_INCREMENTAL,
        # `since`/`until` filter incidents by created_at and `sort_by=created_at:asc` is
        # supported, so incremental sync is safe. Note this only picks up newly *created*
        # incidents — status changes to incidents created before the cursor are not
        # re-fetched (PagerDuty's REST filters key on created_at, not updated_at). Webhooks
        # would be needed for true change capture.
        supports_since=True,
    ),
    "incident_alerts": PagerDutyEndpointConfig(
        path="/incidents/{id}/alerts",
        envelope_key="alerts",
        primary_keys=["incident_id", "id"],
        partition_key="created_at",
        # Full refresh only: the child endpoint has no `since` filter, and an open incident keeps
        # collecting alerts after it was created, so a window on the parent would miss them. The
        # fan-out covers the incidents the parent listing returns, which is its default date range.
        parent="incidents",
        parent_id_column="incident_id",
    ),
    "incident_notes": PagerDutyEndpointConfig(
        path="/incidents/{id}/notes",
        envelope_key="notes",
        primary_keys=["incident_id", "id"],
        partition_key="created_at",
        # Full refresh only, like incident_alerts: responders add notes to an incident long after it
        # was created, and the child endpoint has no `since` filter.
        parent="incidents",
        parent_id_column="incident_id",
    ),
    "incident_analytics": PagerDutyEndpointConfig(
        path="/analytics/raw/incidents",
        envelope_key="data",
        partition_key="created_at",
        incremental_fields=_UPDATED_AT_INCREMENTAL,
        method="POST",
        # The metrics change while an incident is open and after it resolves, and `filters.updated_after`
        # selects the rows the analytics process recomputed. The API sorts only by created_at or
        # seconds_to_resolve, so rows do not arrive in updated_at order.
        sort_mode=None,
    ),
    "log_entries": PagerDutyEndpointConfig(
        path="/log_entries",
        envelope_key="log_entries",
        partition_key="created_at",
        # `/log_entries` accepts a `since` filter but exposes no controllable sort param, so
        # we can't guarantee an ascending watermark. Ship full refresh rather than risk the
        # cursor advancing past unread rows.
    ),
    "change_events": PagerDutyEndpointConfig(
        path="/change_events",
        envelope_key="change_events",
        partition_key="timestamp",
        # `/change_events` accepts `since`/`until` but no sort param, and `timestamp` is set by the
        # tool that emits the event, so a late-arriving event can predate the watermark. Full refresh.
    ),
    "services": PagerDutyEndpointConfig(
        path="/services",
        envelope_key="services",
    ),
    "users": PagerDutyEndpointConfig(
        path="/users",
        envelope_key="users",
    ),
    "teams": PagerDutyEndpointConfig(
        path="/teams",
        envelope_key="teams",
        # PagerDuty gates teams behind an account ability; accounts without it answer 402 with
        # error code 2014 on every /teams request.
        plan_gated_feature="teams",
        plan_gated_status=402,
    ),
    "team_members": PagerDutyEndpointConfig(
        path="/teams/{id}/members",
        envelope_key="members",
        primary_keys=["team_id", "user_id"],
        plan_gated_feature="teams",
        plan_gated_status=402,
        parent="teams",
        parent_id_column="team_id",
    ),
    "escalation_policies": PagerDutyEndpointConfig(
        path="/escalation_policies",
        envelope_key="escalation_policies",
    ),
    "schedules": PagerDutyEndpointConfig(
        path="/schedules",
        envelope_key="schedules",
    ),
    "oncalls": PagerDutyEndpointConfig(
        path="/oncalls",
        envelope_key="oncalls",
        # Without `since`/`until` the API answers the on-call entries at the current time, so each
        # sync replaces the table with who is on call now.
    ),
    "priorities": PagerDutyEndpointConfig(
        path="/priorities",
        envelope_key="priorities",
        # Incident priorities exist only on higher PagerDuty plans. The collection endpoint takes
        # no path parameter, and an account that has the feature but no priority configured still
        # answers 200 with an empty list, so a 404 here can only mean the plan lacks the feature.
        plan_gated_feature="incident priorities",
        plan_gated_status=404,
    ),
    "vendors": PagerDutyEndpointConfig(
        path="/vendors",
        envelope_key="vendors",
    ),
    "business_services": PagerDutyEndpointConfig(
        path="/business_services",
        envelope_key="business_services",
    ),
    "maintenance_windows": PagerDutyEndpointConfig(
        path="/maintenance_windows",
        envelope_key="maintenance_windows",
        # The API documents no default for `filter`, so ask for past, ongoing, and future windows
        # explicitly. There is no `since` filter or sort param, and `start_time` moves when a window
        # is edited, so the table is full refresh with no partition key.
        extra_params={"filter": "all"},
    ),
}

ENDPOINTS = tuple(PAGERDUTY_ENDPOINTS.keys())

# Per-endpoint incremental fields for build_endpoint_schemas; only `incidents` and
# `incident_analytics` expose a server-side filter on their incremental field.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: cfg.incremental_fields for name, cfg in PAGERDUTY_ENDPOINTS.items()
}
