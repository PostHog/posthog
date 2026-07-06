from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MetabaseEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field used for datetime partitioning. Left None when the resource has no
    # reliably-present creation timestamp (e.g. collections, whose `id` may be the string "root").
    partition_key: Optional[str] = None
    # Extra query params sent on the list request. Empty for every endpoint today — Metabase list
    # endpoints take no required filters and we deliberately avoid version-specific optional params.
    params: dict[str, str] = field(default_factory=dict)


# Metabase list endpoints return the full collection in a single response — there is no pagination
# and no server-side timestamp filter, so every schema is full-refresh only. The stream set mirrors
# the canonical Metabase connector (cards, dashboards, collections, databases, users, snippets).
METABASE_ENDPOINTS: dict[str, MetabaseEndpointConfig] = {
    "cards": MetabaseEndpointConfig(name="cards", path="/api/card", partition_key="created_at"),
    "dashboards": MetabaseEndpointConfig(name="dashboards", path="/api/dashboard", partition_key="created_at"),
    # Collection ids can be the literal string "root" and the resource has no creation timestamp.
    "collections": MetabaseEndpointConfig(name="collections", path="/api/collection"),
    "databases": MetabaseEndpointConfig(name="databases", path="/api/database", partition_key="created_at"),
    "users": MetabaseEndpointConfig(name="users", path="/api/user", partition_key="date_joined"),
    "native_query_snippets": MetabaseEndpointConfig(
        name="native_query_snippets", path="/api/native-query-snippet", partition_key="created_at"
    ),
}

ENDPOINTS = tuple(METABASE_ENDPOINTS.keys())
