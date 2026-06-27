"""Canonical, documentation-sourced descriptions for ChartMogul endpoints and columns.

Sourced from the official ChartMogul API reference (https://dev.chartmogul.com/reference).
Keyed by the endpoint names in `settings.py` `CHARTMOGUL_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced ChartMogul table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "A ChartMogul customer aggregating subscription and billing activity.",
        "docs_url": "https://dev.chartmogul.com/reference/list-customers",
        "columns": {
            "uuid": "Unique identifier for the customer in ChartMogul.",
            "external_id": "Identifier of the customer in the source billing system.",
            "data_source_uuid": "UUID of the data source the customer was imported from.",
            "name": "Customer's name.",
            "company": "Company name associated with the customer.",
            "email": "Customer's email address.",
            "status": "Lifecycle status of the customer (e.g. Active, Lead, Cancelled).",
            "customer-since": "Date the customer first became active.",
            "customer_since": "Date and time the customer first started paying for a subscription.",
            "billing_system_url": "URL for this customer's data in the source billing system, if available.",
            "mrr": "Customer's current monthly recurring revenue.",
            "arr": "Customer's current annual run rate.",
            "currency": "Three-letter ISO currency code used for the customer.",
            "country": "Customer's country code.",
            "city": "Customer's city.",
            "lead_created_at": "Time at which the customer was created as a lead.",
            "free_trial_started_at": "Time at which the customer's free trial started.",
        },
    },
    "plans": {
        "description": "A billing plan that subscriptions are sold against.",
        "docs_url": "https://dev.chartmogul.com/reference/list-plans",
        "columns": {
            "uuid": "Unique identifier for the plan in ChartMogul.",
            "external_id": "Identifier of the plan in the source billing system.",
            "data_source_uuid": "UUID of the data source the plan was imported from.",
            "name": "Name of the plan.",
            "interval_count": "Number of intervals between billings.",
            "interval_unit": "Unit of the billing interval (day, month, or year).",
        },
    },
    "plan_groups": {
        "description": "A grouping of related plans for combined reporting.",
        "docs_url": "https://dev.chartmogul.com/reference/list-plan-groups",
        "columns": {
            "uuid": "Unique identifier for the plan group in ChartMogul.",
            "name": "Name of the plan group.",
            "plans_count": "Number of plans contained in the group.",
        },
    },
    "invoices": {
        "description": "An invoice imported into ChartMogul, with its line items and transactions.",
        "docs_url": "https://dev.chartmogul.com/reference/list-invoices",
        "columns": {
            "uuid": "Unique identifier for the invoice in ChartMogul.",
            "external_id": "Identifier of the invoice in the source billing system.",
            "customer_uuid": "UUID of the customer the invoice belongs to.",
            "data_source_uuid": "UUID of the data source the invoice was imported from.",
            "date": "Date the invoice was issued.",
            "due_date": "Date the invoice payment is due.",
            "currency": "Three-letter ISO currency code of the invoice.",
            "line_items": "Line items (subscriptions or one-off charges) on the invoice.",
            "transactions": "Payment and refund transactions recorded against the invoice.",
        },
    },
    "activities": {
        "description": "A subscription activity (new business, expansion, churn, etc.) tracked by ChartMogul.",
        "docs_url": "https://dev.chartmogul.com/reference/list-activities",
        "columns": {
            "uuid": "Unique identifier for the activity.",
            "date": "Date and time the activity occurred.",
            "type": "Type of activity (e.g. new_biz, expansion, contraction, churn, reactivation).",
            "activity-mrr": "MRR associated with the activity.",
            "activity-mrr-movement": "Change in MRR caused by the activity.",
            "currency": "Three-letter ISO currency code of the activity.",
            "subscription-external-id": "External identifier of the subscription the activity relates to.",
            "plan-external-id": "External identifier of the plan the activity relates to.",
            "customer-name": "Name of the customer the activity relates to.",
            "customer-uuid": "UUID of the customer the activity relates to.",
        },
    },
    "data_sources": {
        "description": "A configured ChartMogul data source that billing data is imported through.",
        "docs_url": "https://dev.chartmogul.com/reference/list-data-sources",
        "columns": {
            "uuid": "Unique identifier for the data source.",
            "name": "Name of the data source.",
            "status": "Current status of the data source (e.g. idle, importing).",
            "created_at": "Time at which the data source was created.",
        },
    },
}
