from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DATE_DESCRIPTION = "UTC date used for the report's request window."
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Analytics": {
        "description": "Daily analytics for revenue, subscriptions, trials, refunds, and installs, with one row per chart and metric.",
        "docs_url": "https://adapty.io/docs/api-export-analytics/operations/retrieveAnalyticsData",
        "columns": {
            "date": _DATE_DESCRIPTION,
            "chart_id": "Chart requested from Adapty.",
            "metric": "Metric key from the response, such as revenue or proceeds.",
            "value": "Aggregate value for the requested date.",
            "data": "Nested data points returned by Adapty.",
            "unit": "Unit of the metric, such as USD or percent.",
        },
    },
    "Cohorts": {
        "description": "Daily revenue cohort reports with renewal values preserved in nested data.",
        "docs_url": "https://adapty.io/docs/api-export-analytics/operations/retrieveCohortData",
        "columns": {"date": _DATE_DESCRIPTION, "data": "Cohort segments with totals and renewal values."},
    },
    "Conversions": {
        "description": "Daily conversion reports from the first paid period to more than six months.",
        "docs_url": "https://adapty.io/docs/api-export-analytics/operations/retrieveConversionData",
        "columns": {
            "date": _DATE_DESCRIPTION,
            "data": "Nested conversion data points.",
            "value": "Aggregate conversion value.",
        },
    },
    "Funnels": {
        "description": "Daily funnel reports with absolute and relative values for each step.",
        "docs_url": "https://adapty.io/docs/api-export-analytics/operations/retrieveFunnelData",
        "columns": {"date": _DATE_DESCRIPTION, "data": "Funnel segments with nested steps and churn reasons."},
    },
    "LTV": {
        "description": "Daily lifetime value reports for revenue, proceeds, and net revenue, with nested renewal values.",
        "docs_url": "https://adapty.io/docs/api-export-analytics/operations/retrieveLTVData",
        "columns": {
            "date": _DATE_DESCRIPTION,
            "metric": "Accounting metric returned by Adapty.",
            "data": "LTV segments with renewal values and cohort sizes.",
            "value": "Aggregate lifetime value.",
            "unit": "Unit of the metric.",
        },
    },
    "Retention": {
        "description": "Daily subscription retention reports without the trial step.",
        "docs_url": "https://adapty.io/docs/api-export-analytics/operations/retrieveRetentionData",
        "columns": {"date": _DATE_DESCRIPTION, "data": "Nested subscription retention data points."},
    },
    "Paywalls": {
        "description": "Paywalls for the connected app, including products, state, and deletion status.",
        "docs_url": "https://adapty.io/docs/api-adapty/operations/listPaywalls",
        "columns": {
            "paywall_id": "Unique paywall identifier.",
            "title": "Paywall title.",
            "created_at": "Time the paywall was created.",
            "updated_at": "Time the paywall was last updated.",
            "is_deleted": "Whether the paywall is deleted.",
            "products": "Products and offers attached to the paywall.",
        },
    },
}
