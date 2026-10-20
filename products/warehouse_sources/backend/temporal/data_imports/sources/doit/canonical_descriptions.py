"""Canonical, documentation-sourced descriptions for the fixed DoIt tables.

Sourced from the official DoiT API reference (https://developer.doit.com/openapi/doit-api.yaml).
Keyed by the names in `settings.py` `DOIT_ENDPOINTS`. Report tables have account-specific columns,
so they have no entry here and fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Budgets": {
        "description": (
            "A DoiT budget: a spend limit for a scope of cloud costs over a period, with its current "
            "utilization, forecast, and risk status."
        ),
        "docs_url": "https://developer.doit.com/reference/listbudgets",
        "columns": {
            "id": "Unique identifier for the budget.",
            "budget_name": "Name of the budget.",
            "amount": "Budget limit for the period, in the budget currency.",
            "currency": "Currency of the budget amount.",
            "current_utilization": "Spend so far in the current budget period.",
            "forecasted_utilization_date": "Forecasted time the budget is reached, in milliseconds since the epoch.",
            "risk_status": "Server-computed risk classification: `atRisk`, `onTrack`, or `unknown`.",
            "scopes": "The filters that define which costs count toward the budget.",
            "time_interval": "Length of each budget period.",
            "start_period": "Start of the budget, in milliseconds since the epoch.",
            "end_period": "End of the budget, in milliseconds since the epoch.",
            "create_time": "Time the budget was created, in milliseconds since the epoch.",
            "update_time": "Time the budget was last changed, in milliseconds since the epoch.",
        },
    },
    "Insights": {
        "description": (
            "A DoiT insight: an optimization opportunity or risk found in the cloud environment, with "
            "aggregate savings and risk counts across its affected resources."
        ),
        "docs_url": "https://developer.doit.com/openapi/doit-api.yaml",
        "columns": {
            "source": "The source that generated the insight.",
            "key": "Key that identifies the insight within its source.",
            "title": "Display title of the insight.",
            "short_description": "Brief summary of the insight.",
            "display_status": "Display status, for example `actionable`, `optimized`, or `dismissed`.",
            "cloud_provider": "Cloud provider of the affected resources.",
            "categories": "Categories the insight belongs to, for example `FinOps` or `Security`.",
            "summary": "Aggregate summary of risks and savings across all resource results for the insight.",
            "last_updated": "Time of the last update to the insight.",
        },
    },
    "Anomalies": {
        "description": (
            "A cloud cost anomaly DoiT detected: spend above the expected normal range for a service or SKU."
        ),
        "docs_url": "https://developer.doit.com/reference/listanomalies",
        "columns": {
            "id": "Unique identifier for the anomaly.",
            "platform": "Cloud provider name.",
            "billing_account": "Billing account ID.",
            "service_name": "Service the anomaly was detected on.",
            "severity_level": "Severity level: `information`, `warning`, or `critical`.",
            "cost_of_anomaly": "Excess cost above the expected normal cost.",
            "actual_cost": "Observed cost during the anomaly.",
            "expected_max_cost": "Maximum cost within the expected normal range.",
            "start_time": "Usage start time of the anomaly, in milliseconds since the epoch.",
            "end_time": "End of the anomaly, in milliseconds since the epoch.",
            "status": "Whether the anomaly is `active` or `inactive`.",
            "acknowledged": "Whether a user has acknowledged the anomaly.",
        },
    },
    "Invoices": {
        "description": "A current or historical DoiT invoice, with its total, outstanding balance, and payment status.",
        "docs_url": "https://developer.doit.com/reference/listinvoices",
        "columns": {
            "id": "Invoice number.",
            "platform": "Platform the invoice is for, for example `google-cloud` or `amazon-web-services`.",
            "invoice_date": "Time the invoice was issued, in milliseconds since the epoch.",
            "due_date": "Last day to pay the invoice, in milliseconds since the epoch.",
            "status": "Invoice status: `OPEN`, `PAST DUE`, or `PAID`.",
            "total_amount": "Total invoiced amount.",
            "balance_amount": "Invoice balance still to be paid.",
            "currency": "Currency of the amounts.",
        },
    },
}
