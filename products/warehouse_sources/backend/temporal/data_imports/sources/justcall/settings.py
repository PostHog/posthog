from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
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
# supporting dimensions (contacts, users, phone numbers). Analytics/aggregate endpoints are
# intentionally excluded — they return computed rollups, not raw records.
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
}

ENDPOINTS = tuple(JUSTCALL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: _incremental_fields(config.incremental_cursor)
    for name, config in JUSTCALL_ENDPOINTS.items()
    if config.incremental_cursor
}
