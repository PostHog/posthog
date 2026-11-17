from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

# Xendit's public API only exposes a few list endpoints that enumerate a merchant's own records:
# `GET /transactions` (the unified money-movement ledger), `GET /v2/accounts` (xenPlatform
# sub-accounts), `GET /v1/disputes` and `GET /bill-payments/v1/product`. Everything else in the
# current API reference is either a single-object lookup (payments, payouts, sessions, balance), a
# search that requires an exact identifier (`GET /customers` requires `reference_id`), or a child
# collection with no way to enumerate its parents (`GET /recurring/plans/{id}/cycles`), so none of
# them can be synced as a table.
#
# Transactions and accounts page via `after_id` + `has_more` and filter on `created[gte]` /
# `updated[gte]`. Disputes and bill payment products page via a `cursor` param taken from the
# response body.

XENDIT_BASE_URL = "https://api.xendit.co"

# `limit` is documented as capped at 50 on /v2/accounts. /transactions documents a default of 10 but
# no maximum, so use the one cap Xendit publishes for this pagination style rather than guessing higher.
PAGE_SIZE = 50


@dataclass(frozen=False)
class XenditEndpointConfig:
    name: str
    path: str
    # Timestamp fields the endpoint filters on server-side, as `<field>[gte]` query params.
    filterable_timestamps: tuple[str, ...] = ()
    partition_key: str | None = "created"
    # Sub-account listing only returns data for xenPlatform accounts, so it is off by default.
    should_sync_default: bool = True
    permission: str = ""
    extra_params: dict[str, str] = field(default_factory=dict)
    page_size: int = PAGE_SIZE
    cursor_param: str = "after_id"
    # Body path of the next-page cursor. Empty means the cursor is the last row's `id`.
    next_cursor_path: tuple[str, ...] = ()
    # Body path of the "more pages" flag. None means a non-empty next cursor is the only signal.
    has_more_path: tuple[str, ...] | None = ("has_more",)

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return [
            {
                "label": name,
                "type": IncrementalFieldType.DateTime,
                "field": name,
                "field_type": IncrementalFieldType.DateTime,
            }
            for name in self.filterable_timestamps
        ]


XENDIT_ENDPOINTS: dict[str, XenditEndpointConfig] = {
    "transactions": XenditEndpointConfig(
        name="transactions",
        path="/transactions",
        filterable_timestamps=("updated", "created"),
        permission="Transaction Read",
    ),
    "accounts": XenditEndpointConfig(
        name="accounts",
        path="/v2/accounts",
        filterable_timestamps=("updated", "created"),
        should_sync_default=False,
        permission="Accounts Read",
    ),
    # Disputes change status and outcome after creation, but the API filters only on creation
    # time (`created_after`), so an incremental sync would miss those changes.
    "disputes": XenditEndpointConfig(
        name="disputes",
        path="/v1/disputes",
        partition_key="created_at",
        permission="Disputes Read",
        page_size=100,
        cursor_param="cursor",
        next_cursor_path=("pagination", "next_cursor"),
        has_more_path=("pagination", "has_more"),
    ),
    # A catalog of billers' products with no timestamps. Only useful to bill payment merchants.
    "bill_payment_products": XenditEndpointConfig(
        name="bill_payment_products",
        path="/bill-payments/v1/product",
        partition_key=None,
        should_sync_default=False,
        permission="Bill Payments Read",
        cursor_param="cursor",
        next_cursor_path=("next_cursor",),
        has_more_path=None,
    ),
}

ENDPOINTS = tuple(XENDIT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in XENDIT_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in XENDIT_ENDPOINTS.items()}

# Default cursor field when a schema has no explicit selection.
DEFAULT_INCREMENTAL_FIELD = "updated"
