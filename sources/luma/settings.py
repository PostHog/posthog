from dataclasses import dataclass, field


@dataclass(frozen=True)
class LumaEndpointConfig:
    name: str
    path: str
    # Luma wraps some list entries in an envelope ({"api_id": ..., "event": {...}}); when set, rows
    # are flattened to this nested object (which carries its own `api_id`).
    nested_key: str | None = None
    # Luma object identifiers (`evt-...`, `gst-...`, ...) are globally unique `api_id`s.
    primary_keys: list[str] = field(default_factory=lambda: ["api_id"])
    # Fan-out children are fetched per event, iterating the events list as the parent.
    fan_out_over_events: bool = False
    # Query param carrying the parent event id, also written onto each child row for joins and keys.
    event_id_param: str = "event_api_id"
    # Some newer list endpoints return every entry in one response and take no pagination params.
    paginated: bool = True


EVENTS_PATH = "/public/v1/calendar/list-events"
GUESTS_PATH = "/public/v1/event/get-guests"
BLASTS_PATH = "/v1/events/blasts/list"

# Luma public API list endpoints. All are full refresh only: pagination is cursor-based
# (`pagination_cursor` + `has_more`/`next_cursor`) and there is no server-side updated-since filter.
# list-events only supports `before`/`after` bounds on the event *start* time, which is not a
# modification cursor, so it cannot drive a reliable incremental sync.
LUMA_ENDPOINTS: dict[str, LumaEndpointConfig] = {
    "events": LumaEndpointConfig(name="events", path=EVENTS_PATH, nested_key="event"),
    # Guest api_ids are registration-scoped, but rows aggregate across every event, so the parent
    # event id is part of the key (and useful for joins back to events).
    "guests": LumaEndpointConfig(
        name="guests",
        path=GUESTS_PATH,
        nested_key="guest",
        primary_keys=["event_api_id", "api_id"],
        fan_out_over_events=True,
    ),
    # Blasts (emails to an event's guests) are keyed by `id` on the current API, not the legacy `api_id`.
    "event_blasts": LumaEndpointConfig(
        name="event_blasts",
        path=BLASTS_PATH,
        primary_keys=["event_id", "id"],
        fan_out_over_events=True,
        event_id_param="event_id",
        paginated=False,
    ),
    "people": LumaEndpointConfig(name="people", path="/public/v1/calendar/list-people"),
    "person_tags": LumaEndpointConfig(name="person_tags", path="/public/v1/calendar/list-person-tags"),
}

ENDPOINTS = tuple(LUMA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
