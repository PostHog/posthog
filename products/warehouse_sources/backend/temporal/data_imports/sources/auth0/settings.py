from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Auth0 refuses to page past the first 1000 results of a searchable collection, so the
# endpoints that expose a searchable timestamp walk history in windows: once a window is
# exhausted the Lucene `q` lower bound moves to the newest row seen and paging restarts.
SEARCH_RESULT_CAP = 1000

DEFAULT_PAGE_SIZE = 100

# `take` defaults to 50 on the checkpoint-paginated collections, and no larger maximum is
# documented for every one of them.
CHECKPOINT_PAGE_SIZE = 50

# The Management API caps `per_page` at 100 on every collection that accepts it.
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class Auth0EndpointConfig:
    name: str
    # Formatted with the resolved vendor API version, so the version pin lives on the source
    # class rather than being hardcoded in the request layer.
    path_template: str
    # Key the rows sit under in the response envelope. None means the endpoint returns a bare
    # JSON array and takes no pagination parameters.
    data_key: Optional[str] = None
    primary_keys: tuple[str, ...] = ("id",)
    page_size: int = DEFAULT_PAGE_SIZE
    # Only the collections that document `include_totals` accept it; the Actions API always
    # returns its own totals envelope instead.
    supports_include_totals: bool = True
    # Field the window slides on and the collection is sorted by. Set only for the two
    # collections whose Lucene query syntax documents a date range filter.
    window_field: Optional[str] = None
    # Window field used when the run is a full refresh: an immutable timestamp keeps page
    # boundaries stable while paging, which `updated_at` cannot guarantee.
    full_refresh_window_field: Optional[str] = None
    # Auth0's user search needs the engine pinned; the logs endpoint has no such parameter.
    search_engine: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable (never-rewritten) timestamp column used to partition the delta table.
    partition_key: Optional[str] = None
    # Whether responses may enter opt-in HTTP sample capture. Off wherever the body carries
    # end-user PII or tenant credentials (connection secrets, log stream sink keys) that the
    # name-based sample scrubbers cannot recognise.
    capture_samples: bool = False
    # Management API scope the token must carry, surfaced when a scoped probe is denied.
    required_scope: str = ""
    # Fan-out children: the collection walked for parent ids (`{parent_id}` in the path), the
    # parent row field that holds the id, and the column the id is written to on each child row.
    # Children are paged with `from`/`take` and a `next` token, because Auth0 refuses offset
    # paging past 1000 rows on these collections and offers no window to slide on.
    parent: Optional[str] = None
    parent_id_field: str = "id"
    parent_id_column: Optional[str] = None
    # Fields requested from the parent collection to keep its pages small. Must include the
    # parent's window field so the parent walk can slide past the search result cap.
    parent_fields: Optional[str] = None
    extra_params: dict[str, str] = field(default_factory=dict)
    # Nested array each response row is expanded into, one output row per item.
    explode_field: Optional[str] = None
    # Walked with `from`/`take` when it is a fan-out parent: offset paging stops at 1000 rows and
    # the collection has no window to slide on.
    checkpoint_parent: bool = False

    @property
    def paginated(self) -> bool:
        return self.data_key is not None


AUTH0_ENDPOINTS: dict[str, Auth0EndpointConfig] = {
    "users": Auth0EndpointConfig(
        name="users",
        path_template="/api/{version}/users",
        data_key="users",
        primary_keys=("user_id",),
        window_field="updated_at",
        full_refresh_window_field="created_at",
        search_engine="v3",
        incremental_fields=[incremental_field("updated_at"), incremental_field("created_at")],
        partition_key="created_at",
        required_scope="read:users",
    ),
    "logs": Auth0EndpointConfig(
        name="logs",
        path_template="/api/{version}/logs",
        data_key="logs",
        primary_keys=("log_id",),
        window_field="date",
        full_refresh_window_field="date",
        incremental_fields=[incremental_field("date")],
        partition_key="date",
        required_scope="read:logs",
    ),
    "clients": Auth0EndpointConfig(
        name="clients",
        path_template="/api/{version}/clients",
        data_key="clients",
        primary_keys=("client_id",),
        required_scope="read:clients",
    ),
    "connections": Auth0EndpointConfig(
        name="connections",
        path_template="/api/{version}/connections",
        data_key="connections",
        required_scope="read:connections",
    ),
    "roles": Auth0EndpointConfig(
        name="roles",
        path_template="/api/{version}/roles",
        data_key="roles",
        capture_samples=True,
        required_scope="read:roles",
    ),
    "organizations": Auth0EndpointConfig(
        name="organizations",
        path_template="/api/{version}/organizations",
        data_key="organizations",
        capture_samples=True,
        required_scope="read:organizations",
        checkpoint_parent=True,
    ),
    "resource_servers": Auth0EndpointConfig(
        name="resource_servers",
        path_template="/api/{version}/resource-servers",
        data_key="resource_servers",
        required_scope="read:resource_servers",
    ),
    "actions": Auth0EndpointConfig(
        name="actions",
        path_template="/api/{version}/actions/actions",
        data_key="actions",
        supports_include_totals=False,
        capture_samples=True,
        required_scope="read:actions",
    ),
    "log_streams": Auth0EndpointConfig(
        name="log_streams",
        path_template="/api/{version}/log-streams",
        required_scope="read:log_streams",
    ),
    # Walks role -> users rather than user -> roles: tenants hold far fewer roles than users, so
    # this needs one request per role instead of one per user for the same assignments.
    "user_roles": Auth0EndpointConfig(
        name="user_roles",
        path_template="/api/{version}/roles/{parent_id}/users",
        data_key="users",
        primary_keys=("role_id", "user_id"),
        required_scope="read:users",
        parent="roles",
        parent_id_column="role_id",
    ),
    "organization_members": Auth0EndpointConfig(
        name="organization_members",
        path_template="/api/{version}/organizations/{parent_id}/members",
        data_key="members",
        primary_keys=("organization_id", "user_id"),
        required_scope="read:organization_members",
        parent="organizations",
        parent_id_column="organization_id",
    ),
    # The members collection returns each member's directly assigned roles when asked for them,
    # which replaces one `members/{user_id}/roles` request per member with one page per 50.
    "organization_member_roles": Auth0EndpointConfig(
        name="organization_member_roles",
        path_template="/api/{version}/organizations/{parent_id}/members",
        data_key="members",
        primary_keys=("organization_id", "user_id", "id"),
        extra_params={"fields": "user_id,roles", "include_fields": "true"},
        explode_field="roles",
        required_scope="read:organization_member_roles",
        parent="organizations",
        parent_id_column="organization_id",
    ),
    # Auth0 has no tenant-wide session listing, so this needs one request per user.
    "user_sessions": Auth0EndpointConfig(
        name="user_sessions",
        path_template="/api/{version}/users/{parent_id}/sessions",
        data_key="sessions",
        primary_keys=("user_id", "id"),
        required_scope="read:sessions",
        parent="users",
        parent_id_field="user_id",
        parent_id_column="user_id",
        parent_fields="user_id,created_at",
    ),
}

ENDPOINTS = tuple(AUTH0_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AUTH0_ENDPOINTS.items()
}

REQUIRED_SCOPES: dict[str, str] = {name: config.required_scope for name, config in AUTH0_ENDPOINTS.items()}
