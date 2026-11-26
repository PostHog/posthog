from datetime import timedelta

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, PaginatorConfig

BASE_URL = "https://api.mercadopago.com"
PAGE_SIZE = 20
ENDPOINTS = {
    "payments": "/v1/payments/search",
    "subscriptions": "/preapproval/search",
    "subscription_plans": "/preapproval_plan/search",
    "payment_methods": "/v1/payment_methods",
    "customers": "/v1/customers/search",
    "merchant_orders": "/merchant_orders/search",
    "authorized_payments": "/authorized_payments/search",
}
DATA_SELECTORS = {"payment_methods": "$", "merchant_orders": "elements"}
DEFAULT_DATA_SELECTOR = "results"
PAGINATORS: dict[str, PaginatorConfig] = {
    "payment_methods": "single_page",
    "merchant_orders": {"type": "offset", "limit": PAGE_SIZE, "total_path": "total"},
}
PRIMARY_KEYS = ["id"]
PARTITION_KEYS = ["date_created"]
UNPARTITIONED_ENDPOINTS = {"payment_methods"}
# Merchant order searches only return orders from the last 90 days.
MERCHANT_ORDER_HISTORY = timedelta(days=90)
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "payments": [
        {
            "field": "date_last_updated",
            "label": "date_last_updated",
            "type": IncrementalFieldType.DateTime,
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "merchant_orders": [
        {
            "field": "last_updated",
            "label": "last_updated",
            "type": IncrementalFieldType.DateTime,
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
MERGE_ONLY_ENDPOINTS = {"payments", "merchant_orders"}
AUTH_ERROR = "Mercado Pago rejected the access token. Check your production access token and its permissions."
