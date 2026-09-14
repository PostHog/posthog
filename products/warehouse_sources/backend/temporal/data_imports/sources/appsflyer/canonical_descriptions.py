"""Canonical, documentation-sourced descriptions for AppsFlyer Pull API reports and columns.

Sourced from the official AppsFlyer references for the aggregate Pull API, the raw-data Pull API
and the Master API; each entry below links the page it came from.
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


# Event-level columns shared by the raw-data reports (CSV headers normalized to snake_case). Raw
# reports are built from one wide schema, so a column that doesn't apply to a report comes back
# empty rather than absent.
_RAW_COLUMNS = {
    "appsflyer_id": "Unique AppsFlyer device identifier the event belongs to.",
    "customer_user_id": "Your own user identifier, if it was set in the SDK.",
    "event_time": "Time the event happened, in the report's timezone.",
    "install_time": "Time the user first opened the app.",
    "attributed_touch_type": "Touch that won attribution (click or impression).",
    "attributed_touch_time": "Time of the attributed click or impression.",
    "event_name": "Name of the recorded event.",
    "event_value": "Event parameters as sent by the SDK.",
    "event_revenue": "Revenue reported with the event, in the event's currency.",
    "event_revenue_currency": "Currency the event revenue was reported in.",
    "event_revenue_usd": "Event revenue converted to US dollars.",
    "media_source": "Media source the install is attributed to.",
    "channel": "Channel within the media source.",
    "campaign": "Campaign name the install is attributed to.",
    "campaign_id": "Campaign identifier from the media source.",
    "adset": "Ad set name the install is attributed to.",
    "ad": "Ad name the install is attributed to.",
    "site_id": "Publisher or site identifier reported by the media source.",
    "partner": "Agency or PMD partner credited for the activity.",
    "cost_model": "Cost model the campaign is billed on.",
    "cost_value": "Cost attributed to the install, in the cost currency.",
    "cost_currency": "Currency the cost is reported in.",
    "country_code": "Two-letter country code the event came from.",
    "city": "City the event came from.",
    "ip": "IP address the event came from.",
    "platform": "Device platform (ios, android, and so on).",
    "device_type": "Device make and model group.",
    "os_version": "Operating system version of the device.",
    "app_version": "Version of your app that sent the event.",
    "app_id": "App the event belongs to.",
    "is_retargeting": "Whether the record came from a retargeting campaign.",
    "is_primary_attribution": "Whether this is the primary attribution record for the install.",
    "advertising_id": "Google Advertising ID of the device.",
    "idfa": "Apple advertising identifier of the device.",
    "idfv": "Apple vendor identifier of the device.",
}

_AD_REVENUE_COLUMNS = {
    **_RAW_COLUMNS,
    "monetization_network": "Ad network that paid for the impressions.",
    "ad_unit": "Ad unit the impressions were served in.",
    "placement": "Placement the ad was shown in.",
    "impressions": "Number of impressions the revenue row aggregates.",
}


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
    "installs": {
        "description": "One row per attributed (non-organic) install, with the media source, campaign and touch that won attribution.",
        "docs_url": "https://dev.appsflyer.com/hc/reference/get_app-id-installs-report-v5",
        "columns": _RAW_COLUMNS,
    },
    "in_app_events": {
        "description": "One row per in-app event from an attributed user, carrying the event name, value and revenue alongside the install's attribution.",
        "docs_url": "https://dev.appsflyer.com/hc/reference/get_app-id-in-app-events-report-v5",
        "columns": _RAW_COLUMNS,
    },
    "ad_revenue": {
        "description": "Ad monetization revenue per user for attributed installs, aggregated by monetization network, ad unit and placement.",
        "docs_url": "https://dev.appsflyer.com/hc/reference/get_app-id-ad-revenue-raw-v5",
        "columns": _AD_REVENUE_COLUMNS,
    },
    "ad_revenue_organic": {
        "description": "Ad monetization revenue per user for organic installs, aggregated by monetization network, ad unit and placement.",
        "docs_url": "https://dev.appsflyer.com/hc/reference/get_app-id-ad-revenue-organic-raw-v5",
        "columns": _AD_REVENUE_COLUMNS,
    },
    "ad_revenue_retargeting": {
        "description": "Ad monetization revenue per user attributed to retargeting campaigns, aggregated by monetization network, ad unit and placement.",
        "docs_url": "https://dev.appsflyer.com/hc/reference/get_app-id-ad-revenue-raw-retarget-v5",
        "columns": _AD_REVENUE_COLUMNS,
    },
    "master_report": {
        "description": "Master API LTV report: install-day cohorts broken down by agency, media source, campaign and country, with the generic lifetime-value KPIs.",
        "docs_url": "https://dev.appsflyer.com/hc/reference/master_api_get",
        "columns": {
            **{name: description for name, description in _COMMON_COLUMNS.items() if name != "date"},
            "install_time": "Install date of the cohort the metrics are reported for.",
            "country": "Country the cohort installed from.",
            "sessions": "Number of sessions the cohort has opened since install.",
            "cr": "Conversion rate from click to install.",
            "arpu": "Average revenue per user across the cohort's lifetime.",
            "uninstalls": "Number of users in the cohort who uninstalled the app.",
            "uninstall_rate": "Share of the cohort that uninstalled the app.",
        },
    },
}
