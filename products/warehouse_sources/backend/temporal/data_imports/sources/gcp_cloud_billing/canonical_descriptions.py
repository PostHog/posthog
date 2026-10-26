from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "billing_accounts": {
        "description": "Billing accounts accessible to the service account.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/rest/v1/billingAccounts",
        "columns": {
            "name": "The billing account resource name.",
            "displayName": "The billing account name shown in Google Cloud.",
            "open": "Whether the billing account can pay for usage.",
            "masterBillingAccount": "The parent billing account for a reseller subaccount.",
            "currencyCode": "The currency used by the billing account.",
        },
    },
    "projects": {
        "description": "Projects linked to each accessible billing account.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/rest/v1/billingAccounts.projects",
        "columns": {
            "name": "The resource name for the project's billing information.",
            "projectId": "The Google Cloud project ID.",
            "billingAccountName": "The billing account that pays for this project.",
            "billingEnabled": "Whether the project has active billing.",
            "parent_billing_account": "The billing account used to list this project.",
        },
    },
    "sub_accounts": {
        "description": "Billing subaccounts under each accessible reseller account.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/rest/v1/billingAccounts.subAccounts/list",
        "columns": {
            "name": "The billing subaccount resource name.",
            "displayName": "The billing subaccount name shown in Google Cloud.",
            "masterBillingAccount": "The parent billing account for this subaccount.",
            "parent_billing_account": "The billing account used to list this subaccount.",
        },
    },
    "services": {
        "description": "Google Cloud services in the public price catalog.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/rest/v1/services",
        "columns": {
            "name": "The service resource name.",
            "serviceId": "The unique identifier for the service.",
            "displayName": "The service name shown in Google Cloud.",
            "businessEntityName": "The business entity that provides the service.",
        },
    },
    "skus": {
        "description": "Public SKUs and their latest prices in USD for each Google Cloud service.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/rest/v1/services.skus",
        "columns": {
            "name": "The SKU resource name, including its service.",
            "skuId": "The unique identifier for the SKU.",
            "description": "The description of the billable resource.",
            "category": "The service and resource categories for the SKU.",
            "serviceRegions": "The regions where the SKU is available.",
            "pricingInfo": "The pricing expressions and their effective times.",
            "parent_service": "The service used to list this SKU.",
        },
    },
    "budgets": {
        "description": "Budget amounts, cost filters, thresholds, and notification settings for each accessible billing account.",
        "docs_url": "https://cloud.google.com/billing/docs/reference/budget/rest/v1/billingAccounts.budgets",
        "columns": {
            "name": "The budget resource name, including its billing account.",
            "displayName": "The budget name shown in Google Cloud.",
            "amount": "The configured budget amount.",
            "budgetFilter": "The cost filters that define which usage the budget tracks.",
            "thresholdRules": "The thresholds that trigger budget alerts.",
            "allUpdatesRule": "The notification settings for budget updates.",
            "parent_billing_account": "The billing account used to list this budget.",
        },
    },
}
