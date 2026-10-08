"""Canonical, documentation-sourced descriptions for CloudZero endpoints and columns.

Sourced from the official CloudZero API v2 reference (https://docs.cloudzero.com/reference).
Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced CloudZero table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Budgets": {
        "description": (
            "A budget defined in CloudZero: a monthly planned spend limit for a saved view, with "
            "optional alert thresholds. Sync this alongside Costs to compare planned against actual spend."
        ),
        "docs_url": "https://docs.cloudzero.com/reference/getbudgets",
        "columns": {
            "id": "Unique identifier for the budget.",
            "name": "Name given to the budget in CloudZero.",
            "view": "The saved view the budget applies to, as an object holding the view's `id`.",
            "granularity": "Period each planned limit covers. CloudZero only supports `monthly`.",
            "cost_type": "Cost basis the budget is measured against. CloudZero only supports `real_cost`.",
            "planned_limits": "Planned spend per period, mapping each period's ISO start date to an `amount`.",
            "alerts": "Alert configuration, mapping a percentage of the planned limit to `Y` or `N`.",
            "current": "Actual and planned spend for the current period, returned because PostHog requests `expand=current`.",
            "created": "Unix epoch timestamp of when the budget was created.",
            "last_updated": "Unix epoch timestamp of the last change to the budget.",
        },
    },
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
    "Insights": {
        "description": (
            "A cost insight: a piece of cost work tracked in CloudZero, carrying its estimated dollar "
            "impact, effort, and status as it moves from new to addressed."
        ),
        "docs_url": "https://docs.cloudzero.com/reference/getinsights",
        "columns": {
            "id": "Unique identifier for the insight.",
            "title": "Short title of the insight.",
            "description": "Longer description of the cost opportunity or anomaly.",
            "category": "Category the insight belongs to.",
            "status": "Where the insight is in its workflow: `new`, `in_progress`, `on_hold`, `addressed` or `ignored`.",
            "effort": "Estimated effort to act on the insight: `not_set`, `low`, `medium` or `high`.",
            "cost_impact": "Estimated dollar impact of acting on the insight.",
            "link": "Link to the insight in the CloudZero app.",
            "created": "Unix epoch timestamp of when the insight was created.",
            "last_updated": "Unix epoch timestamp of the last change to the insight.",
        },
    },
    "Recommendations": {
        "description": (
            "A savings recommendation CloudZero generated for one resource, with the spend it could save "
            "over the last 30 days. CloudZero only returns recommendations at or above a $1.00 30-day cost "
            "impact by default, so lower-impact recommendations are not in this table."
        ),
        "docs_url": "https://docs.cloudzero.com/reference/get_all_v2_optimize_recommendations_get",
        "columns": {
            "recommendation_id": "Unique identifier for the recommendation.",
            "title": "Short description of the change CloudZero recommends.",
            "category": "Category of the recommendation, for example `optimization`.",
            "recommendation_type_id": "Identifier of the recommendation type, joins to the RecommendationTypes table's `id`.",
            "optimization_id": "Deprecated by CloudZero in favour of `recommendation_type_id`.",
            "source": "Who produced the recommendation, for example `CloudZero` or `AWS: Trusted Advisor`.",
            "status": "Progress on the recommendation: `not_started`, `in_progress`, `addressed` or `ignored`.",
            "effort": "Estimated effort to apply the recommendation: `not_set`, `low`, `medium` or `high`.",
            "cost_impact_last_30_days": "Spend the recommendation could have saved over the last 30 days.",
            "realized_savings_last_30_days": "Spend already saved over the last 30 days by applying the recommendation.",
            "work_item": "Reference to a ticket for this recommendation in an external tracker, for example Jira.",
            "resource": "Identifier of the cloud resource the recommendation applies to.",
            "resource_type": "Type of the cloud resource the recommendation applies to.",
            "resource_name": "Name of the cloud resource the recommendation applies to.",
            "account": "Cloud accounts the resource belongs to.",
            "cloud_provider": "Cloud providers the resource belongs to.",
            "region": "Cloud regions the resource runs in.",
            "service": "Cloud services the resource belongs to.",
            "cluster": "Kubernetes clusters the resource belongs to, for Kubernetes recommendations.",
            "namespace": "Kubernetes namespaces the resource belongs to, for Kubernetes recommendations.",
            "pod": "Kubernetes pods the resource belongs to, for Kubernetes recommendations.",
            "created": "Unix epoch timestamp of when CloudZero raised the recommendation.",
            "addressed_on_ts": "Unix epoch timestamp of when the recommendation was marked addressed.",
        },
    },
    "RecommendationTypes": {
        "description": (
            "A recommendation type: the pattern CloudZero evaluates to produce recommendations, such as "
            "rightsizing an over-provisioned instance. Resolves the `recommendation_type_id` on the "
            "Recommendations table."
        ),
        "docs_url": "https://docs.cloudzero.com/reference/list_all_recommendation_types",
        "columns": {
            "id": "Unique identifier of the recommendation type, for example `CIR-AWS-00216`.",
            "title": "Title of the recommendation type.",
            "description": "What the recommendation type looks for and why it saves money.",
            "cloud_provider": "Cloud provider the type applies to: `AWS`, `Azure`, `GCP`, `Kubernetes`, `Databricks` or `Unknown`.",
            "category": "Category of the type, for example `waste`, `reservation` or `optimization`.",
            "effort": "Typical effort to act on this type: `not_set`, `low`, `medium` or `high`.",
            "status": "Whether your organization has the type `enabled` or `disabled`.",
            "stage": "Maturity of the type in CloudZero: `alpha`, `beta`, `stable` or `unknown`.",
        },
    },
}
