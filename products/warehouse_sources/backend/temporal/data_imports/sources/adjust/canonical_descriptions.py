"""Canonical, documentation-sourced descriptions for the Adjust Report Service API reports.

Sourced from the official Adjust Report Service API reference
(https://dev.adjust.com/en/api/rs-api/), including its dimensions and metrics glossaries.
Keyed by the report names in `settings.py` `ADJUST_REPORTS`, which match the
`ExternalDataSchema.name` of a synced Adjust table. Column names are the dimension and metric
names Adjust returns verbatim; columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://dev.adjust.com/en/api/rs-api/"

# Dimensions and metrics requested on every report.
_BASE_COLUMNS = {
    "day": "Calendar day (UTC) the aggregated metrics are reported for.",
    "app": "Name of the app in the Adjust dashboard.",
    "app_token": "Adjust app token identifying the app the metrics belong to.",
    "impressions": "Ad impressions recorded by the network in the period.",
    "clicks": "Ad clicks recorded by the network in the period.",
    "installs": "App installs attributed in the period.",
    "sessions": "App sessions recorded in the period.",
    "reattributions": "Reattributed users (previously installed users re-engaged by a campaign) in the period.",
    "click_conversion_rate": "Installs divided by clicks.",
    "impression_conversion_rate": "Installs divided by impressions.",
    "cost": "Ad spend in the period, from the connected ad-spend integrations.",
    "ecpi": "Effective cost per install (cost divided by installs).",
    "revenue": "Revenue attributed in the period, from tracked revenue events.",
}

_USER_COLUMNS = {
    "daus": "Daily active users.",
    "waus": "Weekly active users.",
    "maus": "Monthly active users.",
}

_PARTNER_COLUMN = {"partner_name": "Name of the attribution partner (ad network) the activity is attributed to."}


def _columns(*extra: dict[str, str]) -> dict[str, str]:
    merged = dict(_BASE_COLUMNS)
    for block in extra:
        merged.update(block)
    return merged


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "daily_report": {
        "description": "Daily aggregated performance per app — installs, sessions, clicks, impressions, cost, revenue, and active users.",
        "docs_url": _DOCS_URL,
        "columns": _columns(_USER_COLUMNS),
    },
    "partner_report": {
        "description": "Daily aggregated performance per app broken down by attribution partner (ad network).",
        "docs_url": _DOCS_URL,
        "columns": _columns(_PARTNER_COLUMN),
    },
    "campaign_report": {
        "description": "Daily aggregated performance per campaign, broken down by attribution partner.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            _PARTNER_COLUMN,
            {
                "campaign": "Campaign name as recorded by Adjust.",
                "campaign_id_network": "Campaign identifier as reported by the ad network.",
            },
        ),
    },
    "creative_report": {
        "description": "Daily aggregated performance per creative, broken down by ad group, campaign, and attribution partner.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            _PARTNER_COLUMN,
            {
                "campaign": "Campaign name as recorded by Adjust.",
                "adgroup": "Ad group name within the campaign.",
                "creative": "Creative name within the ad group.",
            },
        ),
    },
    "country_report": {
        "description": "Daily aggregated performance per app broken down by country.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            {
                "country": "Country name the metrics are reported for.",
                "country_code": "ISO country code the metrics are reported for.",
            }
        ),
    },
    "os_report": {
        "description": "Daily aggregated performance per app broken down by operating system.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            _USER_COLUMNS,
            {"os_name": "Operating system of the device (for example ios or android)."},
        ),
    },
}
