from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class DixaFanoutConfig:
    """Wiring for a child endpoint fetched once per row of a parent endpoint."""

    parent: str
    # Field on the parent row that fills the child path placeholder.
    parent_id_field: str
    # Column the parent id is injected as on every child row.
    child_key: str
    # Parent field carried onto each child row to act as the child's incremental cursor.
    parent_cursor_field: Optional[str] = None
    child_cursor_key: Optional[str] = None


@frozen
class DixaEndpointConfig:
    name: str
    path: str
    # Dixa has two API surfaces: the main API (dev.dixa.io/v1, cursor-paginated
    # dimension tables) and the Exports API (exports.dixa.io/v1, time-windowed
    # bulk arrays with strict per-minute rate limits).
    surface: Literal["main", "export"]
    primary_key: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning (Unix ms).
    partition_key: Optional[str] = None
    fanout: Optional[DixaFanoutConfig] = None
    # Main-surface query param carrying the incremental watermark, when the
    # endpoint has a server-side time filter of its own.
    incremental_param: Optional[str] = None
    # Fields Dixa serialises as `2021-12-01T12:46:36.581Z[GMT]` — the trailing
    # zone id is stripped so the column lands as a real timestamp.
    datetime_fields: tuple[str, ...] = ()


CONVERSATION_FANOUT = DixaFanoutConfig(
    parent="conversations",
    parent_id_field="id",
    child_key="conversation_id",
    parent_cursor_field="updated_at",
    child_cursor_key="conversation_updated_at",
)

# Fan-out children inherit the parent conversation's `updated_at` as their cursor: it is the
# value the Exports API filters on, so an incremental run only re-fetches conversations that
# changed since the last sync.
CONVERSATION_FANOUT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "conversation_updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "conversation_updated_at",
        "field_type": IncrementalFieldType.Integer,
    },
]


DIXA_ENDPOINTS: dict[str, DixaEndpointConfig] = {
    "conversations": DixaEndpointConfig(
        name="conversations",
        path="/conversation_export",
        surface="export",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "conversation_messages": DixaEndpointConfig(
        name="conversation_messages",
        path="/conversations/{}/messages",
        surface="main",
        primary_key=["conversation_id", "id"],
        fanout=CONVERSATION_FANOUT,
        incremental_fields=CONVERSATION_FANOUT_INCREMENTAL_FIELDS,
        datetime_fields=("createdAt",),
    ),
    "conversation_ratings": DixaEndpointConfig(
        name="conversation_ratings",
        path="/conversations/{}/ratings",
        surface="main",
        # A multi-question survey returns one row per question, all sharing the survey id, so
        # the rating type is part of what makes a row unique.
        primary_key=["conversation_id", "id", "ratingType"],
        fanout=CONVERSATION_FANOUT,
        incremental_fields=CONVERSATION_FANOUT_INCREMENTAL_FIELDS,
    ),
    "conversation_activity_log": DixaEndpointConfig(
        name="conversation_activity_log",
        path="/conversations/activitylog",
        surface="main",
        incremental_param="fromDatetime",
        incremental_fields=[
            {
                "label": "activityTimestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "activityTimestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        datetime_fields=("activityTimestamp",),
    ),
    "agents": DixaEndpointConfig(
        name="agents",
        path="/agents",
        surface="main",
    ),
    "endusers": DixaEndpointConfig(
        name="endusers",
        path="/endusers",
        surface="main",
    ),
    "queues": DixaEndpointConfig(
        name="queues",
        path="/queues",
        surface="main",
    ),
    "tags": DixaEndpointConfig(
        name="tags",
        path="/tags",
        surface="main",
    ),
    "teams": DixaEndpointConfig(
        name="teams",
        path="/teams",
        surface="main",
    ),
    "team_members": DixaEndpointConfig(
        name="team_members",
        path="/teams/{}/agents",
        surface="main",
        primary_key=["team_id", "id"],
        fanout=DixaFanoutConfig(parent="teams", parent_id_field="id", child_key="team_id"),
    ),
}

ENDPOINTS = tuple(DIXA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DIXA_ENDPOINTS.items() if config.incremental_fields
}
