from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


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
    # JSONPath to the row list in the response body. Some endpoints (/api/card, /api/dashboard,
    # /api/collection, /api/native-query-snippet) return a bare JSON array — left None. Others
    # (/api/database, /api/user) wrap it as {"data": [...], "total": N} — set "data".
    data_selector: Optional[str] = None
    # Child endpoints fetched once per parent row (e.g. fields per database).
    fanout: Optional[DependentEndpointConfig] = None
    # The path carries a `{month}` placeholder (yyyy-mm) and returns that calendar month's rows.
    month_windowed: bool = False
    # The response is a JSON object mapping a key to a list of rows rather than a list of rows.
    grouped_by_key: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Read by the shared fan-out helper; Metabase list endpoints take no page-size param.
    default_incremental_field: Optional[str] = None
    page_size: int = 0


# Metabase list endpoints return the full collection in a single response — there is no pagination
# and no server-side timestamp filter, so every schema except the month-windowed query log is
# full-refresh only. The stream set mirrors
# the canonical Metabase connector (cards, dashboards, collections, databases, users, snippets), plus
# the data-model, permissions, and query-log tables.
METABASE_ENDPOINTS: dict[str, MetabaseEndpointConfig] = {
    "cards": MetabaseEndpointConfig(name="cards", path="/api/card", partition_key="created_at"),
    "dashboards": MetabaseEndpointConfig(name="dashboards", path="/api/dashboard", partition_key="created_at"),
    # Collection ids can be the literal string "root" and the resource has no creation timestamp.
    "collections": MetabaseEndpointConfig(name="collections", path="/api/collection"),
    "databases": MetabaseEndpointConfig(
        name="databases", path="/api/database", partition_key="created_at", data_selector="data"
    ),
    "users": MetabaseEndpointConfig(name="users", path="/api/user", partition_key="date_joined", data_selector="data"),
    "native_query_snippets": MetabaseEndpointConfig(
        name="native_query_snippets", path="/api/native-query-snippet", partition_key="created_at"
    ),
    "tables": MetabaseEndpointConfig(name="tables", path="/api/table", partition_key="created_at"),
    # Field rows carry no creation timestamp and no database id, so the parent id is copied in.
    "fields": MetabaseEndpointConfig(
        name="fields",
        path="/api/database/{id}/fields",
        fanout=DependentEndpointConfig(
            parent_name="databases",
            resolve_param="id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "database_id"},
            # A database deleted between the parent listing and its fields fetch.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "permission_groups": MetabaseEndpointConfig(name="permission_groups", path="/api/permissions/group"),
    # Returns {user_id: [{membership_id, group_id, user_id, is_group_manager}, ...]}.
    "permission_group_memberships": MetabaseEndpointConfig(
        name="permission_group_memberships",
        path="/api/permissions/membership",
        primary_keys=["membership_id"],
        grouped_by_key=True,
    ),
    # Pro/Enterprise only and superuser only. The month window is the only server-side time filter.
    "query_executions": MetabaseEndpointConfig(
        name="query_executions",
        path="/api/ee/logs/query_execution/{month}",
        partition_key="started_at",
        month_windowed=True,
        incremental_fields=[
            {
                "label": "started_at",
                "type": IncrementalFieldType.DateTime,
                "field": "started_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
}

ENDPOINTS = tuple(METABASE_ENDPOINTS.keys())
