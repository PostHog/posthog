"""Canonical, documentation-sourced descriptions for Azure Cost Management endpoints and columns.

Sourced from the official Microsoft.CostManagement REST reference
(https://learn.microsoft.com/en-us/rest/api/cost-management/). Keyed by the endpoint names in
`settings.py` `AZURE_COST_MANAGEMENT_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_QUERY_DOCS_URL = "https://learn.microsoft.com/en-us/rest/api/cost-management/query/usage"
_FORECAST_DOCS_URL = "https://learn.microsoft.com/en-us/rest/api/cost-management/forecast/usage"
_DIMENSIONS_DOCS_URL = "https://learn.microsoft.com/en-us/rest/api/cost-management/dimensions/list"

_SHARED_COST_COLUMNS = {
    "cost": "Summed cost for the day and grouping, in the scope's billing currency.",
    "usage_date": "Day the usage was metered, as YYYY-MM-DD.",
    "currency": "Billing currency the cost is reported in.",
    "scope": "Azure Resource Manager scope the cost was queried for (for example a subscription or billing account path).",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "cost_by_service": {
        "description": "Daily actual Azure cost, grouped by service. Actual cost reflects what was charged on the invoice, including one-off reservation purchases in the month they were bought.",
        "docs_url": _QUERY_DOCS_URL,
        "columns": {
            **_SHARED_COST_COLUMNS,
            "service_name": "Azure service the cost was incurred on, such as Virtual Machines or Storage.",
        },
    },
    "cost_by_resource_group": {
        "description": "Daily actual Azure cost, grouped by resource group — the usual unit for team or environment chargeback.",
        "docs_url": _QUERY_DOCS_URL,
        "columns": {
            **_SHARED_COST_COLUMNS,
            "resource_group_name": "Resource group the cost was incurred in.",
        },
    },
    "cost_by_resource": {
        "description": "Daily actual Azure cost, grouped by individual resource. The finest grain the query API reports, so it is also the widest table.",
        "docs_url": _QUERY_DOCS_URL,
        "columns": {
            **_SHARED_COST_COLUMNS,
            "resource_id": "Full Azure Resource Manager ID of the resource the cost was incurred on.",
        },
    },
    "amortized_cost_by_service": {
        "description": "Daily amortized Azure cost, grouped by service. Amortized cost spreads reservation and savings-plan purchases evenly across the term they cover, so daily spend reflects usage rather than purchase timing.",
        "docs_url": _QUERY_DOCS_URL,
        "columns": {
            **_SHARED_COST_COLUMNS,
            "service_name": "Azure service the cost was incurred on, such as Virtual Machines or Storage.",
        },
    },
    "forecast": {
        "description": "Azure's projection of upcoming daily cost per service, based on recent usage. Recomputed in full on every sync.",
        "docs_url": _FORECAST_DOCS_URL,
        "columns": {
            **_SHARED_COST_COLUMNS,
            "service_name": "Azure service the forecast cost is attributed to.",
            "cost_status": "Whether the row is a forecast or an actual charge.",
        },
    },
    "dimensions": {
        "description": "Dimensions available for grouping and filtering cost on this scope, with the values observed on each.",
        "docs_url": _DIMENSIONS_DOCS_URL,
        "columns": {
            "scope": "Azure Resource Manager scope the dimensions were listed for.",
            "id": "Full Azure Resource Manager ID of the dimension.",
            "name": "Dimension name, as used in a query's grouping or filter (for example ResourceGroupName).",
            "type": "Resource type of the dimension entry.",
            "category": "Category the dimension belongs to.",
            "description": "Description of what the dimension represents.",
            "filter_enabled": "Whether cost queries can filter on this dimension.",
            "grouping_enabled": "Whether cost queries can group by this dimension.",
            "usage_start": "Start of the period the returned dimension values were observed over.",
            "usage_end": "End of the period the returned dimension values were observed over.",
            "total": "Total number of values the dimension has over that period.",
            "data": "Sample of the dimension's values over that period.",
        },
    },
}
