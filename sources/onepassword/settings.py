from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_TIMESTAMP_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "timestamp",
        "type": IncrementalFieldType.DateTime,
        "field": "timestamp",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class OnePasswordEndpointConfig:
    name: str
    path: str
    # The Events Reporting feature scope the bearer token needs for this endpoint, as reported
    # by GET /api/v2/auth/introspect.
    feature: str
    # Every Events API stream is an immutable event log keyed by the event's `uuid`, with the
    # server-side `start_time` filter on `timestamp` as the incremental cursor.
    primary_keys: list[str] = field(default_factory=lambda: ["uuid"])
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_TIMESTAMP_INCREMENTAL_FIELDS))
    partition_key: str = "timestamp"
    should_sync_default: bool = True


# All three streams share the same cursor-paginated POST contract: the first request carries a
# ResetCursor ({limit, start_time}), subsequent requests carry the returned cursor, and the
# response is {cursor, has_more, items}. See https://developer.1password.com/docs/events-api/reference.
ONEPASSWORD_ENDPOINTS: dict[str, OnePasswordEndpointConfig] = {
    "sign_in_attempts": OnePasswordEndpointConfig(
        name="sign_in_attempts",
        path="/api/v2/signinattempts",
        feature="signinattempts",
    ),
    "item_usages": OnePasswordEndpointConfig(
        name="item_usages",
        path="/api/v2/itemusages",
        feature="itemusages",
    ),
    "audit_events": OnePasswordEndpointConfig(
        name="audit_events",
        path="/api/v2/auditevents",
        feature="auditevents",
    ),
}

ENDPOINTS = tuple(ONEPASSWORD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ONEPASSWORD_ENDPOINTS.items()
}
