from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class GoldcastEndpointConfig:
    name: str
    # Path relative to the Goldcast base URL. For fan-out endpoints this is a template with a
    # `{<parent_field>}` placeholder that is filled per parent id.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by. Left None when the endpoint exposes no such
    # field (never partition on `updated_at`, which rewrites partitions on every sync).
    partition_key: Optional[str] = None
    # When set this is a fan-out endpoint: iterate every id from this parent endpoint and request
    # `path` once per parent. `path` must contain a `{<parent_field>}` placeholder.
    fan_out_parent: Optional[str] = None
    # For fan-out children, the parent id is written into each row under this key so the
    # composite primary key is unique table-wide (child ids are only guaranteed unique per parent).
    parent_field: str = "event"
    should_sync_default: bool = True


# Goldcast list endpoints return the full collection as a bare array when no `limit` is sent, and
# expose no server-side modified-at/updated-at filter, so every endpoint is full refresh only. `agenda_items` carries no
# creation timestamp, nor do `broadcast_polls` and `speakers`, so those are left unpartitioned; every
# other endpoint partitions on `created_at`.
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
        fan_out_parent="events",
    ),
    # Fan-out: one request per event id, passed as an `?event=` query param. Rows already carry an
    # `event` field; it is re-stamped defensively so the composite key is always populated.
    "event_members": GoldcastEndpointConfig(
        name="event_members",
        path="/event/event-members/?event={event}",
        primary_keys=["event", "id"],
        partition_key="created_at",
        fan_out_parent="events",
    ),
    "broadcasts": GoldcastEndpointConfig(
        name="broadcasts",
        path="/event/broadcasts/",
        partition_key="created_at",
    ),
    # Fan-out: one request per broadcast id. Poll ids are not documented as globally unique, so the
    # parent broadcast id is injected under `broadcast` for the composite key.
    "broadcast_polls": GoldcastEndpointConfig(
        name="broadcast_polls",
        path="/event/broadcasts/{broadcast}/polls/",
        primary_keys=["broadcast", "id"],
        fan_out_parent="broadcasts",
        parent_field="broadcast",
    ),
    "ticket_types": GoldcastEndpointConfig(
        name="ticket_types",
        path="/event/ticket-type/",
        partition_key="created_at",
    ),
    # Fan-out: one request per event id. A speaker can appear on several events, so the parent event
    # id is part of the key.
    "speakers": GoldcastEndpointConfig(
        name="speakers",
        path="/event/{event}/public/v1/speakers/",
        primary_keys=["event", "id"],
        fan_out_parent="events",
    ),
}

ENDPOINTS = tuple(GOLDCAST_ENDPOINTS.keys())
