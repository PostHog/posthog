from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

API_DOCS_URL = "https://docs.klarna.com/acquirer/klarna/api/settlements/"
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
    path: str
    data_selector: str
    primary_keys: list[str] | None
    partition_key: str


ENDPOINTS: dict[str, KlarnaEndpoint] = {
    "payouts": KlarnaEndpoint(
        path="payouts", data_selector="payouts", primary_keys=["payment_reference"], partition_key="payout_date"
    ),
    # Transactions have no unique ID. Full refresh preserves repeated fees and adjustments.
    "transactions": KlarnaEndpoint(
        path="transactions", data_selector="transactions", primary_keys=None, partition_key="capture_date"
    ),
}

# Payout date filters need account verification. Transactions document no timestamp filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
