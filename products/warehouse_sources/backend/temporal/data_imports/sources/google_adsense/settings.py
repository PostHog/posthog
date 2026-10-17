from typing import NotRequired, TypedDict

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class ReportsSchema(TypedDict):
    dimensions: list[str]
    metrics: list[str]
    primary_key: list[str]
    should_sync_default: bool
    description: str | None

    # AdSense-specific concerns:
    reporting_time_zone: NotRequired[str]  # GOOGLE_TIME_ZONE required for WEBSEARCH_RESULT_PAGES; unused (out of scope)
    end_lag_days: NotRequired[int]  # ESTIMATED_EARNINGS final "through yesterday"; today is an estimate


METRICS_ALL: list[str] = [
    "PAGE_VIEWS",
    "AD_REQUESTS",
    "MATCHED_AD_REQUESTS",
    "IMPRESSIONS",
    "INDIVIDUAL_AD_IMPRESSIONS",
    "CLICKS",
    "ESTIMATED_EARNINGS",
    "PAGE_VIEWS_RPM",
    "IMPRESSIONS_RPM",
    "IMPRESSIONS_CTR",
    "COST_PER_CLICK",
    "ACTIVE_VIEW_VIEWABILITY",
]

# RPM, CTR, and viewability are per-row computed ratios, not additive counts — summing
# them across rows (e.g. across dates) produces a meaningless number. Surfaced here as
# actual column descriptions in the destination, not just a code comment.
METRIC_DESCRIPTIONS: dict[str, str] = {
    "page_views": "Number of page views.",
    "ad_requests": "Number of ad requests.",
    "matched_ad_requests": "Number of ad requests that returned at least one ad.",
    "impressions": "Number of ad impressions.",
    "individual_ad_impressions": "Number of individual ads shown (a single impression can contain several).",
    "clicks": "Number of ad clicks.",
    "estimated_earnings": "Estimated publisher earnings. Accurate through yesterday; today's value is an estimate.",
    "page_views_rpm": "Revenue per thousand page views. Does not sum across rows.",
    "impressions_rpm": "Revenue per thousand ad impressions. Does not sum across rows.",
    "impressions_ctr": "Ratio of impressions that resulted in a click. Does not sum across rows.",
    "cost_per_click": "Average earnings per click. A computed ratio, so it does not sum across rows either.",
    "active_view_viewability": "Ratio of ad requests that were measurably viewable. Does not sum across rows.",
}

# Row-shape rules applied when parsing rows[] (connector logic, not per-table config):
# each header's name is lowercased to snake_case for the column name; values are cast
# by the header's type.
HEADER_TYPE_CASTS: dict[str, str] = {
    "DIMENSION": "str",
    "METRIC_TALLY": "int",
    "METRIC_MILLISECONDS": "int",
    "METRIC_RATIO": "float",
    "METRIC_DECIMAL": "float",
    "METRIC_CURRENCY": "float",  # plus a sibling currency_code column from the header's currencyCode
}

# Every parsed row also gets an `account` column with the syncing account's resource
# name. Not part of any primary_key below — the screenshot's primary keys are date-only
# or date + one entity column, with no account component.

REPORTS_SCHEMAS: dict[str, ReportsSchema] = {
    "daily_stats": {
        "dimensions": ["DATE"],
        "metrics": METRICS_ALL,
        "primary_key": ["date"],
        "should_sync_default": True,
        "description": "Daily totals across all of METRICS_ALL.",
        "end_lag_days": 1,
    },
    "ad_client_stats": {
        "dimensions": ["DATE", "AD_CLIENT_ID", "PRODUCT_CODE", "PRODUCT_NAME"],
        "metrics": METRICS_ALL,
        "primary_key": ["date", "ad_client_id"],
        "should_sync_default": False,
        "description": "Daily performance broken out by ad client, with the client's product (AFC, AFS) attached.",
        "end_lag_days": 1,
    },
    "ad_unit_stats": {
        "dimensions": ["DATE", "AD_UNIT_ID", "AD_UNIT_NAME", "AD_UNIT_SIZE_CODE"],
        "metrics": METRICS_ALL,
        "primary_key": ["date", "ad_unit_id"],
        "should_sync_default": True,
        "description": "Daily performance broken out by ad unit, with the unit's name and size attached.",
        "end_lag_days": 1,
    },
    "country_stats": {
        "dimensions": ["DATE", "COUNTRY_CODE", "COUNTRY_NAME"],
        "metrics": METRICS_ALL,
        "primary_key": ["date", "country_code"],
        "should_sync_default": True,
        "description": "Daily performance broken out by country.",
        "end_lag_days": 1,
    },
    "platform_stats": {
        "dimensions": ["DATE", "PLATFORM_TYPE_CODE", "PLATFORM_TYPE_NAME"],
        "metrics": METRICS_ALL,
        "primary_key": ["date", "platform_type_code"],
        "should_sync_default": False,
        "description": "Daily performance broken out by platform type (e.g. Desktop, HighEndMobile).",
        "end_lag_days": 1,
    },
    "domain_stats": {
        "dimensions": ["DATE", "DOMAIN_CODE", "DOMAIN_NAME"],
        "metrics": METRICS_ALL,
        "primary_key": ["date", "domain_code"],
        "should_sync_default": True,
        "description": "Daily performance broken out by domain the ad was served on.",
        "end_lag_days": 1,
    },
    "page_url_stats": {
        "dimensions": ["DATE", "PAGE_URL"],
        "metrics": METRICS_ALL,
        "primary_key": ["date", "page_url"],
        "should_sync_default": False,
        "description": "Daily performance broken out by page URL. Off by default due to high cardinality.",
        "end_lag_days": 1,
    },
    "custom_channel_stats": {
        "dimensions": ["DATE", "CUSTOM_CHANNEL_ID", "CUSTOM_CHANNEL_NAME"],
        "metrics": METRICS_ALL,
        "primary_key": ["date", "custom_channel_id"],
        "should_sync_default": False,
        "description": "Daily performance broken out by custom channel.",
        "end_lag_days": 1,
    },
    "url_channel_stats": {
        "dimensions": ["DATE", "URL_CHANNEL_ID", "URL_CHANNEL_NAME"],
        "metrics": METRICS_ALL,
        "primary_key": ["date", "url_channel_id"],
        "should_sync_default": False,
        "description": "Daily performance broken out by URL channel.",
        "end_lag_days": 1,
    },
    "ad_format_stats": {
        "dimensions": ["DATE", "AD_FORMAT_CODE", "AD_FORMAT_NAME"],
        "metrics": METRICS_ALL,
        "primary_key": ["date", "ad_format_code"],
        "should_sync_default": False,
        "description": "Daily performance broken out by ad format (e.g. In-page, Anchor, Vignette).",
        "end_lag_days": 1,
    },
}


class EntitySchema(TypedDict):
    primary_key: list[str]  # always ["name"] — the resource name, per the API's own convention
    should_sync_default: bool
    description: str | None
    requires_ad_client_iteration: NotRequired[bool]  # fan-out: list once per ad client, not once globally


# Entity tables, sourced from the accounts.* resource endpoints (not Reports.generate).
# Full refresh — snapshots of current account/inventory state, not time-series data, so
# there's no timestamp field to sync incrementally on. Every table's primary key is
# `name`, the API's own resource name field (e.g. accounts/pub-.../adclients/...).
ENTITY_SCHEMAS: dict[str, EntitySchema] = {
    "account": {
        "primary_key": ["name"],
        "should_sync_default": True,
        "description": "The connected AdSense account. accounts.get returns exactly one row.",
    },
    "ad_client": {
        "primary_key": ["name"],
        "should_sync_default": True,
        "description": "Every ad client on the account (e.g. AdSense for Content, AdSense for Search).",
    },
    # Fan-out: adunits.list is called once per ad_client row, not once for the account.
    "ad_unit": {
        "primary_key": ["name"],
        "should_sync_default": True,
        "description": ("Ad units configured under each ad client. The resource name includes the parent ad client."),
        "requires_ad_client_iteration": True,
    },
    "custom_channel": {
        "primary_key": ["name"],
        "should_sync_default": False,
        "description": "Custom channels configured under each ad client.",
        "requires_ad_client_iteration": True,
    },
    "url_channel": {
        "primary_key": ["name"],
        "should_sync_default": False,
        "description": "URL channels configured under each ad client.",
        "requires_ad_client_iteration": True,
    },
    "site": {
        "primary_key": ["name"],
        "should_sync_default": True,
        "description": "Sites registered to the account.",
    },
    "alert": {
        "primary_key": ["name"],
        "should_sync_default": False,
        "description": "Active alerts on the account.",
    },
    "policy_issue": {
        "primary_key": ["name"],
        "should_sync_default": False,
        "description": "Policy issues affecting the account's inventory.",
    },
    "payment": {
        "primary_key": ["name"],
        "should_sync_default": True,
        "description": (
            "Payments made or pending on the account. `amount` is stored as the raw API "
            "string, not cast to a number — the currency and formatting live in that "
            "string itself. The `unpaid` row's balance changes daily, but full-refresh "
            "already re-fetches it each sync, so no special handling beyond that is needed."
        ),
    },
}

REPORTS_INCREMENTAL_FIELD: IncrementalField = {
    "label": "date",
    "field": "date",
    "type": IncrementalFieldType.Date,
    "field_type": IncrementalFieldType.Date,
}
