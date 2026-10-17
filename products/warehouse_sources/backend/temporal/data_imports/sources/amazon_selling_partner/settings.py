from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

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
# Financial events can post up to 48 hours late.
TRANSACTIONS_LOOKBACK_SECONDS = 3 * 24 * 60 * 60
# A deferred transaction keeps its postedDate when Amazon releases it, so each incremental run also
# re-reads the transactions released in this many days.
DEFERRED_RELEASE_SWEEP_DAYS = 60
# searchOrders refills at one request every 179 seconds once its burst is spent, and SP-API sends
# no Retry-After. Ten attempts wait 1, 2, 4 ... 128 then 180 seconds, 435 in all, past that interval.
SP_API_MAX_RETRY_ATTEMPTS = 10
SP_API_RETRY_BACKOFF_MAX_SECONDS = 180.0

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


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ORDERS: [incremental_field("lastUpdatedTime")],
    ORDER_ITEMS: [incremental_field("lastUpdatedTime")],
    TRANSACTIONS: [incremental_field("postedDate")],
}

DEFAULT_INCREMENTAL_LOOKBACK_SECONDS: dict[str, int] = {TRANSACTIONS: TRANSACTIONS_LOOKBACK_SECONDS}
