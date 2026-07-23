"""Canonical, documentation-sourced descriptions for CloudZero endpoints and columns.

Sourced from the official CloudZero API v2 reference (https://docs.cloudzero.com/reference).
Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced CloudZero table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Costs": {
        "description": (
            "A time-series row of cloud/SaaS spend for a single usage period (hour/day/week/month/year), "
            "optionally broken down by one or more CostFormation dimensions (e.g. service, account)."
        ),
        "docs_url": "https://docs.cloudzero.com/reference/getbillingcosts",
        "columns": {
            "usage_date": "Start of the usage period this row covers, as an ISO 8601 datetime.",
            "cost": "Cost for the usage period (and dimension breakdown, if grouped), in the configured cost_type.",
            "projected_row_count": "Projected total number of rows for the query, only present when include_projected_row_count is requested.",
        },
    },
    "Dimensions": {
        "description": "A CostFormation dimension available to group or filter cost data by (e.g. service, account, team).",
        "docs_url": "https://docs.cloudzero.com/reference/getbillingdimensions",
        "columns": {
            "id": "Dimension identifier, used as a `group_by` value or a `filters` key when querying costs.",
            "name": "Human-readable name of the dimension shown in the CloudZero Explorer.",
        },
    },
}
