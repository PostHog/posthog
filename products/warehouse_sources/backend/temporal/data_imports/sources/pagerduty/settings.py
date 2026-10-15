from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class PagerDutyEndpointConfig:
    path: str  # Path under the API base URL, e.g. "/incidents"
    envelope_key: str  # Key the list of objects is wrapped under in the response body
    primary_key: str = "id"
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


_CREATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
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
    "log_entries": PagerDutyEndpointConfig(
        path="/log_entries",
        envelope_key="log_entries",
        partition_key="created_at",
        # `/log_entries` accepts a `since` filter but exposes no controllable sort param, so
        # we can't guarantee an ascending watermark. Ship full refresh rather than risk the
        # cursor advancing past unread rows.
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
    "escalation_policies": PagerDutyEndpointConfig(
        path="/escalation_policies",
        envelope_key="escalation_policies",
    ),
    "schedules": PagerDutyEndpointConfig(
        path="/schedules",
        envelope_key="schedules",
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
}

ENDPOINTS = tuple(PAGERDUTY_ENDPOINTS.keys())

# Per-endpoint incremental fields for build_endpoint_schemas; only `incidents` exposes a
# server-side `since` filter with a controllable sort, so only it is incremental-capable.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: cfg.incremental_fields for name, cfg in PAGERDUTY_ENDPOINTS.items()
}
