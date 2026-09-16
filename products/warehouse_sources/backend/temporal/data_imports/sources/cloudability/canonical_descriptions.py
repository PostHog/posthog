"""Canonical, documentation-sourced descriptions for Cloudability endpoints and columns.

Sourced from IBM's Cloudability v3 API reference (see each entry's `docs_url`). Keyed by the
resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Cloudability table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Costs": {
        "description": "Cloud cost and usage totals grouped by vendor, account, region, and service, "
        "over a trailing window. Fully replaced each sync to absorb late vendor billing restatements.",
        "docs_url": "https://www.ibm.com/docs/en/cloudability-commercial/cloudability-standard/saas?topic=api-cost-reporting-end-point",
        "columns": {
            "vendor": "Cloud vendor the cost was billed by (for example AWS, Azure, or GCP).",
            "linked_account_name": "Display name of the linked cloud account the cost was billed to.",
            "region": "Cloud provider region the usage occurred in.",
            "enhanced_service_name": "Cloudability-normalized name of the cloud service the cost was billed for.",
            "unblended_cost": "Cost as billed by the vendor, before amortization or discounts are applied.",
            "total_amortized_cost": "Cost with upfront and recurring charges (for example reserved instance fees) spread evenly across their term.",
            "usage_hours": "Number of hours the resource was in use during the reporting window.",
        },
    },
    "Views": {
        "description": "A saved set of filters that scopes cost and usage data to a subset of accounts, "
        "tags, or business dimensions.",
        "docs_url": "https://www.ibm.com/docs/en/SSXUJG/cloudability/api/v3/views_end_point.htm",
        "columns": {
            "id": "Unique identifier for the view.",
            "title": "Display name of the view.",
            "description": "Description of what the view scopes to.",
            "ownerId": "Identifier of the user who owns the view.",
            "ownerEmail": "Email address of the user who owns the view.",
            "sharedWithOrganization": "Whether the view is shared with the whole organization.",
            "sharedWithUsers": "User IDs the view has been explicitly shared with.",
            "filters": "The filter rules that scope this view's data.",
        },
    },
    "BusinessMappingDimensions": {
        "description": "A rule-based custom dimension that allocates cloud spend to cost centers, "
        "products, environments, or applications.",
        "docs_url": "https://www.ibm.com/docs/en/cloudability-commercial/cloudability-premium/saas?topic=api-business-mappings-end-point",
        "columns": {
            "name": "Unique identifier for the business dimension.",
            "index": "Numeric slot (1-10) the dimension occupies.",
            "kind": "Always 'BUSINESS_DIMENSION' for this endpoint.",
            "defaultValue": "Value assigned when no statement matches a cost row.",
            "statements": "Ordered matching rules, each mapping a match expression to a value.",
        },
    },
    "BusinessMappingMetrics": {
        "description": "A rule-based custom metric computed from cloud cost and usage data, such as a "
        "cost allocated by a business formula.",
        "docs_url": "https://www.ibm.com/docs/en/cloudability-commercial/cloudability-premium/saas?topic=api-business-mappings-end-point",
        "columns": {
            "name": "Unique identifier for the business metric.",
            "index": "Numeric slot the metric occupies.",
            "kind": "Always 'BUSINESS_METRIC' for this endpoint.",
            "numberFormat": "Display format for the metric's value, 'currency' or 'number'.",
            "defaultValueExpression": "Fallback expression evaluated when no statement matches.",
            "preMatchExpression": "Expression evaluated globally before per-row statements.",
            "statements": "Ordered conditional rules used to compute the metric's value.",
            "updatedAt": "Time the metric definition was last updated.",
        },
    },
    "Anomalies": {
        "description": "A cost anomaly Cloudability detected, such as a first-time or unusually large "
        "spend on a service.",
        "docs_url": "https://www.ibm.com/docs/en/cloudability-commercial/cloudability-premium/saas?topic=v3-anomaly-detection-end-point",
        "columns": {
            "id": "Unique identifier for the anomaly.",
            "date": "Date the anomalous spend occurred.",
            "type": "Category of anomaly detected.",
            "vendor": "Cloud vendor the anomalous spend was billed by.",
            "vendorAccountName": "Display name of the cloud account the anomalous spend occurred on.",
            "enhancedServiceName": "Cloudability-normalized name of the service the anomaly was detected on.",
            "usageFamily": "Broader usage category the anomalous service belongs to.",
            "unblendedCost": "Actual cost billed for the anomalous spend.",
            "unusualSpend": "Dollar amount by which the spend exceeded the expected baseline.",
            "unusualSpendPercentage": "Percentage by which the spend exceeded the expected baseline.",
            "currencyCode": "Currency the cost amounts are denominated in.",
            "tags": "Cost allocation tags associated with the anomalous resource.",
            "businessDimensions": "Business mapping dimension values associated with the anomalous resource.",
            "issueFields": "Additional fields describing the specific issue detected.",
        },
    },
}
