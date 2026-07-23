from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class XmattersEndpointConfig:
    path: str  # Path under the API base URL, e.g. "/events"
    primary_key: str = "id"
    partition_key: Optional[str] = None  # Stable datetime field used to partition (never a mutable field)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # True only when the endpoint exposes a server-side time-window filter (`from`) on the
    # created timestamp AND accepts a `sortBy`/`sortOrder` ordering we control. Both are
    # required for safe incremental sync: the filter bounds the window and the ascending
    # sort guarantees a stable watermark. Reference/config endpoints stay full-refresh.
    supports_from: bool = False


_CREATED_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created",
        "type": IncrementalFieldType.DateTime,
        "field": "created",
        "field_type": IncrementalFieldType.DateTime,
    },
]


# Top-level list endpoints. xMatters also exposes per-parent resources (e.g. /audits requires
# an eventId, /on-call and /shifts require a group), which need fan-out and are not included
# here. Every list response is wrapped in a `data` array with `count`, `total`, and `links`.
XMATTERS_ENDPOINTS: dict[str, XmattersEndpointConfig] = {
    "events": XmattersEndpointConfig(
        path="/events",
        partition_key="created",
        incremental_fields=_CREATED_INCREMENTAL,
        # `/events` accepts `from`/`to` (ISO 8601) that filter by the event's created time and a
        # `sortBy=START_TIME&sortOrder=ASCENDING` ordering we control, so incremental sync is safe.
        # Note this picks up newly *created* events only — status changes to events created before
        # the cursor are not re-fetched (xMatters filters on created time, not an updated cursor).
        supports_from=True,
    ),
    "people": XmattersEndpointConfig(
        path="/people",
    ),
    "groups": XmattersEndpointConfig(
        path="/groups",
    ),
    "devices": XmattersEndpointConfig(
        path="/devices",
    ),
    "sites": XmattersEndpointConfig(
        path="/sites",
    ),
    "roles": XmattersEndpointConfig(
        path="/roles",
    ),
    "dynamic_teams": XmattersEndpointConfig(
        path="/dynamic-teams",
    ),
    "plans": XmattersEndpointConfig(
        path="/plans",
    ),
    "subscriptions": XmattersEndpointConfig(
        path="/subscriptions",
    ),
}

ENDPOINTS = tuple(XMATTERS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in XMATTERS_ENDPOINTS.items() if config.incremental_fields
}
