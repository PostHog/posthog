from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Better Stack Uptime API. Standard collections live under /v2; incidents moved to /v3 (the /v2
# incidents route still exists, but /v3 is the documented current version). Confirmed against the
# live API: real routes return 401 on a bad token, unknown routes return 404.
BETTER_STACK_BASE_URL = "https://uptime.betterstack.com/api"


@dataclass
class BetterStackEndpointConfig:
    name: str
    path: str
    # Only True where Better Stack exposes a genuine server-side date filter. Today that's the
    # incidents endpoint's `from`/`to` params (YYYY-MM-DD, by incident start date).
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field to partition by — a creation/start timestamp, never `updated_at`.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Documented default is 50 everywhere; standard v2 collections accept up to 250, the v3
    # incidents endpoint caps at 50.
    page_size: int = 50
    should_sync_default: bool = True


_STARTED_AT: list[IncrementalField] = [
    {
        "label": "started_at",
        "type": IncrementalFieldType.DateTime,
        "field": "started_at",
        "field_type": IncrementalFieldType.DateTime,
    }
]

# Endpoint catalog — the streams a reliability team actually wants from an uptime/incident
# platform: monitors and heartbeats (plus their groups), incident history, on-call calendars,
# escalation policies, and status pages. Every path was confirmed to be a real route against the
# live API.
BETTER_STACK_ENDPOINTS: dict[str, BetterStackEndpointConfig] = {
    # Incident history is the high-volume stream — incremental via the server-side `from` date
    # filter on the incident start date.
    "incidents": BetterStackEndpointConfig(
        name="incidents",
        path="/v3/incidents",
        supports_incremental=True,
        incremental_fields=_STARTED_AT,
        partition_key="started_at",
        page_size=50,
    ),
    "monitors": BetterStackEndpointConfig(
        name="monitors",
        path="/v2/monitors",
        partition_key="created_at",
        page_size=250,
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
    # Small configuration collections — page size left at the documented default of 50 since
    # their maximums aren't documented.
    "on_calls": BetterStackEndpointConfig(
        name="on_calls",
        path="/v2/on-calls",
    ),
    "escalation_policies": BetterStackEndpointConfig(
        name="escalation_policies",
        path="/v2/policies",
    ),
}

ENDPOINTS = tuple(BETTER_STACK_ENDPOINTS.keys())
