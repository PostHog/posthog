from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "CreditUnits",
    "Customers",
    "Disputes",
    "Einvoices",
    "Events",
    "Invoices",
    "ItemPrices",
    "Items",
    "Meters",
    "Orders",
    "PaymentSchedules",
    "Subscriptions",
    "Transactions",
)

INCREMENTAL_ENDPOINTS = (
    "Customers",
    "Einvoices",
    "Events",
    "Invoices",
    "ItemPrices",
    "Items",
    "Orders",
    "PaymentSchedules",
    "Subscriptions",
    "Transactions",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Customers": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Einvoices": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Events": [
        {
            "label": "occurred_at",
            "type": IncrementalFieldType.DateTime,
            "field": "occurred_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Invoices": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "ItemPrices": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Items": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Orders": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "PaymentSchedules": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Subscriptions": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Transactions": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
}
