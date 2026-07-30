from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HumanitixEndpointConfig:
    name: str
    path: str
    # Key of the row array in the paginated response envelope; it differs per endpoint
    # (e.g. `events` for /events, `tags` for /tags) even though the envelope shape is identical.
    list_key: str
    # Humanitix objects are Mongo documents, so `_id` is a stable, globally unique primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["_id"])
    # A stable (never-rewritten) datetime field to partition by. Left unset — every endpoint is
    # full refresh only, so there is no partition cursor to advance.
    partition_key: Optional[str] = None


# Humanitix Public API list endpoints. Only genuinely top-level, account-scoped list endpoints are
# included: `/events` and `/tags`. Orders and tickets are nested under `/events/{eventId}/...`
# (fan-out per event) and the `/global/*` endpoints return the public marketplace catalog rather
# than the account's own data, so none of those are exposed here.
# All are full-refresh only: the list endpoints expose no server-side incremental cursor to advance.
HUMANITIX_ENDPOINTS: dict[str, HumanitixEndpointConfig] = {
    "events": HumanitixEndpointConfig(name="events", path="/events", list_key="events"),
    "tags": HumanitixEndpointConfig(name="tags", path="/tags", list_key="tags"),
}

ENDPOINTS = tuple(HUMANITIX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list] = {}
