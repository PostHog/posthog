from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = {
    "bank_accounts": ("organization", "organization.bank_accounts"),
    "transactions": ("transactions", "transactions"),
    "labels": ("labels", "labels"),
    "memberships": ("memberships", "memberships"),
    "transfers": ("sepa/transfers", "transfers"),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "updated_at",
            "field": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name in ("transactions", "transfers")
}

AUTH_ERROR = "Qonto rejected the credentials. Check your organization login and secret key."
PERMISSION_ERROR = "Qonto denied access. Check that your account can read the selected data."
