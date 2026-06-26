from typing import TypedDict

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class GoogleAnalyticsReportSchema(TypedDict):
    dimensions: list[str]
    metrics: list[str]
    primary_key: list[str]
    should_sync_default: bool
    description: str | None


# Each schema maps to a single GA4 Data API `runReport` request with a fixed
# dimension + metric set, mirroring the standard reports in the GA4 UI (and the
# default streams of other GA4 connectors). Every schema includes the `date`
# dimension so rows are day-grained, the primary key (date + dimensions) is
# stable for merge-mode dedupe, and incremental syncs can resume from the last
# synced date.
#
# Note on aggregation: GA4 reports are aggregates, not raw events. A metric
# value for (date, dimension-set) can be re-stated by Google for up to ~48
# hours after the day ends (processing latency), which is why the iterator
# re-fetches a small lookback window on incremental syncs.
GOOGLE_ANALYTICS_REPORT_SCHEMAS: dict[str, GoogleAnalyticsReportSchema] = {
    "website_overview": {
        "dimensions": ["date"],
        "metrics": [
            "totalUsers",
            "newUsers",
            "sessions",
            "sessionsPerUser",
            "screenPageViews",
            "averageSessionDuration",
            "bounceRate",
        ],
        "primary_key": ["date"],
        "should_sync_default": True,
        "description": "Daily totals for users, sessions, page views, session duration, and bounce rate.",
    },
    "daily_active_users": {
        "dimensions": ["date"],
        "metrics": ["active1DayUsers"],
        "primary_key": ["date"],
        "should_sync_default": True,
        "description": "1-day active users per day (DAU).",
    },
    "weekly_active_users": {
        "dimensions": ["date"],
        "metrics": ["active7DayUsers"],
        "primary_key": ["date"],
        "should_sync_default": True,
        "description": "Rolling 7-day active users per day (WAU).",
    },
    "four_weekly_active_users": {
        "dimensions": ["date"],
        "metrics": ["active28DayUsers"],
        "primary_key": ["date"],
        "should_sync_default": True,
        "description": "Rolling 28-day active users per day.",
    },
    "devices": {
        "dimensions": ["date", "deviceCategory", "operatingSystem", "browser"],
        "metrics": [
            "totalUsers",
            "newUsers",
            "sessions",
            "screenPageViews",
            "averageSessionDuration",
            "bounceRate",
        ],
        "primary_key": ["date", "deviceCategory", "operatingSystem", "browser"],
        "should_sync_default": True,
        "description": "Daily usage broken out by device category, operating system, and browser.",
    },
    "locations": {
        "dimensions": ["date", "country", "region", "city"],
        "metrics": [
            "totalUsers",
            "newUsers",
            "sessions",
            "screenPageViews",
            "averageSessionDuration",
            "bounceRate",
        ],
        "primary_key": ["date", "country", "region", "city"],
        "should_sync_default": True,
        "description": "Daily usage broken out by country, region, and city.",
    },
    "pages": {
        "dimensions": ["date", "hostName", "pagePathPlusQueryString"],
        "metrics": [
            "screenPageViews",
            "sessions",
            "totalUsers",
            "averageSessionDuration",
            "bounceRate",
        ],
        "primary_key": ["date", "hostName", "pagePathPlusQueryString"],
        "should_sync_default": True,
        "description": "Daily page performance broken out by host name and page path (including query string).",
    },
    "traffic_sources": {
        "dimensions": ["date", "sessionSource", "sessionMedium"],
        "metrics": [
            "totalUsers",
            "newUsers",
            "sessions",
            "screenPageViews",
            "averageSessionDuration",
            "bounceRate",
        ],
        "primary_key": ["date", "sessionSource", "sessionMedium"],
        "should_sync_default": True,
        "description": "Daily traffic broken out by session source and medium.",
    },
    "user_acquisition": {
        "dimensions": ["date", "firstUserSource", "firstUserMedium"],
        "metrics": ["totalUsers", "newUsers", "sessions", "engagedSessions"],
        "primary_key": ["date", "firstUserSource", "firstUserMedium"],
        "should_sync_default": True,
        "description": "Daily acquisition broken out by the source and medium that first acquired each user.",
    },
    "events": {
        "dimensions": ["date", "eventName"],
        "metrics": ["eventCount", "totalUsers", "eventCountPerUser"],
        "primary_key": ["date", "eventName"],
        "should_sync_default": False,
        "description": "Daily event counts broken out by event name.",
    },
}


GOOGLE_ANALYTICS_INCREMENTAL_FIELD: IncrementalField = {
    "label": "date",
    "field": "date",
    "type": IncrementalFieldType.Date,
    "field_type": IncrementalFieldType.Date,
}
