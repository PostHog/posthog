from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Better Stack Uptime API. Standard collections live under /v2; incidents moved to /v3 (the /v2
# incidents route still exists, but /v3 is the documented current version). Confirmed against the
# live API: real routes return 401 on a bad token, unknown routes return 404.
BETTER_STACK_BASE_URL = "https://uptime.betterstack.com/api"
# Team members and organization roles are account-level, so Better Stack serves them from the main
# host rather than the Uptime subdomain. Confirmed the same way: the Uptime host 404s both routes
# while this one returns 401 on a bad token.
BETTER_STACK_ORG_BASE_URL = "https://betterstack.com/api"

# A parent row deleted between the parent listing and the child fetch 404s. Skip that parent
# instead of failing the whole fan-out.
_SKIP_MISSING_PARENT: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


@dataclass(frozen=True)
class BetterStackEndpointConfig:
    name: str
    path: str
    # Host serving this resource. Defaults to the Uptime API.
    base_url: str = BETTER_STACK_BASE_URL
    # Only True where Better Stack exposes a genuine server-side date filter on this endpoint's
    # own request. Today that's the incidents endpoint's `from`/`to` params (YYYY-MM-DD, by
    # incident start date). A fan-out child leaves this False even when it tracks a cursor — its
    # request set is bounded through the parent listing instead.
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field to partition by — a creation/start timestamp, never `updated_at`.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Documented default is 50 everywhere; standard v2 collections accept up to 250, the v3
    # incidents endpoint caps at 50.
    page_size: int = 50
    # Most collections wrap their rows in the JSON:API `data` envelope; the on-call ones do not.
    data_selector: str = "data"
    should_sync_default: bool = True
    # Set where the resource only exists per parent row (e.g. /monitors/{monitor_id}/sla).
    fanout: Optional[DependentEndpointConfig] = None

    @property
    def default_incremental_field(self) -> str | None:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


def _datetime_field(name: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.DateTime,
            "field": name,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


_MONITOR_FANOUT = DependentEndpointConfig(
    parent_name="monitors",
    resolve_param="monitor_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "monitor_id"},
    child_response_actions=_SKIP_MISSING_PARENT,
)

_HEARTBEAT_FANOUT = DependentEndpointConfig(
    parent_name="heartbeats",
    resolve_param="heartbeat_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "heartbeat_id"},
    child_response_actions=_SKIP_MISSING_PARENT,
)

_ON_CALL_FANOUT = DependentEndpointConfig(
    parent_name="on_calls",
    resolve_param="schedule_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "on_call_id"},
    child_response_actions=_SKIP_MISSING_PARENT,
)

_STATUS_PAGE_FANOUT = DependentEndpointConfig(
    parent_name="status_pages",
    resolve_param="status_page_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "status_page_id"},
    child_response_actions=_SKIP_MISSING_PARENT,
)

# Endpoint catalog — the streams a reliability team actually wants from an uptime/incident
# platform: monitors and heartbeats (plus their groups), monitor availability and latency,
# incident history and commentary, on-call calendars, escalation policies, status pages, and the
# people lookups the rest of them reference. Every path was confirmed to be a real route against
# the live API.
BETTER_STACK_ENDPOINTS: dict[str, BetterStackEndpointConfig] = {
    # Incident history is the high-volume stream — incremental via the server-side `from` date
    # filter on the incident start date.
    "incidents": BetterStackEndpointConfig(
        name="incidents",
        path="/v3/incidents",
        supports_incremental=True,
        incremental_fields=_datetime_field("started_at"),
        partition_key="started_at",
        page_size=50,
    ),
    # Acknowledgement and resolution commentary, one request per incident. The endpoint returns
    # every comment at once (no pagination, no time filter), so it merges on its primary key and
    # bounds its request set through the incidents listing instead.
    "incident_comments": BetterStackEndpointConfig(
        name="incident_comments",
        path="/v2/incidents/{incident_id}/comments",
        incremental_fields=_datetime_field("created_at"),
        partition_key="created_at",
        primary_keys=["incident_id", "id"],
        should_sync_default=False,
        fanout=DependentEndpointConfig(
            parent_name="incidents",
            resolve_param="incident_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "incident_id"},
            child_response_actions=_SKIP_MISSING_PARENT,
        ),
    ),
    "monitors": BetterStackEndpointConfig(
        name="monitors",
        path="/v2/monitors",
        partition_key="created_at",
        page_size=250,
    ),
    # Uptime percentage and downtime totals per monitor — the product's headline metric, which
    # the monitors table does not carry. One row per monitor, recomputed every sync.
    "monitor_availability": BetterStackEndpointConfig(
        name="monitor_availability",
        path="/v2/monitors/{monitor_id}/sla",
        primary_keys=["monitor_id"],
        fanout=_MONITOR_FANOUT,
    ),
    # Latency time series per monitor and region. Better Stack only serves the last 24 hours and
    # takes no time filter, so each sync re-reads that window and merges it onto the history
    # already collected; appending would duplicate the overlap.
    "monitor_response_times": BetterStackEndpointConfig(
        name="monitor_response_times",
        path="/v2/monitors/{monitor_id}/response-times",
        incremental_fields=_datetime_field("at"),
        partition_key="at",
        primary_keys=["monitor_id", "region", "at"],
        should_sync_default=False,
        fanout=_MONITOR_FANOUT,
    ),
    "monitor_groups": BetterStackEndpointConfig(
        name="monitor_groups",
        path="/v2/monitor-groups",
        page_size=250,
    ),
    "heartbeats": BetterStackEndpointConfig(
        name="heartbeats",
        path="/v2/heartbeats",
        partition_key="created_at",
        page_size=250,
    ),
    # Recomputed every sync: the endpoint summarizes the heartbeat's whole life and takes no filter.
    "heartbeat_availability": BetterStackEndpointConfig(
        name="heartbeat_availability",
        path="/v2/heartbeats/{heartbeat_id}/availability",
        primary_keys=["heartbeat_id"],
        fanout=_HEARTBEAT_FANOUT,
    ),
    "heartbeat_groups": BetterStackEndpointConfig(
        name="heartbeat_groups",
        path="/v2/heartbeat-groups",
        page_size=250,
    ),
    "status_pages": BetterStackEndpointConfig(
        name="status_pages",
        path="/v2/status-pages",
        page_size=250,
    ),
    "status_page_resources": BetterStackEndpointConfig(
        name="status_page_resources",
        path="/v2/status-pages/{status_page_id}/resources",
        primary_keys=["status_page_id", "id"],
        fanout=_STATUS_PAGE_FANOUT,
    ),
    # Small configuration collections — page size left at the documented default of 50 since
    # their maximums aren't documented.
    "on_calls": BetterStackEndpointConfig(
        name="on_calls",
        path="/v2/on-calls",
    ),
    # Re-read whole every sync rather than merged: editing a schedule rewrites its future shifts,
    # and a merge would keep rows for shifts that no longer exist.
    "on_call_events": BetterStackEndpointConfig(
        name="on_call_events",
        path="/v2/on-calls/{schedule_id}/events",
        # Rows arrive under `events`, and the endpoint does not paginate.
        data_selector="events",
        partition_key="starts_at",
        primary_keys=["on_call_id", "id"],
        fanout=_ON_CALL_FANOUT,
    ),
    "on_call_rotations": BetterStackEndpointConfig(
        name="on_call_rotations",
        path="/v2/on-calls/{schedule_id}/rotation",
        # A bare object with no envelope and no id of its own, so the schedule id is the key. A
        # schedule with no rotation defined answers 404, which the fan-out skips.
        data_selector="$",
        primary_keys=["on_call_id"],
        fanout=_ON_CALL_FANOUT,
    ),
    "escalation_policies": BetterStackEndpointConfig(
        name="escalation_policies",
        path="/v2/policies",
    ),
    # The routes still carry the feature's former name, `urgencies`.
    "severities": BetterStackEndpointConfig(
        name="severities",
        path="/v2/urgencies",
    ),
    "severity_groups": BetterStackEndpointConfig(
        name="severity_groups",
        path="/v2/urgency-groups",
    ),
    # People lookups resolving the user ids incidents, on-call calendars and escalation policies
    # reference. Both are account-level, so they live on the other host.
    "team_members": BetterStackEndpointConfig(
        name="team_members",
        path="/v2/team-members",
        base_url=BETTER_STACK_ORG_BASE_URL,
        # The collection mixes accepted members with pending invitations, whose ids come from
        # separate id spaces — `type` keeps two rows from collapsing onto one key.
        primary_keys=["id", "type"],
    ),
    "roles": BetterStackEndpointConfig(
        name="roles",
        path="/v2/roles",
        base_url=BETTER_STACK_ORG_BASE_URL,
    ),
}

ENDPOINTS = tuple(BETTER_STACK_ENDPOINTS.keys())
