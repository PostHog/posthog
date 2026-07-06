"""Canonical, documentation-sourced descriptions for Google Analytics (GA4) report endpoints.

Sourced from the official GA4 Data API reference and the dimensions & metrics catalog
(https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema). Keyed by the report
names in `settings.py` `GOOGLE_ANALYTICS_REPORT_SCHEMAS`, which match the `ExternalDataSchema.name` of
a synced GA4 report table. Each report is a daily aggregate (a GA4 `runReport` request) with a fixed
dimension + metric set; columns are the GA4 dimension/metric API names. Columns absent here fall back
to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# GA4 dimensions reused across reports.
_DATE = {"date": "The date the report row aggregates, in YYYYMMDD form."}

# GA4 metrics reused across reports.
_CORE_METRICS = {
    "totalUsers": "Total number of unique users.",
    "newUsers": "Number of users who interacted for the first time.",
    "sessions": "Number of sessions.",
    "screenPageViews": "Number of app screens or web pages viewed.",
    "averageSessionDuration": "Average duration of a session, in seconds.",
    "bounceRate": "Share of sessions that were not engaged.",
}


def _date_columns(**overrides: str) -> dict[str, str]:
    return {**_DATE, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "website_overview": {
        "description": "Daily totals for users, sessions, page views, session duration, and bounce rate.",
        "docs_url": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "columns": _date_columns(
            **_CORE_METRICS,
            sessionsPerUser="Average number of sessions per user.",
        ),
    },
    "daily_active_users": {
        "description": "Number of 1-day active users per day (DAU).",
        "docs_url": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "columns": _date_columns(
            active1DayUsers="Number of users who engaged in the prior 1 day (daily active users).",
        ),
    },
    "weekly_active_users": {
        "description": "Rolling 7-day active users per day (WAU).",
        "docs_url": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "columns": _date_columns(
            active7DayUsers="Number of users who engaged in the prior 7 days (weekly active users).",
        ),
    },
    "four_weekly_active_users": {
        "description": "Rolling 28-day active users per day.",
        "docs_url": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "columns": _date_columns(
            active28DayUsers="Number of users who engaged in the prior 28 days.",
        ),
    },
    "devices": {
        "description": "Daily usage broken out by device category, operating system, and browser.",
        "docs_url": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "columns": _date_columns(
            **_CORE_METRICS,
            deviceCategory="Type of device (desktop, mobile, or tablet).",
            operatingSystem="Operating system of the device.",
            browser="Browser used to view the site.",
        ),
    },
    "locations": {
        "description": "Daily usage broken out by country, region, and city.",
        "docs_url": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "columns": _date_columns(
            **_CORE_METRICS,
            country="Country the user's activity originated from.",
            region="Region (state/province) the user's activity originated from.",
            city="City the user's activity originated from.",
        ),
    },
    "pages": {
        "description": "Daily page performance broken out by host name and page path (including query string).",
        "docs_url": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "columns": _date_columns(
            screenPageViews="Number of times the page was viewed.",
            sessions="Number of sessions that included the page.",
            totalUsers="Number of unique users who viewed the page.",
            averageSessionDuration="Average session duration, in seconds.",
            bounceRate="Share of sessions that were not engaged.",
            hostName="Host name (domain) of the page.",
            pagePathPlusQueryString="Page path including the query string.",
        ),
    },
    "traffic_sources": {
        "description": "Daily traffic broken out by session source and medium.",
        "docs_url": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "columns": _date_columns(
            **_CORE_METRICS,
            sessionSource="The source that brought the user to the site for the session (e.g. google).",
            sessionMedium="The medium that brought the user for the session (e.g. organic, cpc, referral).",
        ),
    },
    "user_acquisition": {
        "description": "Daily acquisition broken out by the source and medium that first acquired each user.",
        "docs_url": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "columns": _date_columns(
            totalUsers="Number of unique users.",
            newUsers="Number of first-time users.",
            sessions="Number of sessions.",
            engagedSessions="Number of sessions that were engaged (lasted 10s+, had a conversion, or 2+ page views).",
            firstUserSource="Source that first acquired the user.",
            firstUserMedium="Medium that first acquired the user.",
        ),
    },
    "events": {
        "description": "Daily event counts broken out by event name.",
        "docs_url": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "columns": _date_columns(
            eventName="Name of the event.",
            eventCount="Number of times the event was triggered.",
            totalUsers="Number of unique users who triggered the event.",
            eventCountPerUser="Average number of times each user triggered the event.",
        ),
    },
}
