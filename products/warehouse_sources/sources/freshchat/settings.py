"""Freshchat source settings and endpoint catalog."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    ResponseAction,
)

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


@dataclass(frozen=True)
class HistoricalMetric:
    name: str
    # Aggregate metrics need an aggregator; count metrics must be sent without one.
    aggregator: Optional[str] = None


# The metrics that `GET /v2/metrics/historical` returns at account level, one value per metric per
# bucket. The `*_x_mins_ago_*` metrics ignore the time window, `team_performance.wait_time` only comes
# inside the `team_performance` summary, and `csat_metrics.rating` is only useful split by rating, so
# none of those are read.
HISTORICAL_METRICS: tuple[HistoricalMetric, ...] = (
    HistoricalMetric("conversation_metrics.created_interactions"),
    HistoricalMetric("conversation_metrics.assigned_interactions"),
    HistoricalMetric("conversation_metrics.resolved_interactions"),
    HistoricalMetric("conversation_metrics.wait_time", aggregator="avg"),
    HistoricalMetric("csat_metrics.satisfactory_interactions"),
    HistoricalMetric("csat_metrics.unsatisfactory_interactions"),
    HistoricalMetric("csat_metrics.total_rated_interactions"),
    HistoricalMetric("csat_metrics.count_per_rating", aggregator="avg"),
    HistoricalMetric("team_performance.responses_sent"),
    HistoricalMetric("team_performance.first_response_time", aggregator="avg"),
    HistoricalMetric("team_performance.response_time", aggregator="avg"),
    HistoricalMetric("team_performance.resolution_time", aggregator="avg"),
    HistoricalMetric("team_performance.concurrency_ratio", aggregator="avg"),
)

HISTORICAL_METRICS_INTERVAL = "1d"
# Freshchat documents no maximum range, so a window stays small.
HISTORICAL_METRICS_WINDOW = timedelta(days=30)
HISTORICAL_METRICS_LOOKBACK = timedelta(days=365)
HISTORICAL_METRICS_REREAD = timedelta(days=1)

INTERVAL_START_FIELD = IncrementalField(
    label="interval_start",
    type=IncrementalFieldType.DateTime,
    field="interval_start",
    field_type=IncrementalFieldType.DateTime,
)


@dataclass(frozen=True)
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
    # Path to the page count in the response body, which lets the paginator stop without paying
    # an extra empty request. `None` falls back to stopping on the first empty page.
    total_pages_path: Optional[str] = "pagination.total_pages"
    # Only the top-level list endpoints document `sort_order`.
    accepts_sort_order: bool = True
    partition_key: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None
    # Two hops down, where the parent is itself a fan-out child.
    chained_fanout: Optional[FreshchatChainedFanoutConfig] = None
    metrics_query: bool = False
    # Freshchat's page-size param rides in each endpoint's own params rather than through the
    # fan-out helper, so these three only satisfy the helper's structural typing.
    page_size: int = PER_PAGE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# Freshchat v2 endpoints.
#
# The public REST API exposes no server-side updated_since / created_since cursor on the top-level
# list endpoints, so those are full refresh only. Pagination is resumable by page number via the
# ResumableSource manager. Historical metrics take a server-side time window, so that table can sync
# incrementally. Raw reports are async export jobs, so they are not covered.
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
    "outbound_messages": FreshchatEndpointConfig(
        name="outbound_messages",
        path="/outbound-messages",
        data_key="outbound_messages",
        # The endpoint documents no page / items_per_page params and returns every message as one
        # array; page params on it could loop on the same array forever.
        paginated=False,
    ),
    "user_conversations": FreshchatEndpointConfig(
        name="user_conversations",
        path="/users/{user_id}/conversations",
        data_key="conversations",
        # The endpoint documents no page / items_per_page params.
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
    "historical_metrics": FreshchatEndpointConfig(
        name="historical_metrics",
        path="/metrics/historical",
        paginated=False,
        partition_key="interval_start",
        metrics_query=True,
        incremental_fields=[INTERVAL_START_FIELD],
        default_incremental_field="interval_start",
    ),
}

ENDPOINTS = tuple(FRESHCHAT_ENDPOINTS.keys())

# `id` is the auto-generated primary key on the top-level collections; the single
# account-configuration row is keyed on its stable Freshchat app id. The fan-out children carry the
# parent id too: a conversation can be listed under more than one user, and Freshchat documents no
# global uniqueness for message ids.
PRIMARY_KEYS: dict[str, list[str]] = {
    "agents": ["id"],
    "users": ["id"],
    "groups": ["id"],
    "channels": ["id"],
    "roles": ["id"],
    "accounts_configuration": ["app_id"],
    "outbound_messages": ["message_id"],
    "user_conversations": ["user_id", "id"],
    "conversation_messages": ["conversation_id", "id"],
    "historical_metrics": ["metric", "grouping", "interval_start"],
}
