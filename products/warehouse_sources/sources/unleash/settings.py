from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UnleashEndpointConfig:
    name: str
    # Path under the instance base URL (Unleash Admin API lives at /api/admin).
    path: str
    # Top-level key the list of records lives under in the response body, or None when the
    # endpoint returns a bare JSON array (context fields).
    data_selector: Optional[str]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Only the feature search endpoint supports offset/limit pagination; every other Admin API
    # list endpoint returns the full collection in one response.
    paginated: bool = False
    # Endpoints gated on the ADMIN root permission (verified against a live instance: a
    # non-admin personal access token gets a 403 PermissionError here).
    requires_admin: bool = False


# Unleash Admin API list endpoints. All are full refresh only: the Admin API exposes no
# server-side updated_after/created_after filter on these resources, so there is no reliable
# timestamp cursor to advance an incremental sync. Collections are configuration-sized, so a
# full pull per sync is cheap.
UNLEASH_ENDPOINTS: dict[str, UnleashEndpointConfig] = {
    # Feature flag search (Unleash 5.12+). Flag names are unique across the whole instance, so
    # `name` is a safe primary key. Fetched sorted by createdAt ascending for stable page
    # boundaries while paginating.
    "features": UnleashEndpointConfig(
        name="features",
        path="/api/admin/search/features",
        data_selector="features",
        primary_keys=["name"],
        paginated=True,
    ),
    "projects": UnleashEndpointConfig(
        name="projects",
        path="/api/admin/projects",
        data_selector="projects",
    ),
    "environments": UnleashEndpointConfig(
        name="environments",
        path="/api/admin/environments",
        data_selector="environments",
        primary_keys=["name"],
    ),
    "strategies": UnleashEndpointConfig(
        name="strategies",
        path="/api/admin/strategies",
        data_selector="strategies",
        primary_keys=["name"],
    ),
    "segments": UnleashEndpointConfig(
        name="segments",
        path="/api/admin/segments",
        data_selector="segments",
    ),
    # Returns a bare JSON array (no wrapper object).
    "context_fields": UnleashEndpointConfig(
        name="context_fields",
        path="/api/admin/context",
        data_selector=None,
        primary_keys=["name"],
    ),
    # A tag is identified by its (type, value) pair — there is no id column.
    "tags": UnleashEndpointConfig(
        name="tags",
        path="/api/admin/tags",
        data_selector="tags",
        primary_keys=["type", "value"],
    ),
    "tag_types": UnleashEndpointConfig(
        name="tag_types",
        path="/api/admin/tag-types",
        data_selector="tagTypes",
        primary_keys=["name"],
    ),
    "feature_types": UnleashEndpointConfig(
        name="feature_types",
        path="/api/admin/feature-types",
        data_selector="types",
    ),
    "addons": UnleashEndpointConfig(
        name="addons",
        path="/api/admin/addons",
        data_selector="addons",
    ),
    "users": UnleashEndpointConfig(
        name="users",
        path="/api/admin/user-admin",
        data_selector="users",
        requires_admin=True,
    ),
}

ENDPOINTS = tuple(UNLEASH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
