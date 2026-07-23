"""Canonical, documentation-sourced descriptions for Aiven endpoints and columns.

Sourced from the official Aiven API reference (https://api.aiven.io/doc). Keyed by the endpoint
names in `settings.py` `AIVEN_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Aiven table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "An Aiven project — the container that groups services and their billing.",
        "docs_url": "https://api.aiven.io/doc/#tag/Project",
        "columns": {
            "project_name": "Unique name of the project (its identifier).",
            "account_id": "Identifier of the account the project belongs to.",
            "organization_id": "Identifier of the organization the project belongs to.",
            "billing_group_id": "Identifier of the billing group the project is billed under.",
            "billing_currency": "Currency used for billing this project.",
            "default_cloud": "Default cloud region for services created in this project.",
            "estimated_balance": "Estimated unbilled balance for the current period.",
        },
    },
    "organizations": {
        "description": "An Aiven organization — the top-level tenant that owns projects and billing.",
        "docs_url": "https://api.aiven.io/doc/#tag/Organizations",
        "columns": {
            "organization_id": "Unique identifier of the organization.",
            "organization_name": "Display name of the organization.",
            "account_id": "Identifier of the underlying account.",
            "tier": "Subscription tier of the organization.",
            "create_time": "Timestamp when the organization was created.",
            "update_time": "Timestamp when the organization was last updated.",
        },
    },
    "services": {
        "description": "A running Aiven managed service (Kafka, PostgreSQL, ClickHouse, OpenSearch, etc.).",
        "docs_url": "https://api.aiven.io/doc/#tag/Service",
        "columns": {
            "project_name": "Name of the project the service belongs to (injected from the parent).",
            "service_name": "Name of the service (unique within its project).",
            "service_type": "Service type code (e.g. kafka, pg, clickhouse).",
            "cloud_name": "Cloud region the service runs in.",
            "plan": "Subscription plan of the service.",
            "state": "Current state of the service (e.g. RUNNING, POWEROFF).",
            "create_time": "Service creation timestamp (ISO 8601).",
            "update_time": "Service last update timestamp (ISO 8601).",
            "node_count": "Number of service nodes in the active plan.",
        },
    },
    "billing_groups": {
        "description": "A billing group that aggregates charges for one or more projects.",
        "docs_url": "https://api.aiven.io/doc/#tag/BillingGroup",
        "columns": {
            "billing_group_id": "Unique identifier of the billing group.",
            "billing_group_name": "Display name of the billing group.",
            "organization_id": "Identifier of the owning organization.",
            "payment_method": "Payment method used for the billing group.",
            "vat_id": "VAT identifier associated with the billing group.",
            "create_time": "Timestamp when the billing group was created.",
        },
    },
    "invoices": {
        "description": "An issued invoice for a billing group.",
        "docs_url": "https://api.aiven.io/doc/#tag/Invoice",
        "columns": {
            "invoice_number": "Invoice identifier.",
            "billing_group_id": "Identifier of the billing group the invoice is for.",
            "organization_id": "Identifier of the owning organization.",
            "currency": "Currency the invoice is denominated in.",
            "state": "State of the invoice (e.g. estimate, mailed, paid).",
            "net": "Total invoice amount without taxes, in local currency.",
            "net_usd": "Total invoice amount without taxes, in USD.",
            "total": "Total invoice amount including taxes, in local currency.",
            "total_usd": "Total invoice amount including taxes, in USD.",
            "invoice_period": "Billing period the invoice covers.",
            "issue_date": "Date the invoice was issued.",
            "due_date": "Date the invoice is due.",
            "create_time": "Date when the invoice was created.",
        },
    },
    "invoice_lines": {
        "description": "A single cost line on an invoice — the per-service breakdown used for BI cost export.",
        "docs_url": "https://api.aiven.io/doc/#tag/Invoice",
        "columns": {
            "invoice_number": "Invoice the line belongs to (injected from the parent).",
            "organization_id": "Owning organization identifier (injected from the parent).",
            "description": "Human-readable description of the line item.",
            "line_type": "Type of the line item.",
            "service_id": "Identifier of the service the charge is for.",
            "service_type": "Type of the service the charge is for.",
            "project_id": "Name of the project the charge is for.",
            "cloud": "Cloud provider/region the charge is for.",
            "plan": "Plan of the service being charged.",
            "begin_time": "Start timestamp of the line item's billing window.",
            "end_time": "End timestamp of the line item's billing window.",
            "total": "Total amount for the line, in local currency.",
            "total_usd": "Total amount for the line, in USD.",
            "currency": "Currency the line is denominated in.",
        },
    },
    "organization_users": {
        "description": "A member of an Aiven organization.",
        "docs_url": "https://api.aiven.io/doc/#tag/Organizations",
        "columns": {
            "organization_id": "Organization the membership is in (injected from the parent).",
            "user_id": "Unique identifier of the user.",
            "is_super_admin": "Whether the user is a super admin of the organization.",
            "join_time": "Timestamp when the user joined the organization.",
            "last_activity_time": "Timestamp of the user's last activity.",
        },
    },
    "user_groups": {
        "description": "A user group within an organization for grouping members and permissions.",
        "docs_url": "https://api.aiven.io/doc/#tag/Organizations",
        "columns": {
            "organization_id": "Organization the group belongs to (injected from the parent).",
            "user_group_id": "Unique identifier of the user group.",
            "user_group_name": "Display name of the user group.",
            "description": "Description of the user group.",
            "member_count": "Number of members in the group.",
            "managed_by_scim": "Whether the group is managed via SCIM.",
            "create_time": "Timestamp when the group was created.",
            "update_time": "Timestamp when the group was last updated.",
        },
    },
    "clouds": {
        "description": "Global catalogue of Aiven cloud regions across AWS, GCP and Azure.",
        "docs_url": "https://api.aiven.io/doc/#tag/Cloud",
        "columns": {
            "cloud_name": "Unique cloud region identifier (e.g. aws-eu-west-1).",
            "cloud_description": "Human-readable region description.",
            "provider": "Cloud provider code (aws, gcp, azure).",
            "provider_description": "Human-readable cloud provider name.",
            "geo_region": "Geographic region the cloud sits in.",
            "geo_latitude": "Latitude of the cloud region.",
            "geo_longitude": "Longitude of the cloud region.",
        },
    },
}
