from dataclasses import dataclass, field

# Zep is a single global deployment; there are no regional hosts.
ZEP_BASE_URL = "https://api.getzep.com/api/v2"


@dataclass(frozen=False)  # tests patch fields such as page_size
class ZepEndpointConfig:
    name: str
    path: str
    # Key in the JSON response body that holds the list of rows.
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["uuid"])
    # Stable creation-time field to partition by (never a mutable field like updated_at).
    partition_key: str | None = "created_at"
    # Page-based endpoints use different param casing (users: pageNumber/pageSize,
    # threads: page_number/page_size). Left None for the cursor-paginated fan-out.
    page_number_param: str | None = None
    page_size_param: str | None = None
    page_size: int = 100
    # Value passed to `order_by` so pagination walks a stable, monotonic order. Must be a
    # creation-time column so the sort matches sort_mode="asc" and page boundaries are stable
    # as new rows arrive mid-sync.
    order_by: str | None = None
    should_sync_default: bool = True
    # thread_messages fans out one paginated request per thread (Zep only exposes messages
    # per-thread). When True, `path` is a template with a `{thread_id}` placeholder.
    fan_out_over_threads: bool = False
    # Graph endpoints list one graph per request. When True, `path` is a template with `{scope}`
    # ("user" or "graph") and `{owner_id}` placeholders, and the source fans out over every user
    # graph and every standalone graph. The response body is a bare list.
    fan_out_over_graphs: bool = False


GRAPH_ELEMENT_PRIMARY_KEYS = ["graph_scope", "graph_owner_id", "uuid"]

ZEP_ENDPOINTS: dict[str, ZepEndpointConfig] = {
    "users": ZepEndpointConfig(
        name="users",
        path="/users-ordered",
        data_key="users",
        page_number_param="pageNumber",
        page_size_param="pageSize",
        order_by="created_at",
    ),
    "threads": ZepEndpointConfig(
        name="threads",
        path="/threads",
        data_key="threads",
        page_number_param="page_number",
        page_size_param="page_size",
        order_by="created_at",
    ),
    # Fan out over every thread and pull its messages. Message `uuid` is a globally-unique id
    # per the API docs, so it alone is a safe table-wide primary key; each row is enriched with
    # its parent `thread_id` for joinability.
    "thread_messages": ZepEndpointConfig(
        name="thread_messages",
        path="/threads/{thread_id}/messages",
        data_key="messages",
        fan_out_over_threads=True,
    ),
    "graphs": ZepEndpointConfig(
        name="graphs",
        path="/graph/list-all",
        data_key="graphs",
        page_number_param="pageNumber",
        page_size_param="pageSize",
        order_by="created_at",
    ),
    # Graph elements carry no reference to their graph, so each row gets `graph_scope` and
    # `graph_owner_id` (the user_id or graph_id). The key includes them because the API does not
    # document element uuids as unique across graphs.
    "graph_edges": ZepEndpointConfig(
        name="graph_edges",
        path="/graph/edge/{scope}/{owner_id}",
        data_key="",
        primary_keys=GRAPH_ELEMENT_PRIMARY_KEYS,
        fan_out_over_graphs=True,
    ),
    "graph_nodes": ZepEndpointConfig(
        name="graph_nodes",
        path="/graph/node/{scope}/{owner_id}",
        data_key="",
        primary_keys=GRAPH_ELEMENT_PRIMARY_KEYS,
        fan_out_over_graphs=True,
    ),
    "graph_episodes": ZepEndpointConfig(
        name="graph_episodes",
        path="/graph/episodes/{scope}/{owner_id}",
        data_key="",
        primary_keys=GRAPH_ELEMENT_PRIMARY_KEYS,
        # The API clamps an explicit episode `limit` to 50.
        page_size=50,
        fan_out_over_graphs=True,
    ),
}

ENDPOINTS = tuple(ZEP_ENDPOINTS.keys())
