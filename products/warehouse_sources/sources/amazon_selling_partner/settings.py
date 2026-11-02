from datetime import timedelta

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
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
REPORTS_PATH = "/reports/2021-06-30/reports"
REPORT_DOCUMENTS_PATH = "/reports/2021-06-30/documents"

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
# no Retry-After. Nine attempts wait 1, 2, 4 ... 128 seconds, 255 in all, past that interval and
# inside the shared retry budget, which ends a request 300 seconds after its first try.
SP_API_MAX_RETRY_ATTEMPTS = 9
SP_API_RETRY_BACKOFF_MAX_SECONDS = 128.0

ORDERS = "orders"
ORDER_ITEMS = "order_items"
TRANSACTIONS = "transactions"
INVENTORY_SUMMARIES = "inventory_summaries"
VENDOR_SALES = "vendor_sales"
VENDOR_INVENTORY = "vendor_inventory"
VENDOR_NET_PURE_PRODUCT_MARGIN = "vendor_net_pure_product_margin"
VENDOR_FORECASTS = "vendor_forecasts"
VENDOR_REAL_TIME_SALES = "vendor_real_time_sales"


@frozen
class VendorReport:
    report_type: str
    # The key of the row list in the report document.
    rows_key: str
    options: dict[str, str]
    # None for a report that takes no date range, such as the latest forecast.
    window: timedelta | None = None
    lookback: timedelta | None = None
    # Amazon publishes a period's data some time after the period closes.
    availability_delay: timedelta = timedelta(0)
    hourly: bool = False
    needs_currency: bool = False


_RETAIL_OPTIONS = {"reportPeriod": "DAY", "distributorView": "MANUFACTURING", "sellingProgram": "RETAIL"}
# Daily retail analytics: 1,460 days back, final 72 hours after the day closes. Amazon allows 15 days
# per request, but 7 keeps one document of a large catalog small enough to parse in memory.
_DAILY_WINDOW = timedelta(days=7)
_DAILY_LOOKBACK = timedelta(days=1459)
_DAILY_DELAY = timedelta(days=4)

VENDOR_REPORTS: dict[str, VendorReport] = {
    VENDOR_SALES: VendorReport(
        report_type="GET_VENDOR_SALES_REPORT",
        rows_key="salesByAsin",
        options=_RETAIL_OPTIONS,
        window=_DAILY_WINDOW,
        lookback=_DAILY_LOOKBACK,
        availability_delay=_DAILY_DELAY,
    ),
    VENDOR_INVENTORY: VendorReport(
        report_type="GET_VENDOR_INVENTORY_REPORT",
        rows_key="inventoryByAsin",
        options=_RETAIL_OPTIONS,
        window=_DAILY_WINDOW,
        lookback=_DAILY_LOOKBACK,
        availability_delay=_DAILY_DELAY,
    ),
    VENDOR_NET_PURE_PRODUCT_MARGIN: VendorReport(
        report_type="GET_VENDOR_NET_PURE_PRODUCT_MARGIN_REPORT",
        rows_key="netPureProductMarginByAsin",
        options={"reportPeriod": "DAY"},
        window=_DAILY_WINDOW,
        lookback=_DAILY_LOOKBACK,
        availability_delay=_DAILY_DELAY,
    ),
    VENDOR_FORECASTS: VendorReport(
        report_type="GET_VENDOR_FORECASTING_REPORT", rows_key="forecastByAsin", options={"sellingProgram": "RETAIL"}
    ),
    # Hourly, 30 days back, requestable five minutes after the hour closes. Amazon allows 14 days per
    # request, but one day keeps a document small enough to parse in memory for a large catalog.
    VENDOR_REAL_TIME_SALES: VendorReport(
        report_type="GET_VENDOR_REAL_TIME_SALES_REPORT",
        rows_key="reportData",
        options={},
        window=timedelta(days=1),
        lookback=timedelta(days=29),
        availability_delay=timedelta(minutes=5),
        hourly=True,
        needs_currency=True,
    ),
}

# Real-time sales reports ask for the currency of the marketplace they cover.
MARKETPLACE_CURRENCIES: dict[str, str] = {
    "A2EUQ1WTGCTBG2": "CAD",
    "ATVPDKIKX0DER": "USD",
    "A1AM78C64UM0Y8": "MXN",
    "A2Q3Y263D00KWC": "BRL",
    "A28R8C7NBKEWEA": "EUR",
    "A1RKKUPIHCS9HS": "EUR",
    "A1F83G8C2ARO7P": "GBP",
    "A13V1IB3VIYZZH": "EUR",
    "AMEN7PMS3EDWL": "EUR",
    "A1805IZSGTT6HS": "EUR",
    "A1PA6795UKMFR9": "EUR",
    "APJ6JRA9NG5V4": "EUR",
    "A2NODRKZP88ZB9": "SEK",
    "AE08WJ6YKNBMC": "ZAR",
    "A1C3SOZRARQ6R3": "PLN",
    "ARBP9OOSHTCHU": "EGP",
    "A33AVAJ2PDY3EV": "TRY",
    "A17E79C6D8DWNP": "SAR",
    "A2VIGQ35RCS4UG": "AED",
    "A21TJRUUN4KGV": "INR",
    "A19VAU5U5O7RUS": "SGD",
    "A39IBJ37TRP1C6": "AUD",
    "A1VC38T7YXB528": "JPY",
}

SELLER_ENDPOINTS = (ORDERS, ORDER_ITEMS, TRANSACTIONS, INVENTORY_SUMMARIES)
ENDPOINTS = (*SELLER_ENDPOINTS, *VENDOR_REPORTS)

PRIMARY_KEYS: dict[str, list[str]] = {
    ORDERS: ["orderId"],
    ORDER_ITEMS: ["orderId", "orderItemId"],
    TRANSACTIONS: ["transactionId"],
    INVENTORY_SUMMARIES: ["marketplaceId", "sellerSku"],
    VENDOR_SALES: ["marketplaceId", "asin", "startDate"],
    VENDOR_INVENTORY: ["marketplaceId", "asin", "startDate"],
    VENDOR_NET_PURE_PRODUCT_MARGIN: ["marketplaceId", "asin", "startDate"],
    VENDOR_FORECASTS: ["marketplaceId", "asin", "startDate"],
    VENDOR_REAL_TIME_SALES: ["marketplaceId", "asin", "startTime"],
}

PARTITION_KEYS: dict[str, str] = {
    ORDERS: "createdTime",
    ORDER_ITEMS: "createdTime",
    TRANSACTIONS: "postedDate",
    VENDOR_SALES: "startDate",
    VENDOR_INVENTORY: "startDate",
    VENDOR_NET_PURE_PRODUCT_MARGIN: "startDate",
    VENDOR_REAL_TIME_SALES: "startTime",
}


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ORDERS: [incremental_field("lastUpdatedTime")],
    ORDER_ITEMS: [incremental_field("lastUpdatedTime")],
    TRANSACTIONS: [incremental_field("postedDate")],
    VENDOR_SALES: [incremental_field("startDate", IncrementalFieldType.Date)],
    VENDOR_INVENTORY: [incremental_field("startDate", IncrementalFieldType.Date)],
    VENDOR_NET_PURE_PRODUCT_MARGIN: [incremental_field("startDate", IncrementalFieldType.Date)],
    VENDOR_REAL_TIME_SALES: [incremental_field("startTime")],
}

DEFAULT_INCREMENTAL_LOOKBACK_SECONDS: dict[str, int] = {TRANSACTIONS: TRANSACTIONS_LOOKBACK_SECONDS}
