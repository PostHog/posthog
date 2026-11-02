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
    "Assets": {
        "description": "A DoiT asset: a cloud billing account or licensed subscription, such as a Google Workspace or Microsoft 365 subscription.",
        "docs_url": "https://developer.doit.com/openapi/doit-api.yaml",
        "columns": {
            "id": "Unique identifier of the asset.",
            "name": "Readable label for the asset, usually the product name with the domain or account ID.",
            "type": "Asset type, for example `g-suite`, `office-365`, `google-cloud`, or `amazon-web-services`.",
            "quantity": "Number of licenses or seats assigned to the asset.",
            "create_time": "Time the asset was created, in milliseconds since the epoch.",
            "url": "Link to the asset details page in the DoiT console.",
        },
    },
    "Annotations": {
        "description": "A DoiT annotation: a note attached to a date in cloud cost reports, for example a deployment or a pricing change.",
        "docs_url": "https://developer.doit.com/openapi/doit-api.yaml",
        "columns": {
            "id": "Unique identifier of the annotation.",
            "content": "Text of the annotation.",
            "timestamp": "Date the annotation refers to.",
            "reports": "IDs of the reports the annotation is attached to.",
            "labels": "Labels on the annotation, each with an `id` and a `name`.",
            "create_time": "Time the annotation was created.",
            "update_time": "Time the annotation was last updated.",
        },
    },
    "SupportTickets": {
        "description": "A support request opened with DoiT, with its severity, status, and the product it concerns.",
        "docs_url": "https://developer.doit.com/openapi/doit-api.yaml",
        "columns": {
            "id": "Ticket ID.",
            "subject": "Subject of the ticket.",
            "requester": "Email address of the person who opened the ticket.",
            "severity": "Severity of the ticket.",
            "status": "Status of the ticket.",
            "platform": "Platform the ticket is about.",
            "product": "Product the ticket is about.",
            "is_public": "Whether the ticket is public.",
            "tags": "Tags on the ticket.",
            "create_time": "Time the ticket was created, in milliseconds since the epoch.",
            "update_time": "Time the ticket was last updated, in milliseconds since the epoch.",
            "url_ui": "Link to the ticket in the DoiT console.",
        },
    },
    "InsightResourceResults": {
        "description": "A cloud resource affected by a DoiT insight, with the savings or risk the insight finds for that resource.",
        "docs_url": "https://developer.doit.com/openapi/doit-api.yaml",
        "columns": {
            "insight_source": "Source of the insight the result belongs to. Joins to `source` in the insights table.",
            "insight_key": "Key of the insight the result belongs to. Joins to `key` in the insights table.",
            "resource_id": "Cloud resource identifier.",
            "resource_type": "Kind of resource, for example `instance` for an EC2 resource.",
            "cloud_provider": "Cloud provider of the resource.",
            "account": "Cloud account or project ID that contains the resource.",
            "location": "Region or zone of the resource.",
            "resolved": "Whether the issue on this resource is resolved.",
            "severity": "Severity of the finding.",
            "external_id": "ID of the resource in the provider's system.",
            "external_url": "URL of the issue in the provider's system.",
            "result_type": "Kind of result, which sets the fields that `result` contains.",
            "result": "Result data, for example the daily saving amount or the security risk counts.",
            "metadata": "Additional information about the resource result.",
            "enhancement": "DoiT-managed metadata on the result, such as tags and priority.",
        },
    },
}
