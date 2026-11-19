from dataclasses import field
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

# The feature search endpoint documents a default limit of 50; 100 verified working against a
# live instance and keeps round trips low.
PAGE_SIZE = 100


@frozen
class UnleashEndpointConfig:
    name: str
    # Path under the instance base URL (Unleash Admin API lives at /api/admin).
    path: str
    # Top-level key the list of records lives under in the response body, or None when the
    # endpoint returns a bare JSON array (context fields).
    data_selector: Optional[str]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Only the feature and event search endpoints support offset/limit pagination; every other
    # Admin API list endpoint returns the full collection in one response.
    paginated: bool = False
    page_size: int = PAGE_SIZE
    # Endpoints gated on the ADMIN root permission (verified against a live instance: a
    # non-admin personal access token gets a 403 PermissionError here).
    requires_admin: bool = False
    # Fan-out children: fields of each `features` row that fill the path placeholders. They are
    # also copied onto the child rows.
    parent_fields: tuple[str, ...] = ()
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Unleash Admin API list endpoints. The configuration tables are full refresh only: the Admin API
# exposes no server-side updated_after/created_after filter on these resources, so there is no
# reliable timestamp cursor to advance an incremental sync. Collections are configuration-sized,
# so a full pull per sync is cheap.
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
    # The audit log. Search returns newest first with no sort option, and `from` filters on the
    # creation date (day granularity, inclusive). The legacy GET /api/admin/events is deprecated.
    "events": UnleashEndpointConfig(
        name="events",
        path="/api/admin/search/events",
        data_selector="events",
        paginated=True,
        page_size=1000,
        partition_key="createdAt",
        incremental_fields=[
            IncrementalField(
                label="createdAt",
                type=IncrementalFieldType.DateTime,
                field="createdAt",
                field_type=IncrementalFieldType.DateTime,
            )
        ],
    ),
    # One row per strategy per environment. The feature endpoint returns every environment with
    # its strategies, so one request per flag replaces one per flag and environment on
    # .../environments/{environment}/strategies. Strategy ids are UUIDs, unique instance-wide.
    "feature_strategies": UnleashEndpointConfig(
        name="feature_strategies",
        path="/api/admin/projects/{project}/features/{name}",
        data_selector="environments",
        parent_fields=("name", "project"),
    ),
    # Hourly yes/no evaluation counts per flag, SDK app and environment. Unleash keeps 48 hours
    # of raw metrics. Every sync reads the whole window, because late reports update older
    # buckets; an incremental sync merges it on the key, so history outlives that retention as
    # long as syncs run at least every 48 hours.
    "feature_metrics": UnleashEndpointConfig(
        name="feature_metrics",
        path="/api/admin/client-metrics/features/{name}/raw",
        data_selector="data",
        primary_keys=["featureName", "appName", "environment", "timestamp"],
        parent_fields=("name",),
        partition_key="timestamp",
        incremental_fields=[
            IncrementalField(
                label="timestamp",
                type=IncrementalFieldType.DateTime,
                field="timestamp",
                field_type=IncrementalFieldType.DateTime,
            )
        ],
    ),
}

ENDPOINTS = tuple(UNLEASH_ENDPOINTS.keys())
