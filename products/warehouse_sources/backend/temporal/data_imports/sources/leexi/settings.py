from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

LEEXI_BASE_URL = "https://public-api.leexi.ai/v1"

# Leexi caps list pages at 100 items (`items` param, default 10).
PAGE_SIZE = 100

# Every Leexi resource is identified by its `uuid`.
PRIMARY_KEY = "uuid"


@dataclass(frozen=True)
class LeexiEndpointConfig:
    name: str
    # Relative path appended to the API base. The fan-out child carries a `{call_uuid}`
    # placeholder that the framework binds from the parent row per request.
    path: str
    # Stable creation-time field used for datetime partitioning. Never an `updated_at`-style
    # field — partitions would rewrite on every sync.
    partition_key: str
    # Explicit `order` param for endpoints that document one; users/teams document none.
    order: str | None = None
    # Static query params sent on every request.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Set for the fan-out child (`call_notes`): the endpoint whose rows resolve the path.
    fan_out_parent: str | None = None


LEEXI_ENDPOINTS: dict[str, LeexiEndpointConfig] = {
    "calls": LeexiEndpointConfig(
        name="calls",
        path="/calls",
        partition_key="created_at",
        order="created_at asc",
        # Opt the plain-text transcript into each call row.
        extra_params={"with_simple_transcript": "true"},
    ),
    "call_notes": LeexiEndpointConfig(
        name="call_notes",
        # `call_uuid` is a query param, but the framework binds resolve params via path
        # placeholders, so it rides in the path template (same pattern as Asana's
        # `/projects?workspace={workspace_gid}`).
        path="/call_notes?call_uuid={call_uuid}",
        partition_key="created_at",
        fan_out_parent="calls",
    ),
    "meeting_events": LeexiEndpointConfig(
        name="meeting_events",
        path="/meeting_events",
        partition_key="created_at",
        order="created_at asc",
    ),
    "users": LeexiEndpointConfig(
        name="users",
        path="/users",
        partition_key="created_at",
    ),
    "teams": LeexiEndpointConfig(
        name="teams",
        path="/teams",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(LEEXI_ENDPOINTS.keys())

# /calls is the only endpoint with a genuine server-side timestamp filter (`date_filter` +
# `from`/`to`, orderable by the same fields). /meeting_events only filters on
# start_time/end_time, which aren't update cursors (a rescheduled or late-created event
# would be missed), and the remaining endpoints document no timestamp filters — those all
# ship full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "calls": [
        incremental_field("updated_at"),
        incremental_field("created_at"),
        incremental_field("performed_at"),
    ],
}

# `date_filter` and `order` accept exactly these fields on /calls.
CALLS_INCREMENTAL_FIELD_NAMES = tuple(f["field"] for f in INCREMENTAL_FIELDS["calls"])

# Permission scope each endpoint's requests require on the API key.
ENDPOINT_SCOPES: dict[str, str] = {
    "calls": "read_calls",
    "call_notes": "read_calls",
    "meeting_events": "read_meeting_events",
    "users": "read_users",
    "teams": "read_teams",
}

# Path probed (with items=1) to check an endpoint's scope. /call_notes requires a
# `call_uuid`, so its scope is probed via /calls (both need `read_calls`).
ENDPOINT_PROBE_PATHS: dict[str, str] = {
    "calls": "/calls",
    "call_notes": "/calls",
    "meeting_events": "/meeting_events",
    "users": "/users",
    "teams": "/teams",
}
