from typing import Any, Literal, NotRequired, TypedDict

from products.warehouse_sources.sources.sdk import IncrementalFieldType, incremental_field

BASE_URL = "https://api.peec.ai/customer"
PAGE_SIZE = 1000
# Peec's largest allowed page. Rows inside one day have no unique sort key, so offset pages can
# shift between requests; a page this size holds a whole day for almost every project.
DAILY_PAGE_SIZE = 10000


class PeecAIEndpoint(TypedDict):
    path: str
    params: dict[str, Any]
    total_path: str | None
    method: NotRequired[Literal["GET", "POST"]]
    paginated: NotRequired[bool]
    primary_keys: NotRequired[list[str]]
    # Sends start_date (the configured start or the incremental watermark) and end_date (today).
    date_range: NotRequired[bool]
    # Reads the date range one day per request window, so offsets stay small and rows arrive in date order.
    daily: NotRequired[bool]
    sort_mode: NotRequired[Literal["asc"]]
    # Top-level columns copied from nested objects, so they can be primary keys.
    lifted_ids: NotRequired[dict[str, tuple[str, str]]]


# The vendor recommends a per-model-channel breakdown, and a daily grain keeps rows mergeable by date.
REPORT_PARAMS: dict[str, Any] = {"dimensions": ["date", "model_channel_id"]}
MODEL_CHANNEL_ID: tuple[str, str] = ("model_channel", "id")


ENDPOINTS: dict[str, PeecAIEndpoint] = {
    "chats": {
        "path": "chats",
        "params": {"include_archived_prompts": "true", "sort": "asc"},
        "total_path": "total_count",
        "date_range": True,
        "sort_mode": "asc",
    },
    "prompts": {"path": "prompts", "params": {"is_archived": "false"}, "total_path": "total_count"},
    "archived_prompts": {"path": "prompts", "params": {"is_archived": "true"}, "total_path": "total_count"},
    "brands": {"path": "brands", "params": {}, "total_path": "total_count"},
    "topics": {"path": "topics", "params": {}, "total_path": "total_count"},
    "tags": {"path": "tags", "params": {}, "total_path": "total_count"},
    "model_channels": {"path": "model-channels", "params": {}, "total_path": None},
    "tag_groups": {
        "path": "tag-groups",
        "params": {},
        "total_path": None,
        "paginated": False,
        "primary_keys": ["group"],
    },
    # The default impact order shifts as statuses change, so offset pages need a stable order.
    "actions": {
        "path": "actions/list",
        "params": {"order_by": "created_at", "direction": "asc"},
        "total_path": "total_count",
        "method": "POST",
    },
    "brand_report": {
        "path": "reports/brands",
        "params": REPORT_PARAMS,
        "total_path": None,
        "method": "POST",
        "date_range": True,
        "daily": True,
        "sort_mode": "asc",
        "primary_keys": ["brand_id", "date", "model_channel_id"],
        "lifted_ids": {"brand_id": ("brand", "id"), "model_channel_id": MODEL_CHANNEL_ID},
    },
    "domain_report": {
        "path": "reports/domains",
        "params": REPORT_PARAMS,
        "total_path": "total_count",
        "method": "POST",
        "date_range": True,
        "daily": True,
        "sort_mode": "asc",
        "primary_keys": ["domain", "date", "model_channel_id"],
        "lifted_ids": {"model_channel_id": MODEL_CHANNEL_ID},
    },
    "url_report": {
        "path": "reports/urls",
        "params": REPORT_PARAMS,
        "total_path": None,
        "method": "POST",
        "date_range": True,
        "daily": True,
        "sort_mode": "asc",
        "primary_keys": ["url", "date", "model_channel_id"],
        "lifted_ids": {"model_channel_id": MODEL_CHANNEL_ID},
    },
    # Metrics are totals over the whole date range, so this table is a full-refresh snapshot.
    "products": {
        "path": "products/list",
        "params": {"order_by": "name", "direction": "asc"},
        "total_path": "total_count",
        "method": "POST",
        "date_range": True,
    },
    "search_fanout_queries": {
        "path": "queries/search",
        "params": {"view": "rows"},
        "total_path": "total_count",
        "method": "POST",
        "date_range": True,
        "daily": True,
        "sort_mode": "asc",
        "primary_keys": ["chat_id", "query_index"],
        "lifted_ids": {"chat_id": ("chat", "id"), "query_index": ("query", "index")},
    },
}

# Daily rows keep changing while late chats for the day arrive, so re-read the two latest days.
INCREMENTAL_LOOKBACK_SECONDS = {
    name: 2 * 24 * 60 * 60 for name, endpoint in ENDPOINTS.items() if endpoint.get("daily", False)
}

INCREMENTAL_FIELDS = {
    name: [incremental_field("date", IncrementalFieldType.Date)]
    for name in ("chats", "brand_report", "domain_report", "url_report", "search_fanout_queries")
}

AUTH_ERRORS = {
    400: "Peec AI rejected the request. Check your API key, project ID, and start date.",
    401: "Your Peec AI API key is invalid. Create a new key and reconnect.",
    403: "Peec AI denied access. Check that your key can read this project and your plan includes API access.",
}
