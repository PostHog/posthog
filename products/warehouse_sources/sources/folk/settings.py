from dataclasses import dataclass, field
from typing import Literal, Optional

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
    # (groups, users, group members, and custom fields).
    partition_key: Optional[str] = None
    # Set on endpoints scoped to one group: the sync walks every group from `/v1/groups` and lists
    # this child resource per group. "objects" and "custom_fields" also fan out per object type.
    group_fanout: Optional[Literal["members", "custom_fields", "objects"]] = None


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
    "group_members": FolkEndpointConfig(
        name="group_members",
        path="/v1/groups/{groupId}/members",
        primary_keys=["groupId", "id"],
        group_fanout="members",
    ),
    "group_custom_fields": FolkEndpointConfig(
        name="group_custom_fields",
        path="/v1/groups/{groupId}/custom-fields/{entityType}",
        primary_keys=["groupId", "entityType", "name"],
        group_fanout="custom_fields",
    ),
    # Deals and every other custom object type share one route per group and object type.
    "custom_objects": FolkEndpointConfig(
        name="custom_objects",
        path="/v1/groups/{groupId}/{objectType}",
        primary_keys=["groupId", "objectType", "id"],
        partition_key="createdAt",
        group_fanout="objects",
    ),
}

# Custom field entity types every group has; custom object type names are added per group.
FOLK_BUILTIN_ENTITY_TYPES = ("person", "company")

ENDPOINTS = tuple(FOLK_ENDPOINTS.keys())
