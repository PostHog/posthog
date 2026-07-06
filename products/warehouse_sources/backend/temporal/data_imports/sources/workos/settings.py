from dataclasses import dataclass


@dataclass
class WorkOSEndpointConfig:
    name: str
    path: str
    # `created_at` is set once and never changes, so it's a stable partition key.
    partition_key: str = "created_at"
    page_size: int = 100  # WorkOS max page size


# WorkOS list endpoints share one cursor-paginated envelope
# ({"data": [...], "list_metadata": {"before": ..., "after": ...}}) and expose no
# server-side timestamp filter, so every endpoint is full-refresh only. Incremental
# sync on WorkOS is only possible through the /events API, which is not modeled here.
WORKOS_ENDPOINTS: dict[str, WorkOSEndpointConfig] = {
    "organizations": WorkOSEndpointConfig(name="organizations", path="/organizations"),
    "users": WorkOSEndpointConfig(name="users", path="/user_management/users"),
    "connections": WorkOSEndpointConfig(name="connections", path="/connections"),
    "directories": WorkOSEndpointConfig(name="directories", path="/directories"),
    "directory_users": WorkOSEndpointConfig(name="directory_users", path="/directory_users"),
    "directory_groups": WorkOSEndpointConfig(name="directory_groups", path="/directory_groups"),
}

ENDPOINTS = tuple(WORKOS_ENDPOINTS.keys())
