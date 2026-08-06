from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Region/environment-specific REST hosts — credentials only work against
# their tenant's environment.
ZUORA_ENVIRONMENT_HOSTS: dict[str, str] = {
    "us_production": "https://rest.zuora.com",
    "us_api_sandbox": "https://rest.apisandbox.zuora.com",
    "us_cloud_production": "https://rest.na.zuora.com",
    "us_cloud_sandbox": "https://rest.sandbox.na.zuora.com",
    "eu_production": "https://rest.eu.zuora.com",
    "eu_sandbox": "https://rest.sandbox.eu.zuora.com",
    "central_sandbox": "https://rest.test.zuora.com",
}

# Object Query pages cap at 99 records.
PAGE_SIZE = 99

# Every Object Query object filters server-side on updateddate (lowercase in
# filters, camelCase in rows) — all streams are honestly incremental.
_UPDATED_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updatedDate",
        "type": IncrementalFieldType.DateTime,
        "field": "updatedDate",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# Stream name -> Object Query path segment under /object-query/.
ZUORA_ENDPOINTS: dict[str, str] = {
    "accounts": "accounts",
    "subscriptions": "subscriptions",
    "invoices": "invoices",
    "payments": "payments",
    "credit_memos": "credit-memos",
    "refunds": "refunds",
    "products": "products",
    "orders": "orders",
}

ENDPOINTS = tuple(ZUORA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(_UPDATED_DATE_INCREMENTAL_FIELDS) for name in ZUORA_ENDPOINTS
}
