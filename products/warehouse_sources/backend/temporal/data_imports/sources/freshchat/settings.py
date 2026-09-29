"""Freshchat source settings and endpoint catalog."""

from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField

# Freshchat caps `items_per_page` at 50 (default 20). Pull the max to keep the request
# count — and therefore rate-limit pressure — as low as possible.
PER_PAGE = 50

# The `GET /v2/users` list endpoint requires at least one filter parameter; a bare list
# request errors. `created_from` is a stable creation-time floor that lets us page every
# user without excluding anyone. This is a full-refresh floor, not an incremental cursor.
USERS_CREATED_FROM = "2000-01-01T00:00:00.000Z"

# A parent row can disappear between its listing page and the child fetch that follows it;
# that must not sink the whole fan-out.
SKIP_MISSING_PARENT: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


@dataclass(frozen=True)
class FreshchatChainedFanoutConfig:
    """A second-level fan-out whose parent is itself a fan-out child.

    Freshchat exposes no top-level conversations list, so messages are only reachable as
    users -> that user's conversations -> that conversation's messages, which
    `build_dependent_resource` (one hop, one resolved param) cannot express.
    """

    parent_name: str
    resolve_param: str
    resolve_field: str
    include_from_parent: list[str]
    parent_field_renames: dict[str, str]


USER_CONVERSATIONS_FANOUT = DependentEndpointConfig(
    parent_name="users",
    resolve_param="user_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "user_id"},
    child_response_actions=SKIP_MISSING_PARENT,
)

CONVERSATION_MESSAGES_FANOUT = FreshchatChainedFanoutConfig(
    parent_name="user_conversations",
    resolve_param="conversation_id",
    resolve_field="id",
    # A message object already carries `conversation_id`, but projecting it from the parent row
    # guarantees the primary-key column is populated on every row.
    include_from_parent=["id"],
    parent_field_renames={"id": "conversation_id"},
)


@dataclass
class FreshchatEndpointConfig:
    name: str
    # Path relative to the `/v2` base (e.g. `/agents`).
    path: str
    # Freshchat wraps most list responses in an object keyed by the resource name
    # (e.g. {"agents": [...], "pagination": {...}}); `data_key` is that key. The envelope is
    # inconsistent across the API, so the extractor also falls back to a bare array / single
    # object when the key is absent.
    data_key: Optional[str] = None
    # `True` for the paginated collection endpoints (page / items_per_page). `False` for
    # single-object endpoints like accounts/configuration.
    paginated: bool = True
    # `True` when the endpoint returns a single object rather than a collection — we wrap it
    # into a one-row list so it lands as a single warehouse row.
    single_object: bool = False
    # Extra static query params (e.g. the mandatory `created_from` filter on users).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Path to the page count in the response body. Most list endpoints report it, which lets the
    # paginator stop without paying an extra empty request; the per-conversation messages response
    # carries no pagination envelope, so that endpoint stops on the first empty page instead.
    total_pages_path: Optional[str] = "pagination.total_pages"
    # `sort_order` is documented on the top-level list endpoints but not on the per-conversation
    # messages endpoint, so it is only sent where the API documents it.
    accepts_sort_order: bool = True
    # Stable creation-time field to partition the Delta table on.
    partition_key: Optional[str] = None
    # One hop down from a top-level list endpoint.
    fanout: Optional[DependentEndpointConfig] = None
    # Two hops down, where the parent is itself a fan-out child.
    chained_fanout: Optional[FreshchatChainedFanoutConfig] = None
    # Freshchat's page-size param rides in each endpoint's own params rather than through the
    # fan-out helper, so these three only satisfy the helper's structural typing.
    page_size: int = PER_PAGE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# Freshchat v2 endpoints.
#
# The public REST API exposes no server-side updated_since / created_since cursor on the top-level
# list endpoints, so every endpoint is full refresh only (no `supports_incremental`). Pagination is
# resumable by page number via the ResumableSource manager. The outbound-messages and metrics
# endpoints require time-window params and are not covered.
FRESHCHAT_ENDPOINTS: dict[str, FreshchatEndpointConfig] = {
    "agents": FreshchatEndpointConfig(
        name="agents",
        path="/agents",
        data_key="agents",
    ),
    "users": FreshchatEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        # At least one filter is mandatory on this endpoint; the created-time floor lists all users.
        extra_params={"created_from": USERS_CREATED_FROM},
    ),
    "groups": FreshchatEndpointConfig(
        name="groups",
        path="/groups",
        data_key="groups",
    ),
    "channels": FreshchatEndpointConfig(
        name="channels",
        path="/channels",
        data_key="channels",
    ),
    "roles": FreshchatEndpointConfig(
        name="roles",
        path="/roles",
        data_key="roles",
    ),
    "accounts_configuration": FreshchatEndpointConfig(
        name="accounts_configuration",
        path="/accounts/configuration",
        data_key="configuration",
        paginated=False,
        single_object=True,
    ),
    "user_conversations": FreshchatEndpointConfig(
        name="user_conversations",
        path="/users/{user_id}/conversations",
        data_key="conversations",
        # The endpoint documents no page / items_per_page params and answers with the user's whole
        # conversation list in one response.
        paginated=False,
        fanout=USER_CONVERSATIONS_FANOUT,
    ),
    "conversation_messages": FreshchatEndpointConfig(
        name="conversation_messages",
        path="/conversations/{conversation_id}/messages",
        data_key="messages",
        total_pages_path=None,
        accepts_sort_order=False,
        partition_key="created_time",
        chained_fanout=CONVERSATION_MESSAGES_FANOUT,
    ),
}

ENDPOINTS = tuple(FRESHCHAT_ENDPOINTS.keys())

# `id` is the auto-generated primary key on agents / users / groups / channels / roles. The single
# account-configuration row is keyed on its stable Freshchat app id. The two fan-out children
# aggregate rows from every parent, so their keys carry the parent id: a conversation can be listed
# under more than one user, and Freshchat documents no global uniqueness for message ids.
PRIMARY_KEYS: dict[str, list[str]] = {
    "agents": ["id"],
    "users": ["id"],
    "groups": ["id"],
    "channels": ["id"],
    "roles": ["id"],
    "accounts_configuration": ["app_id"],
    "user_conversations": ["user_id", "id"],
    "conversation_messages": ["conversation_id", "id"],
}
