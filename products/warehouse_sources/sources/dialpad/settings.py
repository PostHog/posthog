from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

DIALPAD_BASE_URL = "https://dialpad.com"

# Dialpad's call list returns only concluded calls, and it filters on the start time. A call that
# is still running when a sync reads a newer call would fall below the next watermark, so each
# incremental read starts this far before the watermark. Merge on `call_id` drops the repeats.
CALLS_LOOKBACK = timedelta(hours=3)

# Calls carry their timestamps as epoch milliseconds. The source converts these fields to UTC
# datetimes, so the incremental field and the partition key are real datetimes.
CALL_TIMESTAMP_FIELDS = ("date_connected", "date_ended", "date_rang", "date_started", "event_timestamp")


@dataclass(frozen=True)
class DialpadEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    params: dict[str, Any] = field(default_factory=dict)
    # Server-side filter that takes a start time in epoch milliseconds.
    incremental_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # A creation timestamp that never changes. Never an updated-at field.
    partition_key: Optional[str] = None
    # Text for `get_endpoint_permissions` when the key cannot read this endpoint.
    access_requirement: Optional[str] = None
    # False when the endpoint returns the whole collection in one response, with no `cursor`.
    paginated: bool = True
    # Set for an endpoint that runs once per row of a parent endpoint.
    fanout: Optional[DependentEndpointConfig] = None
    # The path that `validate_credentials` and `get_endpoint_permissions` read, when `path` needs a parent id.
    probe_path: Optional[str] = None

    @property
    def readable_path(self) -> str:
        return self.probe_path or self.path


DIALPAD_ENDPOINTS: dict[str, DialpadEndpointConfig] = {
    "calls": DialpadEndpointConfig(
        name="calls",
        path="/api/v2/call",
        primary_keys=["call_id"],
        # Without `include_anonymized`, the list drops the calls of deleted users.
        params={"include_anonymized": "true"},
        incremental_param="started_after",
        incremental_fields=[
            {
                "label": "date_started",
                "type": IncrementalFieldType.DateTime,
                "field": "date_started",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_key="date_started",
        access_requirement="a company API key with the `calls:list` scope",
    ),
    "call_centers": DialpadEndpointConfig(name="call_centers", path="/api/v2/callcenters"),
    "call_labels": DialpadEndpointConfig(
        name="call_labels",
        path="/api/v2/calllabels",
        primary_keys=["label"],
        paginated=False,
    ),
    "channels": DialpadEndpointConfig(name="channels", path="/api/v2/channels"),
    "coaching_teams": DialpadEndpointConfig(name="coaching_teams", path="/api/v2/coachingteams"),
    # Without `include_local`, the list holds only the shared company contacts.
    "contacts": DialpadEndpointConfig(name="contacts", path="/api/v2/contacts", params={"include_local": "true"}),
    "departments": DialpadEndpointConfig(name="departments", path="/api/v2/departments"),
    "numbers": DialpadEndpointConfig(
        name="numbers",
        path="/api/v2/numbers",
        primary_keys=["number"],
        access_requirement="a company admin API key",
    ),
    "offices": DialpadEndpointConfig(name="offices", path="/api/v2/offices"),
    "rooms": DialpadEndpointConfig(name="rooms", path="/api/v2/rooms"),
    # `state=all` also returns suspended, cancelled and deleted users.
    "users": DialpadEndpointConfig(
        name="users",
        path="/api/v2/users",
        params={"state": "all"},
        partition_key="date_added",
    ),
}

# Scorecards belong to one target. The list takes the target type and id, so the source lists the
# targets of each type first. Each state is asked for by name, so no state depends on the API default.
SCORECARDS_PATH = "/api/v2/scorecards"
SCORECARD_TARGETS: tuple[tuple[str, str], ...] = (
    ("office", "offices"),
    ("callcenter", "call_centers"),
    ("coachingteam", "coaching_teams"),
)
SCORECARD_STATES = ("active", "archived", "draft")


def _fanout(parent_name: str, parent_id_column: str) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name=parent_name,
        resolve_param="id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": parent_id_column},
        parent_params=dict(DIALPAD_ENDPOINTS[parent_name].params),
        # A parent deleted between the parent list and the child request has no children left.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


DIALPAD_ENDPOINTS.update(
    {
        # Operators are users and rooms, so each row carries `operator_type`. A user row has its own
        # `office_id`, so the office that the row is an operator of is `parent_office_id`.
        "call_center_operators": DialpadEndpointConfig(
            name="call_center_operators",
            path="/api/v2/callcenters/{id}/operators",
            primary_keys=["call_center_id", "operator_type", "id"],
            paginated=False,
            fanout=_fanout("call_centers", "call_center_id"),
            probe_path="/api/v2/callcenters",
        ),
        "channel_members": DialpadEndpointConfig(
            name="channel_members",
            path="/api/v2/channels/{id}/members",
            primary_keys=["channel_id", "id"],
            fanout=_fanout("channels", "channel_id"),
            probe_path="/api/v2/channels",
        ),
        "office_operators": DialpadEndpointConfig(
            name="office_operators",
            path="/api/v2/offices/{id}/operators",
            primary_keys=["parent_office_id", "operator_type", "id"],
            paginated=False,
            fanout=_fanout("offices", "parent_office_id"),
            probe_path="/api/v2/offices",
        ),
        "scorecards": DialpadEndpointConfig(
            name="scorecards",
            path=SCORECARDS_PATH,
            primary_keys=["target_type", "target_id", "id"],
            partition_key="date_created",
            probe_path="/api/v2/offices",
        ),
    }
)

ENDPOINTS = tuple(DIALPAD_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DIALPAD_ENDPOINTS.items() if config.incremental_fields
}
