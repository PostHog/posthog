"""Canonical, documentation-sourced descriptions for Singular tables and columns.

Sourced from the Singular Reporting API reference and the Metrics and Dimensions glossary
(https://support.singular.net/hc/en-us/articles/203389179). Keyed by the endpoint names in
`settings.py`. The `daily_report` columns depend on the dimensions and metrics a source is set up
with, so only the default ones are described here. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

REPORTING_API_URL = "https://support.singular.net/hc/en-us/articles/360045245692-Reporting-API-Reference"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "daily_report": {
        "description": "Daily campaign statistics from the Singular Reporting API, one row per day and combination of the chosen dimensions.",
        "docs_url": "https://support.singular.net/hc/en-us/articles/203389179-Metrics-and-Dimensions",
        "columns": {
            "date": "The day the row's statistics cover.",
            "app": "The app name as configured in the Apps page.",
            "source": "The name of the data source (usually the ad network).",
            "os": "The operating system of the marketed product, such as iOS or Android.",
            "country_field": "The user's country, as reported by the network or derived from the network's targeting settings.",
            "adn_campaign_id": "The ID of the campaign, as pulled from the ad network.",
            "adn_campaign_name": "The name of the campaign, as pulled from the ad network.",
            "adn_cost": "Cost (ad spend) reported by the ad network, in the default currency configured in Singular.",
            "adn_impressions": "The number of ad views as reported by the ad network.",
            "adn_clicks": "The number of ad clicks as reported by the ad network.",
            "adn_installs": "The number of app installs or total conversions as reported by the ad network.",
        },
    },
    "custom_dimensions": {
        "description": "A custom dimension defined in the Singular account. Use its ID as a dimension in a report.",
        "docs_url": REPORTING_API_URL,
        "columns": {
            "id": "Identifier of the custom dimension, used in report queries.",
            "display_name": "The name of the custom dimension as it appears in the Singular platform.",
        },
    },
    "cohort_metrics": {
        "description": "A cohort metric or in-app event available to the Singular account for report queries.",
        "docs_url": REPORTING_API_URL,
        "columns": {
            "name": "The identifier of the metric for use in API queries.",
            "display_name": "The name of the metric as it appears in the Singular platform.",
        },
    },
    "conversion_metrics": {
        "description": "A conversion event available to the Singular account, usable as a metric in report queries.",
        "docs_url": REPORTING_API_URL,
        "columns": {
            "name": "The auto-generated identifier of the event, used in report queries.",
            "display_name": "The name of the conversion event as configured in the Events page.",
        },
    },
}
