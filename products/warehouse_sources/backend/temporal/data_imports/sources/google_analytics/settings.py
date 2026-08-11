import re
import json
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
    "landing_pages": {
        "dimensions": ["date", "landingPagePlusQueryString"],
        "metrics": [
            "sessions",
            "totalUsers",
            "newUsers",
            "screenPageViews",
            "averageSessionDuration",
            "bounceRate",
        ],
        "primary_key": ["date", "landingPagePlusQueryString"],
        "should_sync_default": False,
        "description": "Daily performance of the first page in each session (landing page, including query string).",
    },
    "campaigns": {
        "dimensions": ["date", "sessionCampaignName", "sessionDefaultChannelGroup", "sessionSource", "sessionMedium"],
        "metrics": ["totalUsers", "newUsers", "sessions", "engagedSessions"],
        "primary_key": ["date", "sessionCampaignName", "sessionDefaultChannelGroup", "sessionSource", "sessionMedium"],
        "should_sync_default": False,
        "description": "Daily traffic broken out by session campaign, default channel group, source, and medium.",
    },
    "key_events": {
        "dimensions": ["date", "sessionSource", "sessionMedium"],
        "metrics": ["keyEvents", "purchaseRevenue", "sessions", "totalUsers"],
        "primary_key": ["date", "sessionSource", "sessionMedium"],
        "should_sync_default": False,
        "description": "Daily key events and purchase revenue broken out by session source and medium.",
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


# GA4's runReport rejects requests over 9 dimensions or 10 metrics. `date` counts
# toward the dimension limit because it is always requested, so a user-defined
# report may name at most 8 dimensions of its own.
GA4_MAX_DIMENSIONS = 9
GA4_MAX_METRICS = 10

# GA4 dimension/metric API names are alphanumeric identifiers; custom dimensions and
# metrics carry a `customEvent:`/`customUser:` scope prefix. Reject anything else so a
# malformed name fails fast at config time instead of as an opaque runReport error.
_GA4_FIELD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(:[A-Za-z0-9_]+)?$")


class CustomReportError(ValueError):
    """A user-defined custom report is malformed or exceeds GA4's request limits."""


def _validated_field_names(raw: object, *, report_name: str, kind: str) -> list[str]:
    if not isinstance(raw, list):
        raise CustomReportError(f"Report '{report_name}': '{kind}' must be a list of GA4 {kind} names.")
    names: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            raise CustomReportError(f"Report '{report_name}': every {kind[:-1]} name must be a non-empty string.")
        name = value.strip()
        if not _GA4_FIELD_NAME_RE.match(name):
            raise CustomReportError(f"Report '{report_name}': '{name}' is not a valid GA4 {kind[:-1]} name.")
        if name not in names:
            names.append(name)
    return names


def parse_custom_reports(custom_reports_json: str | None) -> dict[str, GoogleAnalyticsReportSchema]:
    """Turn the user's custom-report JSON into report schemas keyed by table name.

    Mirrors the conventions of the built-in schemas so custom reports flow through the
    same incremental/resumable sync unchanged: `date` always leads the dimensions and
    the primary key is date plus every dimension for merge-mode dedupe. Raises
    `CustomReportError` with an actionable message on any malformed or oversized report.
    """
    if not custom_reports_json or not custom_reports_json.strip():
        return {}

    try:
        parsed = json.loads(custom_reports_json)
    except json.JSONDecodeError as e:
        raise CustomReportError(f"Custom reports must be valid JSON: {e}.") from e

    if not isinstance(parsed, list):
        raise CustomReportError("Custom reports must be a JSON array of report objects.")

    reports: dict[str, GoogleAnalyticsReportSchema] = {}
    for entry in parsed:
        if not isinstance(entry, dict):
            raise CustomReportError(
                "Each custom report must be a JSON object with 'name', 'dimensions', and 'metrics'."
            )

        raw_name = entry.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise CustomReportError("Each custom report needs a non-empty 'name'.")
        name = raw_name.strip()

        if name in GOOGLE_ANALYTICS_REPORT_SCHEMAS:
            raise CustomReportError(
                f"'{name}' is a built-in report name. Choose a different name for your custom report."
            )
        if name in reports:
            raise CustomReportError(f"Duplicate custom report name '{name}'. Each report needs a unique name.")

        metrics = _validated_field_names(entry.get("metrics"), report_name=name, kind="metrics")
        if not metrics:
            raise CustomReportError(f"Report '{name}': add at least one metric.")

        # `date` is always day-grained and leads the dimensions; drop a user-supplied
        # duplicate so it is not requested twice.
        user_dimensions = _validated_field_names(entry.get("dimensions", []), report_name=name, kind="dimensions")
        dimensions = ["date", *(d for d in user_dimensions if d != "date")]

        if len(dimensions) > GA4_MAX_DIMENSIONS:
            raise CustomReportError(
                f"Report '{name}': GA4 allows at most {GA4_MAX_DIMENSIONS} dimensions per report "
                f"(date is always included), but this report has {len(dimensions)}."
            )
        if len(metrics) > GA4_MAX_METRICS:
            raise CustomReportError(
                f"Report '{name}': GA4 allows at most {GA4_MAX_METRICS} metrics per report, "
                f"but this report has {len(metrics)}."
            )

        reports[name] = {
            "dimensions": dimensions,
            "metrics": metrics,
            "primary_key": list(dimensions),
            "should_sync_default": True,
            "description": entry.get("description")
            if isinstance(entry.get("description"), str)
            else "User-defined GA4 report.",
        }

    return reports


def build_report_schemas(custom_reports_json: str | None) -> dict[str, GoogleAnalyticsReportSchema]:
    """Built-in report schemas merged with any user-defined custom reports."""
    return {**GOOGLE_ANALYTICS_REPORT_SCHEMAS, **parse_custom_reports(custom_reports_json)}
