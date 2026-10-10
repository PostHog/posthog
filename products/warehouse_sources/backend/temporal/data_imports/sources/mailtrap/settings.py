from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class MailtrapEndpointConfig:
    name: str
    path: str
    # Key wrapping the rows in the response body; None means the body is a bare JSON array.
    data_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Cursor query param for paginated endpoints (None = single-request endpoint).
    cursor_param: Optional[str] = None
    # Where the next cursor comes from: a top-level response field, or the last row's field.
    cursor_response_key: Optional[str] = None
    cursor_row_field: Optional[str] = None
    # Page size the API caps responses at; used to detect the last page when the API exposes no
    # explicit next-page signal (suppressions).
    page_size: Optional[int] = None
    # Server-side lower-bound timestamp query param for incremental syncs.
    incremental_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field used for partitioning (creation/send time, never an updated_at).
    partition_key: Optional[str] = None
    # Static query params sent on every request (page sizes).
    params: dict[str, Any] = field(default_factory=dict)
    # Endpoint requires a `start_date`/`end_date` window (stats endpoints).
    date_range: bool = False
    # Nested object whose keys are lifted onto the row root.
    flatten_field: Optional[str] = None


# Mailtrap REST API list endpoints (https://mailtrap.io/api, Api-Token header auth). All paths are
# token-scoped: results cover every account/domain the token can access, so no account_id is needed.
#
# Incremental sync:
# - email_logs exposes a server-side `filters[sent_after]` bound and cursor pagination via
#   `search_after`/`next_page_cursor`; results are ordered by sent_at descending.
# - suppressions exposes a server-side `start_time` (created-at) bound and `last_id` cursor
#   pagination, capped at 1000 rows per request.
# Both are declared sort_mode="desc" so the incremental watermark only commits once a sync
# completes (suppressions ordering is undocumented; email logs are documented newest-first).
# - contacts and email_campaigns paginate via `token` / `pagination.next_token` but expose no
#   timestamp filter: full refresh only.
# - sending_stats_by_date requires a date window and returns one row per day in a single response.
#   It stays full refresh because past days' open/click counts keep changing after the send date.
# The remaining endpoints return unpaginated arrays with no timestamp filter: full refresh only.
MAILTRAP_ENDPOINTS: dict[str, MailtrapEndpointConfig] = {
    "email_logs": MailtrapEndpointConfig(
        name="email_logs",
        path="/api/email_logs",
        data_key="messages",
        primary_keys=["message_id"],
        cursor_param="search_after",
        cursor_response_key="next_page_cursor",
        incremental_param="filters[sent_after]",
        incremental_fields=[
            {
                "label": "sent_at",
                "type": IncrementalFieldType.DateTime,
                "field": "sent_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_key="sent_at",
    ),
    "suppressions": MailtrapEndpointConfig(
        name="suppressions",
        path="/api/suppressions",
        cursor_param="last_id",
        cursor_row_field="id",
        page_size=1000,
        incremental_param="start_time",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_key="created_at",
    ),
    "email_templates": MailtrapEndpointConfig(name="email_templates", path="/api/email_templates"),
    "contact_lists": MailtrapEndpointConfig(name="contact_lists", path="/api/contacts/lists"),
    "sending_domains": MailtrapEndpointConfig(name="sending_domains", path="/api/domains", data_key="data"),
    "accounts": MailtrapEndpointConfig(name="accounts", path="/api/accounts"),
    "contacts": MailtrapEndpointConfig(
        name="contacts",
        path="/api/contacts",
        data_key="data",
        cursor_param="token",
        cursor_response_key="pagination.next_token",
        params={"per_page": 50},
    ),
    "email_campaigns": MailtrapEndpointConfig(
        name="email_campaigns",
        path="/api/email_campaigns",
        data_key="data",
        cursor_param="token",
        cursor_response_key="pagination.next_token",
        params={"per_page": 100},
        partition_key="created_at",
    ),
    "sending_stats_by_date": MailtrapEndpointConfig(
        name="sending_stats_by_date",
        path="/api/stats/date",
        primary_keys=["date"],
        date_range=True,
        flatten_field="stats",
        partition_key="date",
    ),
}

ENDPOINTS = tuple(MAILTRAP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: config.incremental_fields for endpoint, config in MAILTRAP_ENDPOINTS.items() if config.incremental_fields
}
