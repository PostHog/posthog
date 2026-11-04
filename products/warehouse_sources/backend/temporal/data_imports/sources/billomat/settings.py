from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Clients",
    "Suppliers",
    "Invoices",
    "Estimates",
    "CreditNotes",
    "Incomings",
    "InvoicePayments",
    "ClientContacts",
    "Confirmations",
    "Recurrings",
    "Reminders",
    "Articles",
    "DeliveryNotes",
    "ActivityFeed",
)

# An activity's `id` is the ID of the document it happened to (an invoice can have many
# activities), so no single field is unique across the feed.
PRIMARY_KEYS: dict[str, list[str]] = {
    "ActivityFeed": ["resource", "id", "date", "text"],
}

# Billomat's `from`/`to` list filters apply to the document `date`, not a last-modified
# timestamp, so this only catches new documents within a synced date window, not edits to
# existing ones (the API has no `updated_since`-style filter at all). Clients, Suppliers,
# ClientContacts, Recurrings, Articles and ActivityFeed have no date filter, so they stay
# full-refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Invoices": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "Estimates": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "CreditNotes": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "Incomings": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "InvoicePayments": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "Confirmations": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "Reminders": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "DeliveryNotes": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
}
