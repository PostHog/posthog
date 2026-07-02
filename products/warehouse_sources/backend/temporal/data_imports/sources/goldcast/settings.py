from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GoldcastEndpointConfig:
    name: str
    # Path relative to the Goldcast base URL. For fan-out endpoints this is a template with an
    # `{event}` placeholder that is filled per parent event id.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by. Left None when the endpoint exposes no such
    # field (never partition on `updated_at`, which rewrites partitions on every sync).
    partition_key: Optional[str] = None
    # When True this is a per-event fan-out endpoint: iterate every event id from the events
    # endpoint and request `path` once per event. `path` must contain an `{event}` placeholder.
    fan_out_over_events: bool = False
    # For fan-out children, the parent event id is written into each row under this key so the
    # composite primary key is unique table-wide (child ids are only guaranteed unique per parent).
    parent_event_field: str = "event"
    should_sync_default: bool = True


# Goldcast's public API exposes full collections with no pagination and no server-side
# modified-at/updated-at filter, so every endpoint is full refresh only. `agenda_items` carries no
# creation timestamp, so it is left unpartitioned; every other endpoint partitions on `created_at`.
GOLDCAST_ENDPOINTS: dict[str, GoldcastEndpointConfig] = {
    "organizations": GoldcastEndpointConfig(
        name="organizations",
        path="/core/organization/",
        partition_key="created_at",
    ),
    "events": GoldcastEndpointConfig(
        name="events",
        path="/event/",
        partition_key="created_at",
    ),
    "agenda_items": GoldcastEndpointConfig(
        name="agenda_items",
        path="/event/agenda-item/",
    ),
    "discussion_groups": GoldcastEndpointConfig(
        name="discussion_groups",
        path="/event/discussion-groups/",
        partition_key="created_at",
    ),
    "tracks": GoldcastEndpointConfig(
        name="tracks",
        path="/event/tracks/",
        partition_key="created_at",
    ),
    # Fan-out: one request per event id. The event id is in the URL path and not present on the
    # returned webinar rows, so it is injected under `event` to form the composite primary key.
    "webinars": GoldcastEndpointConfig(
        name="webinars",
        path="/event/webinars/{event}/",
        primary_keys=["event", "id"],
        partition_key="created_at",
        fan_out_over_events=True,
    ),
    # Fan-out: one request per event id, passed as an `?event=` query param. Rows already carry an
    # `event` field; it is re-stamped defensively so the composite key is always populated.
    "event_members": GoldcastEndpointConfig(
        name="event_members",
        path="/event/event-members/?event={event}",
        primary_keys=["event", "id"],
        partition_key="created_at",
        fan_out_over_events=True,
    ),
}

ENDPOINTS = tuple(GOLDCAST_ENDPOINTS.keys())
