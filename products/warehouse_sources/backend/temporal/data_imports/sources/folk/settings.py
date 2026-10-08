from dataclasses import dataclass, field
from typing import Optional

# Folk's public API (developer.folk.app). All list endpoints share one shape: bearer auth, a
# `{"data": {"items": [...], "pagination": {"nextLink": ...}}}` envelope, and cursor pagination
# via `limit` + `cursor` params (the next cursor arrives as the full `nextLink` URL).
FOLK_BASE_URL = "https://api.folk.app"


@dataclass(frozen=True)
class FolkEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp to partition by; None where the resource carries no timestamp
    # (groups and users).
    partition_key: Optional[str] = None


# Every endpoint is full refresh: Folk exposes no updatedAt filter on any list endpoint, its
# createdAt filter is day-precision only, and no list endpoint takes a sort param, so an
# incremental watermark could neither catch updates nor checkpoint safely.
FOLK_ENDPOINTS: dict[str, FolkEndpointConfig] = {
    "people": FolkEndpointConfig(
        name="people",
        path="/v1/people",
        partition_key="createdAt",
    ),
    "companies": FolkEndpointConfig(
        name="companies",
        path="/v1/companies",
        partition_key="createdAt",
    ),
    "groups": FolkEndpointConfig(
        name="groups",
        path="/v1/groups",
    ),
    "users": FolkEndpointConfig(
        name="users",
        path="/v1/users",
    ),
    "notes": FolkEndpointConfig(
        name="notes",
        path="/v1/notes",
        partition_key="createdAt",
    ),
    "tasks": FolkEndpointConfig(
        name="tasks",
        path="/v1/tasks",
        partition_key="createdAt",
    ),
    "reminders": FolkEndpointConfig(
        name="reminders",
        path="/v1/reminders",
        partition_key="createdAt",
    ),
}

ENDPOINTS = tuple(FOLK_ENDPOINTS.keys())
