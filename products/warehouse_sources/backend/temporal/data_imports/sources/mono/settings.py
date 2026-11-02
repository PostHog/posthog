from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.withmono.com"
# Relative paths follow the pinned API version. Mono serves bank coverage, Direct Debit and Disburse only on v3.
ENDPOINTS = {
    "customers": "customers",
    "accounts": "accounts",
    "transactions": "accounts/{account_id}/transactions",
    "institutions": f"{BASE_URL}/v3/institutions",
    "payments": "payments/transactions",
    "mandates": f"{BASE_URL}/v3/payments/mandates",
    "mandate_debits": f"{BASE_URL}/v3/payments/mandates/debits",
    "payouts": "payments/payouts",
    "disbursements": f"{BASE_URL}/v3/payments/disburse/disbursements",
    "disbursement_distributions": f"{BASE_URL}/v3/payments/disburse/disbursements/{{batch_id}}/distributions",
    "income_records": "accounts/{account_id}/income-records",
}
PRIMARY_KEYS = {
    "customers": ["id"],
    "accounts": ["id"],
    "transactions": ["account_id", "id"],
    "institutions": ["id"],
    "payments": ["id"],
    "mandates": ["id"],
    "mandate_debits": ["mandate", "reference"],
    "payouts": ["id"],
    "disbursements": ["id"],
    "disbursement_distributions": ["batch_id", "id"],
    # Income records carry no id, so the account and the assessment time identify a record.
    "income_records": ["account_id", "created_at"],
}
# Child endpoint -> (parent endpoint, path placeholder that takes the parent id).
FANOUT_PARENTS = {
    "transactions": ("accounts", "account_id"),
    "income_records": ("accounts", "account_id"),
    "disbursement_distributions": ("disbursements", "batch_id"),
}
DATA_SELECTORS = {
    "payments": "data.payments",
    "payouts": "data.payouts",
    "disbursements": "data.disbursements",
    "disbursement_distributions": "data.distributions",
}
# Mono requires a payout status and documents only "settled".
PAYOUT_STATUS = "settled"
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "transactions": [
        {
            "field": "date",
            "type": IncrementalFieldType.DateTime,
            "label": "date",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "payments": [
        {
            "field": "created_at",
            "type": IncrementalFieldType.DateTime,
            "label": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "mandate_debits": [
        {
            "field": "date",
            "type": IncrementalFieldType.DateTime,
            "label": "date",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
# Date filter query params and their formats for each incremental endpoint.
DATE_FILTERS = {
    "transactions": ("start", "end", "%d-%m-%Y"),
    "payments": ("start", "end", "%d-%m-%Y"),
    "mandate_debits": ("start_date", "end_date", "%Y-%m-%d"),
}
PAGE_SIZE = 100
AUTH_ERROR = "Mono rejected the secret API key. Copy the secret key from your Mono app and reconnect."
PERMISSION_ERROR = "Mono denied access. Check that your Mono app has access to the requested data."
