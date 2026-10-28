"""Canonical, documentation-sourced descriptions for the Adjust Report Service API reports.

Sourced from the official Adjust Report Service API reference
(https://dev.adjust.com/en/api/rs-api/), including its dimensions and metrics glossaries.
Keyed by the report names in `settings.py` `ADJUST_REPORTS` (plus the events catalog), which match the
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
    "retention_report": {
        "description": "Day 1, 7, and 30 retention per daily install cohort, broken down by attribution partner.",
        "docs_url": _DOCS_URL,
        "columns": {
            "day": "Calendar day (UTC) of the install cohort.",
            "app": _BASE_COLUMNS["app"],
            "app_token": _BASE_COLUMNS["app_token"],
            **_PARTNER_COLUMN,
            "installs": _BASE_COLUMNS["installs"],
            **{
                f"cohort_size_{cohort}": f"Users who installed or were reattributed on the day and kept the app installed for the {cohort} cohort period."
                for cohort in ("d1", "d7", "d30")
            },
            **{
                f"retained_users_{cohort}": f"Users from the cohort who were still active in the {cohort} cohort period."
                for cohort in ("d1", "d7", "d30")
            },
            **{
                f"retention_rate_{cohort}": f"Retained users divided by cohort size for the {cohort} cohort period."
                for cohort in ("d1", "d7", "d30")
            },
        },
    },
    "skad_report": {
        "description": "Daily SKAdNetwork (iOS) installs, reinstalls, and conversion value counts per network campaign.",
        "docs_url": _DOCS_URL,
        "columns": {
            "day": _BASE_COLUMNS["day"],
            "app": _BASE_COLUMNS["app"],
            "app_token": _BASE_COLUMNS["app_token"],
            **_PARTNER_COLUMN,
            "campaign_network": "Campaign name as reported by the ad network.",
            "campaign_id_network": "Campaign identifier as reported by the ad network.",
            "skad_installs": "SKAdNetwork postbacks representing a new install.",
            "skad_reinstalls": "SKAdNetwork postbacks representing a reinstall.",
            "skad_total_installs": "Total SKAdNetwork conversions (installs plus reinstalls).",
            "valid_conversions": "SKAdNetwork postbacks with a non-null conversion value attached.",
            "skad_conversion_value_null": "SKAdNetwork postbacks received with a null conversion value.",
        },
    },
    "event_report": {
        "description": "Daily in-app event counts per app and attribution partner, with one row per event.",
        "docs_url": _DOCS_URL,
        "columns": {
            "day": _BASE_COLUMNS["day"],
            "app": _BASE_COLUMNS["app"],
            "app_token": _BASE_COLUMNS["app_token"],
            **_PARTNER_COLUMN,
            "event_slug": "Adjust event slug, matching the id column of the events table.",
            "event_name": "Readable name of the event.",
            "events": "Number of times the event was triggered on the day.",
        },
    },
    "events": {
        "description": "Catalog of in-app events configured in Adjust, with the slugs used to request event metrics in reports.",
        "docs_url": "https://dev.adjust.com/en/api/rs-api/events/",
        "columns": {
            "id": "Event slug, used to build report metric names such as `{slug}_events`.",
            "name": "Readable name of the event.",
            "short_name": "Shortened name of the event.",
            "section": "Report section the event belongs to.",
            "formatting": "Format the event's data is stored in (for example money).",
            "app_token": "App tokens the event is associated with.",
            "tokens": "Event token or tokens.",
            "is_skad_event": "Whether the event is a SKAdNetwork event.",
            "app_token_x_event_tokens_mapping": "Mapping of app tokens to the event's tokens in each app.",
        },
    },
}
