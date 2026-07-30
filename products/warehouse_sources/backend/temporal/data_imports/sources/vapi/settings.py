from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

VAPI_BASE_URL = "https://api.vapi.ai"

# Vapi caps `limit` at 1000 (default 100). Call/chat objects can be large (full transcripts,
# message arrays, cost breakdowns), so keep pages at 100 rows to bound per-request memory.
DEFAULT_PAGE_LIMIT = 100

# How the endpoint paginates:
# - "created_at_cursor": returns a bare array in createdAt-descending order; the next page is
#   requested with `createdAtLt=<oldest createdAt of the previous page>`.
# - "page": returns a `{results, metadata}` envelope with `page`/`sortOrder`/`sortBy` params.
# - "none": returns the full collection in a single unpaginated array.
VapiPaginationStyle = Literal["created_at_cursor", "page", "none"]


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class VapiEndpointConfig:
    name: str
    path: str
    pagination: VapiPaginationStyle
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field used for partitioning. None disables partitioning.
    partition_key: Optional[str] = "createdAt"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


VAPI_ENDPOINTS: dict[str, VapiEndpointConfig] = {
    # Calls is the flagship stream: transcripts, analysis, ended reasons, durations, and cost
    # breakdowns. createdAt is the safe default cursor; updatedAt also has a server-side filter
    # (`updatedAtGt`) and re-syncs calls whose analysis/artifacts were attached after the call ended.
    "calls": VapiEndpointConfig(
        name="calls",
        path="/call",
        pagination="created_at_cursor",
        incremental_fields=[
            _datetime_incremental_field("createdAt"),
            _datetime_incremental_field("updatedAt"),
        ],
    ),
    # Assistants/phone numbers/squads/tools are small config tables that mutate in place, so a
    # createdAt watermark would go stale immediately; full refresh keeps them correct and cheap.
    "assistants": VapiEndpointConfig(
        name="assistants",
        path="/assistant",
        pagination="created_at_cursor",
    ),
    "phone_numbers": VapiEndpointConfig(
        name="phone_numbers",
        path="/phone-number",
        pagination="created_at_cursor",
    ),
    "squads": VapiEndpointConfig(
        name="squads",
        path="/squad",
        pagination="created_at_cursor",
    ),
    "tools": VapiEndpointConfig(
        name="tools",
        path="/tool",
        pagination="created_at_cursor",
    ),
    # GET /file takes no pagination params at all — single unpaginated array.
    "files": VapiEndpointConfig(
        name="files",
        path="/file",
        pagination="none",
        partition_key=None,
    ),
    # Page-based endpoints are requested with sortOrder=ASC&sortBy=createdAt so rows arrive in
    # ascending createdAt order. Only createdAt is offered as an incremental field: the API can't
    # sort by updatedAt, and an updatedAt watermark over createdAt-ordered pages would checkpoint
    # values that later pages can undercut, losing rows on the next sync.
    "chats": VapiEndpointConfig(
        name="chats",
        path="/chat",
        pagination="page",
        incremental_fields=[_datetime_incremental_field("createdAt")],
    ),
    "sessions": VapiEndpointConfig(
        name="sessions",
        path="/session",
        pagination="page",
        incremental_fields=[_datetime_incremental_field("createdAt")],
    ),
    # Campaigns mutate heavily (status plus per-call counters), so createdAt-incremental would go
    # stale immediately; the table is small, so full refresh only.
    "campaigns": VapiEndpointConfig(
        name="campaigns",
        path="/campaign",
        pagination="page",
    ),
}

ENDPOINTS = tuple(VAPI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in VAPI_ENDPOINTS.items()
}
