"""Canonical, documentation-sourced descriptions for AppsFlyer aggregate Pull API reports and columns.

Sourced from the official AppsFlyer Pull API / aggregate report reference
(https://support.appsflyer.com/hc/en-us/articles/207034366-Pull-APIs-aggregate-and-raw-data).
Keyed by the report names in `settings.py` `APPSFLYER_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced AppsFlyer table. Column names are the CSV headers normalized to
snake_case (see `_normalize_header`); columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Columns shared across the aggregate-by-date reports (CSV headers normalized to snake_case).
_COMMON_COLUMNS = {
    "date": "Date the aggregated metrics are reported for.",
    "agency_pmd_af_prt": "Agency or PMD partner attributed to the activity (af_prt).",
    "media_source_pid": "Media source the traffic is attributed to (pid).",
    "campaign_c": "Campaign name the activity is attributed to (c).",
    "impressions": "Number of ad impressions in the period.",
    "clicks": "Number of ad clicks in the period.",
    "ctr": "Click-through rate (clicks divided by impressions).",
    "installs": "Number of attributed app installs in the period.",
    "conversion_rate": "Install conversion rate (installs divided by clicks).",
    "cost": "Total ad spend in the period.",
    "revenue": "Total revenue attributed in the period.",
    "roi": "Return on investment (revenue relative to cost).",
    "average_ecpi": "Average effective cost per install.",
    "loyal_users": "Number of users classified as loyal in the period.",
    "loyal_users_installs": "Ratio of loyal users to installs.",
    "total_revenue": "Total revenue attributed across all events in the period.",
    "total_cost": "Total cost attributed across the period.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "daily_report": {
        "description": "Daily aggregate performance per media source and campaign — installs, clicks, cost, and revenue by date.",
        "docs_url": "https://support.appsflyer.com/hc/en-us/articles/207034366-Pull-APIs-aggregate-and-raw-data",
        "columns": _columns(),
    },
    "geo_report": {
        "description": "Daily aggregate performance broken down by country, in addition to media source and campaign.",
        "docs_url": "https://support.appsflyer.com/hc/en-us/articles/207034366-Pull-APIs-aggregate-and-raw-data",
        "columns": _columns(
            country="Country the aggregated metrics are reported for.",
        ),
    },
    "partners_report": {
        "description": "Daily aggregate performance broken down by attribution partner (media source).",
        "docs_url": "https://support.appsflyer.com/hc/en-us/articles/207034366-Pull-APIs-aggregate-and-raw-data",
        "columns": _columns(),
    },
}
