from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = {
    "bank_accounts": ("organization", "organization.bank_accounts"),
    "transactions": ("transactions", "transactions"),
    "labels": ("labels", "labels"),
    "memberships": ("memberships", "memberships"),
    "transfers": ("sepa/transfers", "transfers"),
    "beneficiaries": ("sepa/beneficiaries", "beneficiaries"),
    "client_invoices": ("client_invoices", "client_invoices"),
    "supplier_invoices": ("supplier_invoices", "supplier_invoices"),
    "credit_notes": ("credit_notes", "credit_notes"),
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
    for name in ("transactions", "transfers", "supplier_invoices")
}

# Qonto's supplier invoice sync guide pages through updates in ascending order.
SORT_ORDER: dict[str, Literal["asc", "desc"]] = {
    "transactions": "desc",
    "transfers": "desc",
    "supplier_invoices": "asc",
}

AUTH_ERROR = "Qonto rejected the credentials. Check your organization login and secret key."
PERMISSION_ERROR = "Qonto denied access. Check that your account can read the selected data."
