from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.mercadopago.com"
PAGE_SIZE = 20
ENDPOINTS = {
    "payments": "/v1/payments/search",
    "subscriptions": "/preapproval/search",
    "subscription_plans": "/preapproval_plan/search",
}
PRIMARY_KEYS = ["id"]
PARTITION_KEYS = ["date_created"]
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "payments": [
        {
            "field": "date_last_updated",
            "label": "date_last_updated",
            "type": IncrementalFieldType.DateTime,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
}
AUTH_ERROR = "Mercado Pago rejected the access token. Check your production access token and its permissions."
