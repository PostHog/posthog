from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "billing_accounts": {
        "description": "A Google Cloud billing account, which resources are charged to and which projects can be linked to.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/rest/v1/billingAccounts",
        "columns": {
            "name": "Resource name of the billing account, in the form `billingAccounts/012345-567890-ABCDEF`.",
            "open": "True when the billing account is open and active, so resources billed to it can be used.",
            "displayName": "Display name given to the billing account, for example `My Billing Account`.",
            "masterBillingAccount": "Resource name of the parent billing account, set only when this account is a subaccount.",
            "parent": "Resource name of the organization or billing account this billing account belongs to.",
            "currencyCode": "ISO-4217 currency code the billing account is billed in.",
        },
    },
    "projects": {
        "description": "The link between a Google Cloud project and the billing account it is charged to.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/rest/v1/billingAccounts.projects",
        "columns": {
            "name": "Resource name of the project billing info, in the form `projects/tokyo-rain-123/billingInfo`.",
            "projectId": "ID of the project this billing information belongs to.",
            "billingAccountName": "Resource name of the billing account the project is linked to, empty when the project has none.",
            "billingEnabled": "True when the project is linked to an open billing account, so its usage is charged.",
            "_billing_account_name": "Resource name of the billing account this row was listed under. Added by PostHog.",
        },
    },
    "sub_accounts": {
        "description": "Billing subaccounts owned by a reseller's master billing account. Same shape as a billing account.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/rest/v1/billingAccounts/list",
        "columns": {
            "name": "Resource name of the subaccount, in the form `billingAccounts/012345-567890-ABCDEF`.",
            "open": "True when the subaccount is open and active.",
            "displayName": "Display name given to the subaccount.",
            "masterBillingAccount": "Resource name of the master billing account that owns this subaccount.",
            "currencyCode": "ISO-4217 currency code the subaccount is billed in.",
            "_billing_account_name": "Resource name of the master billing account this row was listed under. Added by PostHog.",
        },
    },
    "services": {
        "description": "A Google Cloud service that is billed for, such as Compute Engine or BigQuery.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/rest/v1/services",
        "columns": {
            "name": "Resource name of the service, in the form `services/6F81-5844-456A`.",
            "serviceId": "Identifier for the service, for example `6F81-5844-456A`.",
            "displayName": "Human readable name of the service, for example `BigQuery`.",
            "businessEntityName": "Business entity the service is offered under, for example `businessEntities/GCP`.",
        },
    },
    "skus": {
        "description": "A billable SKU within a Google Cloud service, including its public list price over time.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/rest/v1/services.skus",
        "columns": {
            "name": "Resource name of the SKU, in the form `services/DA34-426B-A397/skus/AA95-CD31-42FE`.",
            "skuId": "Identifier for the SKU, for example `AA95-CD31-42FE`.",
            "description": "Human readable description of the SKU, for example `Nearline Storage US`.",
            "category": "Category hierarchy of the SKU: service display name, resource family, resource group, and usage type.",
            "serviceRegions": "Regions the SKU is offered in.",
            "pricingInfo": "Timeline of pricing for the SKU, including tiered rates, the currency, and the usage units the rates apply to.",
            "serviceProviderName": "Provider of the service, for example `Google`.",
            "geoTaxonomy": "Geographic taxonomy of the SKU: whether it is global, regional, or multi-regional, and the regions covered.",
            "_service_name": "Resource name of the service this SKU belongs to. Added by PostHog.",
        },
    },
    "budgets": {
        "description": "A budget set on a billing account, with its scope, amount, and alert thresholds.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/budget/rest/v1/billingAccounts.budgets",
        "columns": {
            "name": "Resource name of the budget, in the form `billingAccounts/012345-567890-ABCDEF/budgets/<budget-id>`.",
            "displayName": "Name of the budget as shown in the Google Cloud console.",
            "budgetFilter": "Filters that decide which projects, services, labels, and credits count towards the budget.",
            "amount": "Budgeted amount, either a fixed amount or the amount spent in the previous period.",
            "thresholdRules": "Rules that trigger an alert when spend reaches a percentage of the budgeted amount.",
            "notificationsRule": "How alerts are delivered, for example the Pub/Sub topic and whether billing admins are emailed.",
            "ownershipScope": "Who the budget is visible to, either billing account level or project level.",
            "etag": "Etag used for optimistic concurrency control when the budget is updated.",
            "_billing_account_name": "Resource name of the billing account this budget belongs to. Added by PostHog.",
        },
    },
}
