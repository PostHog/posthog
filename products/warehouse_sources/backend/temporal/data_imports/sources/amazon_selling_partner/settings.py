from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

SP_API_HOSTS = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}
LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"

ORDERS_PATH = "/orders/2026-01-01/orders"
TRANSACTIONS_PATH = "/finances/2024-06-19/transactions"
INVENTORY_SUMMARIES_PATH = "/fba/inventory/v1/summaries"
MARKETPLACE_PARTICIPATIONS_PATH = "/sellers/v1/marketplaceParticipations"

ORDERS_PAGE_SIZE = 100
# BUYER and RECIPIENT are left out: they carry PII and need restricted roles on the app.
ORDERS_INCLUDED_DATA = "FULFILLMENT,PROCEEDS,EXPENSE,PROMOTION,CANCELLATION,PACKAGES,TAX,PAYMENT"
# listTransactions answers with an empty page when postedAfter and postedBefore are over 180 days apart.
TRANSACTIONS_WINDOW_DAYS = 179
# Amazon rejects a window end closer than two minutes to the request time.
REQUEST_TIME_MARGIN_SECONDS = 180
# The oldest order data any marketplace keeps (JP, AU and SG keep orders from 2016).
EARLIEST_START = "2016-01-01T00:00:00Z"
# getInventorySummaries rejects a startDateTime more than 18 months before the call.
INVENTORY_MAX_LOOKBACK_DAYS = 540
# Financial events can post up to 48 hours late, and a deferred transaction changes status when released.
TRANSACTIONS_LOOKBACK_SECONDS = 3 * 24 * 60 * 60

ORDERS = "orders"
ORDER_ITEMS = "order_items"
TRANSACTIONS = "transactions"
INVENTORY_SUMMARIES = "inventory_summaries"

ENDPOINTS = (ORDERS, ORDER_ITEMS, TRANSACTIONS, INVENTORY_SUMMARIES)

PRIMARY_KEYS: dict[str, list[str]] = {
    ORDERS: ["orderId"],
    ORDER_ITEMS: ["orderId", "orderItemId"],
    TRANSACTIONS: ["transactionId"],
    INVENTORY_SUMMARIES: ["marketplaceId", "sellerSku"],
}

PARTITION_KEYS: dict[str, str] = {
    ORDERS: "createdTime",
    ORDER_ITEMS: "createdTime",
    TRANSACTIONS: "postedDate",
}


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ORDERS: [_datetime_field("lastUpdatedTime")],
    ORDER_ITEMS: [_datetime_field("lastUpdatedTime")],
    TRANSACTIONS: [_datetime_field("postedDate")],
    INVENTORY_SUMMARIES: [_datetime_field("lastUpdatedTime")],
}

DEFAULT_INCREMENTAL_LOOKBACK_SECONDS: dict[str, int] = {TRANSACTIONS: TRANSACTIONS_LOOKBACK_SECONDS}
