from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, frozen, incremental_field

API_DOCS_URL = "https://docs.klarna.com/acquirer/klarna/api/settlements/"
DISPUTES_DOCS_URL = "https://docs.klarna.com/acquirer/klarna/api/disputes-api-v4/"
PAGE_SIZE = 500

BASE_URLS = {
    "live": {
        "eu": "https://api.klarna.com",
        "na": "https://api-na.klarna.com",
        "oc": "https://api-oc.klarna.com",
    },
    "playground": {
        "eu": "https://api.playground.klarna.com",
        "na": "https://api-na.playground.klarna.com",
        "oc": "https://api-oc.playground.klarna.com",
    },
}


@frozen
class KlarnaEndpoint:
    # `{api_version}` is the pinned Settlements API version.
    path: str
    data_selector: str
    primary_keys: list[str] | None
    partition_key: str
    pagination: Literal["offset", "cursor"] = "offset"


ENDPOINTS: dict[str, KlarnaEndpoint] = {
    "payouts": KlarnaEndpoint(
        path="settlements/{api_version}/payouts",
        data_selector="payouts",
        primary_keys=["payment_reference"],
        partition_key="payout_date",
    ),
    # Transactions have no unique ID. Full refresh preserves repeated fees and adjustments.
    "transactions": KlarnaEndpoint(
        path="settlements/{api_version}/transactions",
        data_selector="transactions",
        primary_keys=None,
        partition_key="capture_date",
    ),
    # The Disputes API has its own version (v4) and cursor pagination.
    "disputes": KlarnaEndpoint(
        path="v4/payment/disputes",
        data_selector="disputes",
        primary_keys=["payment_dispute_id"],
        partition_key="created_at",
        pagination="cursor",
    ),
}

# Payout date filters need account verification. Transactions document no timestamp filter.
# Disputes filter on `<field>_start`, but can only sort by created_at or closed_at.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "disputes": [incremental_field("updated_at"), incremental_field("created_at")],
}
