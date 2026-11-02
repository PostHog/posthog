from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class JustCallEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    # User-timezone date field the JustCall `from_datetime` filter aligns with. When set, the
    # endpoint supports server-side incremental sync (rows are requested ascending with
    # `sort=datetime` and bounded by `from_datetime`), and this field doubles as the stable
    # datetime partition key. When None the endpoint is full refresh only.
    #
    # JustCall exposes both UTC (`call_date`) and account-timezone (`call_user_date`) date fields;
    # `from_datetime` is documented as being interpreted in the account timezone, so the cursor
    # must be the `_user_` variant for the watermark and the filter to agree.
    incremental_cursor: Optional[str] = None
    # `order` casing differs per endpoint in JustCall's API (calls/texts accept lowercase
    # `asc`/`desc`; phone-numbers documents uppercase `ASC`/`DESC`). Ascending keeps already-paged
    # results stable under concurrent inserts and lets the incremental watermark advance monotonically.
    order: str = "asc"
    # Per-endpoint page-size cap where JustCall documents a lower maximum than the default of 100.
    page_size: Optional[int] = None
    extra_params: dict[str, Any] = field(default_factory=dict)


def _incremental_fields(cursor: str) -> list[IncrementalField]:
    # JustCall's `_user_date` fields are `yyyy-mm-dd` strings, so the DB field type is Date even
    # though the UI presents a datetime cursor. Day-granularity is intentional: `from_datetime`
    # re-fetches the boundary day each sync and the primary-key merge dedupes the overlap.
    return [
        {
            "label": cursor,
            "type": IncrementalFieldType.DateTime,
            "field": cursor,
            "field_type": IncrementalFieldType.Date,
        }
    ]


# Endpoints are the JustCall v2.1 list resources a warehouse user is most likely to want:
# telephony (calls), messaging (texts), the sales-dialer contact-center calls, plus the
# supporting dimensions (contacts, users, user groups, phone numbers, campaigns), and the per-call
# JustCall AI analysis. Analytics/aggregate endpoints are intentionally excluded — they return
# computed rollups, not raw records.
JUSTCALL_ENDPOINTS: dict[str, JustCallEndpointConfig] = {
    "calls": JustCallEndpointConfig(
        name="calls",
        path="/calls",
        incremental_cursor="call_user_date",
    ),
    "texts": JustCallEndpointConfig(
        name="texts",
        path="/texts",
        incremental_cursor="sms_user_date",
    ),
    "sales_dialer_calls": JustCallEndpointConfig(
        name="sales_dialer_calls",
        path="/sales_dialer/calls",
        # Sales Dialer calls key their id under `call_id`, not `id`.
        primary_key="call_id",
        incremental_cursor="call_user_date",
    ),
    "contacts": JustCallEndpointConfig(
        name="contacts",
        path="/contacts",
    ),
    "users": JustCallEndpointConfig(
        name="users",
        path="/users",
    ),
    "phone_numbers": JustCallEndpointConfig(
        name="phone_numbers",
        path="/phone-numbers",
        order="ASC",
    ),
    "user_groups": JustCallEndpointConfig(
        name="user_groups",
        path="/user_groups",
    ),
    # Campaign status and contact counts change after creation, so a creation-date
    # `from_datetime` filter would miss updates; campaigns are a small table, so full refresh.
    "sales_dialer_campaigns": JustCallEndpointConfig(
        name="sales_dialer_campaigns",
        path="/sales_dialer/campaigns",
        page_size=50,
    ),
    # Rows carry no date field to use as a cursor, so full refresh. Only JustCall-platform calls are
    # requested: `id` is the call id, which is not unique across the JustCall and Sales Dialer platforms.
    "calls_ai": JustCallEndpointConfig(
        name="calls_ai",
        path="/calls_ai",
        page_size=20,
        extra_params={"platform": "justcall", "fetch_transcription": "true"},
    ),
}

ENDPOINTS = tuple(JUSTCALL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: _incremental_fields(config.incremental_cursor)
    for name, config in JUSTCALL_ENDPOINTS.items()
    if config.incremental_cursor
}
