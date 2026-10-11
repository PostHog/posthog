"""Canonical, documentation-sourced descriptions for Matomo endpoints and columns.

Sourced from the official Matomo Reporting API reference (https://developer.matomo.org/api-reference/reporting-api).
Keyed by the endpoint names in `settings.py` `MATOMO_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Matomo table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "visits": {
        "description": "The raw visit log from Matomo's Live API — one row per visit with its actions and visitor details.",
        "docs_url": "https://developer.matomo.org/api-reference/reporting-api#Live",
        "columns": {
            "idVisit": "Unique identifier for the visit.",
            "idSite": "The identifier of the site the visit was recorded on.",
            "visitorId": "The anonymized identifier for the visitor.",
            "serverTimestamp": "Server-side Unix timestamp of the visit, used as the incremental cursor.",
            "firstActionTimestamp": "Unix timestamp of the visit's first action.",
            "lastActionTimestamp": "Unix timestamp of the visit's last action.",
            "visitDuration": "The duration of the visit in seconds.",
            "actions": "The number of actions (page views, events, etc.) in the visit.",
            "referrerType": "The type of referrer that drove the visit (direct, search, website, campaign).",
            "referrerName": "The name of the referrer.",
            "country": "The country the visit originated from.",
            "city": "The city the visit originated from.",
            "deviceType": "The type of device used for the visit.",
            "browserName": "The browser used for the visit.",
            "operatingSystemName": "The operating system used for the visit.",
            "actionDetails": "The detailed list of actions performed during the visit.",
        },
    },
    "visits_summary": {
        "description": "Per-day aggregate visit metrics from Matomo's VisitsSummary API.",
        "docs_url": "https://developer.matomo.org/api-reference/reporting-api#VisitsSummary",
        "columns": {
            "_date": "The report day this aggregate row is for.",
            "nb_visits": "The number of visits in the period.",
            "nb_uniq_visitors": "The number of unique visitors in the period.",
            "nb_users": "The number of unique logged-in users in the period.",
            "nb_actions": "The total number of actions in the period.",
            "nb_actions_per_visit": "The average number of actions per visit.",
            "avg_time_on_site": "The average visit duration in seconds.",
            "bounce_rate": "The percentage of visits with a single action (bounces).",
            "max_actions": "The maximum number of actions in a single visit.",
            "sum_visit_length": "The total duration of all visits in seconds.",
        },
    },
    "actions_summary": {
        "description": "Per-day aggregate action metrics from Matomo's Actions API.",
        "docs_url": "https://developer.matomo.org/api-reference/reporting-api#Actions",
        "columns": {
            "_date": "The report day this aggregate row is for.",
            "nb_pageviews": "The total number of page views in the period.",
            "nb_uniq_pageviews": "The number of unique page views in the period.",
            "nb_downloads": "The total number of downloads in the period.",
            "nb_uniq_downloads": "The number of unique downloads in the period.",
            "nb_outlinks": "The total number of outbound link clicks in the period.",
            "nb_uniq_outlinks": "The number of unique outbound link clicks in the period.",
            "nb_searches": "The total number of site searches in the period.",
            "avg_time_on_page": "The average time spent on a page in seconds.",
            "bounce_rate": "The percentage of single-action visits (bounces).",
        },
    },
    "referrers": {
        "description": "Per-day referrer breakdown from Matomo's Referrers API — one row per referrer.",
        "docs_url": "https://developer.matomo.org/api-reference/reporting-api#Referrers",
        "columns": {
            "_date": "The report day this row is for.",
            "label": "The referrer label (e.g. the search engine, website, or campaign name).",
            "referrer_type": "The type of referrer (direct, search, website, campaign, social).",
            "nb_visits": "The number of visits from this referrer.",
            "nb_uniq_visitors": "The number of unique visitors from this referrer.",
            "nb_actions": "The number of actions from this referrer.",
            "nb_conversions": "The number of conversions attributed to this referrer.",
        },
    },
    "countries": {
        "description": "Per-day country breakdown from Matomo's UserCountry API — one row per country.",
        "docs_url": "https://developer.matomo.org/api-reference/reporting-api#UserCountry",
        "columns": {
            "_date": "The report day this row is for.",
            "label": "The country name.",
            "code": "The two-letter country code.",
            "nb_visits": "The number of visits from this country.",
            "nb_uniq_visitors": "The number of unique visitors from this country.",
            "nb_actions": "The number of actions from this country.",
        },
    },
}
