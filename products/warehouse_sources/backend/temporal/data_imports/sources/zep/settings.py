from dataclasses import dataclass, field

# Zep is a single global deployment; there are no regional hosts.
ZEP_BASE_URL = "https://api.getzep.com/api/v2"


@dataclass
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
}

ENDPOINTS = tuple(ZEP_ENDPOINTS.keys())
