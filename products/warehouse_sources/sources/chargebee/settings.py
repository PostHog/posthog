from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Coupons",
    "CreditNotes",
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
    "PaymentSources",
    "Subscriptions",
    "Transactions",
    "Usages",
)

INCREMENTAL_ENDPOINTS = (
    "CreditNotes",
    "Customers",
    "Einvoices",
    "Events",
    "Invoices",
    "ItemPrices",
    "Items",
    "Orders",
    "PaymentSchedules",
    "PaymentSources",
    "Subscriptions",
    "Transactions",
    "Usages",
)

# Usages are read through `/subscriptions/{id}/usages`, so their `id` is only documented as unique
# per subscription.
PRIMARY_KEYS: dict[str, list[str]] = {
    "Usages": ["subscription_id", "id"],
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "CreditNotes": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
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
    "PaymentSources": [
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
    "Usages": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
}
