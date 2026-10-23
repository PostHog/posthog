"""Canonical, documentation-sourced descriptions for AppLovin endpoints and columns.

Sourced from the AppLovin support centre API references linked per entry below. Keyed by the
endpoint names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced AppLovin table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import COHORT_DAY_OFFSETS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_MAX_REPORT_DOCS_URL = "https://support.applovin.com/en/max/reporting-apis/revenue-reporting-api"
_REPORT_DOCS_URL = "https://support.applovin.com/en/growth/promoting-your-apps/api/reporting-api"
_COHORT_DOCS_URL = "https://support.applovin.com/en/max/reporting-apis/cohort-api"
_USER_AD_REVENUE_DOCS_URL = "https://support.applovin.com/en/max/reporting-apis/user-level-ad-revenue-api"
_CAMPAIGN_MANAGEMENT_DOCS_URL = (
    "https://support.applovin.com/en/growth/promoting-your-apps/api/axon-campaign-management-api"
)


def _horizon_columns(prefix: str, template: str) -> dict[str, str]:
    """Expand a per-horizon cohort metric into one description per requested day offset."""
    return {f"{prefix}_{offset}": template.format(days=offset) for offset in COHORT_DAY_OFFSETS}


_APP_DIMENSIONS = {
    "day": "Day of the data, in YYYY-MM-DD format (UTC).",
    "application": "Name of the application.",
    "package_name": "Package name (Android) or bundle ID (iOS) of the application.",
    "store_id": "Numeric part of the iTunes ID on iOS, or the package name on Android. Falls back to the bundle ID when AppLovin doesn't know the iTunes ID.",
    "platform": "Platform of the application: android, fireos or ios.",
    "country": "Two-letter ISO country code of the user.",
    "device_type": "The user's device type: phone, tablet or other.",
}

_COHORT_DIMENSION_DESCRIPTIONS = {
    "day": _APP_DIMENSIONS["day"],
    "application": _APP_DIMENSIONS["application"],
    "package_name": _APP_DIMENSIONS["package_name"],
    "platform": _APP_DIMENSIONS["platform"],
    "country": _APP_DIMENSIONS["country"],
    "installs": "Number of new installers on this day.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "max_ad_revenue": {
        "description": "Estimated MAX mediation revenue and delivery, broken down by day, app, ad unit and the ad network that filled the impression.",
        "docs_url": _MAX_REPORT_DOCS_URL,
        "columns": {
            **_APP_DIMENSIONS,
            "ad_format": "Ad unit ad type: INTER, BANNER or REWARD.",
            "max_ad_unit": "MAX Ad Unit name.",
            "max_ad_unit_id": "MAX Ad Unit ID.",
            "network": "Ad network name that served the impression.",
            "impressions": "Number of impressions shown.",
            "attempts": "Number of attempts made to the ad network.",
            "responses": "Number of responses received from the ad network.",
            "fill_rate": "Responses divided by attempts.",
            "ecpm": "Estimated eCPM generated, in USD.",
            "estimated_revenue": "Estimated revenue generated, in USD.",
        },
    },
    "max_ad_unit_revenue": {
        "description": "Estimated MAX mediation revenue and delivery per ad unit, without the network breakdown. This is the only grain at which AppLovin reports ad requests.",
        "docs_url": _MAX_REPORT_DOCS_URL,
        "columns": {
            **_APP_DIMENSIONS,
            "ad_format": "Ad unit ad type: INTER, BANNER or REWARD.",
            "max_ad_unit": "MAX Ad Unit name.",
            "max_ad_unit_id": "MAX Ad Unit ID.",
            "impressions": "Number of impressions shown.",
            "requests": "Number of ad requests made by the SDK.",
            "ecpm": "Estimated eCPM generated, in USD.",
            "estimated_revenue": "Estimated revenue generated, in USD.",
        },
    },
    "publisher_report": {
        "description": "Publisher-side AppLovin monetization: revenue, impressions and clicks earned by your apps, broken down by day, app, placement and geography.",
        "docs_url": _REPORT_DOCS_URL,
        "columns": {
            **_APP_DIMENSIONS,
            "ad_type": "Ad type served: APPOPEN, GRAPHIC, MRAID, PLAY, REWARD or VIDEO.",
            "placement_type": "Placement type: APP_OPEN, BANNER, INTER, LEADER, MREC, NATIVE or REWARDED_INTER.",
            "size": "Ad size: BANNER, INTER, LEADER, MREC or NATIVE.",
            "bidding_integration": "The mediation provider AppLovin bids through: MAX for MAX mediation, Google for AdMob Open Bidding or Google Ad Manager, None for non-bidding integrations.",
            "impressions": "Number of impressions.",
            "clicks": "Number of clicks.",
            "ctr": "Clicks divided by impressions.",
            "ecpm": "Money earned per 1000 impressions.",
            "revenue": "Money earned.",
        },
    },
    "advertiser_report": {
        "description": "Advertiser-side AppLovin campaign performance: spend, installs and attributed sales by day, campaign, traffic source app and geography.",
        "docs_url": _REPORT_DOCS_URL,
        "columns": {
            "day": _APP_DIMENSIONS["day"],
            "campaign": "Campaign name.",
            "campaign_id_external": "Unique reference to a campaign. Does not change when the campaign is renamed.",
            "campaign_type": "The campaign optimization type: CPP, CPE, ad ROAS, IAP ROAS or ROAS.",
            "campaign_ad_type": "ua for user acquisition, or rt for retargeting.",
            "campaign_package_name": "Package name or bundle ID of the promoted app.",
            "application": "Name of the source application the ad ran in.",
            "app_id_external": "Hashed application ID of the source app, commonly called the site ID.",
            "platform": "Platform of the source application: android, fireos, ios or tvos.",
            "country": _APP_DIMENSIONS["country"],
            "device_type": _APP_DIMENSIONS["device_type"],
            "ad_type": "Ad type served: APPOPEN, GRAPHIC, PLAY, REWARD or VIDEO.",
            "size": "Ad size: BANNER, INTER, LEADER, MREC, NATIVE or PRELOAD.",
            "cost": "Advertiser spend.",
            "impressions": "Number of impressions.",
            "clicks": "Number of clicks.",
            "ctr": "Clicks divided by impressions.",
            "conversions": "Number of conversions (installs).",
            "conversion_rate": "Conversions divided by impressions.",
            "average_cpa": "Average cost per conversion.",
            "average_cpc": "Average cost per click.",
            "sales": "Count of attributed sales events. Requires revenue postbacks.",
        },
    },
    "max_cohort_ad_revenue": {
        "description": "MAX cohort revenue: how much revenue users generate in the days after they install, keyed on the install day.",
        "docs_url": _COHORT_DOCS_URL,
        "columns": {
            **_COHORT_DIMENSION_DESCRIPTIONS,
            **_horizon_columns("pub_revenue", "Revenue generated in {days} days since the install."),
            **_horizon_columns("rpi", "Revenue per install generated in {days} days since the install."),
            **_horizon_columns("ads_pub_revenue", "Revenue generated from ads in {days} days since the install."),
            **_horizon_columns(
                "iap_pub_revenue", "Revenue generated from in-app purchases in {days} days since the install."
            ),
        },
    },
    "max_cohort_impressions": {
        "description": "MAX cohort ad impressions: how many impressions users see in the days after they install, keyed on the install day.",
        "docs_url": _COHORT_DOCS_URL,
        "columns": {
            **_COHORT_DIMENSION_DESCRIPTIONS,
            **_horizon_columns("imp", "Number of impressions from users {days} days after the install."),
            **_horizon_columns("imp_per_user", "Impressions per user {days} days after the install."),
            **_horizon_columns("user_count", "Number of users active {days} days after the install."),
        },
    },
    "max_cohort_sessions": {
        "description": "MAX cohort engagement: retention, session counts and time spent in the days after users install, keyed on the install day.",
        "docs_url": _COHORT_DOCS_URL,
        "columns": {
            **_COHORT_DIMENSION_DESCRIPTIONS,
            **_horizon_columns("user_count", "Number of users active {days} days after the install."),
            **_horizon_columns("retention", "Active users {days} days after the install divided by installs."),
            **_horizon_columns("session_count", "Total number of user sessions {days} days after the install."),
            **_horizon_columns("daily_usage", "Average time spent by users {days} days after the install, in seconds."),
            **_horizon_columns("session_length", "Daily usage divided by session count {days} days after the install."),
        },
    },
    "user_ad_revenue": {
        "description": "MAX ad revenue per user, ad unit and placement for each app and day, from the aggregated User-Level Ad Revenue API report.",
        "docs_url": _USER_AD_REVENUE_DOCS_URL,
        "columns": {
            "day": _APP_DIMENSIONS["day"],
            "package_name": _APP_DIMENSIONS["package_name"],
            "platform": _APP_DIMENSIONS["platform"],
            "ad_unit_id": "ID of the MAX ad unit that generated the revenue.",
            "placement": "Ad placement name where the user generated impressions and revenue.",
            "idfa": "Advertising identifier: IDFA on iOS devices, GAID on Android devices.",
            "idfv": "Identifier for vendor.",
            "user_id": "Optional ID of the user, set through the AppLovin SDK.",
            "custom_data": "Custom data passed in from the integration.",
            "impressions": "Number of ads displayed to the user.",
            "revenue": "Revenue generated by the user, in USD, with six-decimal precision.",
        },
    },
    "campaigns": {
        "description": "AppLovin campaigns on the account, with status, budget, goal, tracking and country targeting. Archived campaigns are not listed.",
        "docs_url": _CAMPAIGN_MANAGEMENT_DOCS_URL,
        "columns": {
            "id": "ID of the campaign.",
            "hashed_id": "External ID of the campaign. Same value as campaign_id_external in the Reporting API.",
            "name": "Name of the campaign.",
            "status": "Current state of the campaign: LIVE or PAUSED.",
            "type": "Type of the campaign.",
            "platform": "Platform of the campaign.",
            "package_name": "Package name associated with the campaign.",
            "itunes_id": "iTunes ID associated with the campaign.",
            "bidding_strategy": "Bidding strategy of the campaign.",
            "budget": "Daily budget settings, either for all countries or per country.",
            "goal": "Optimization goal type and goal value, either for all countries or per country.",
            "tracking": "Attribution provider and the click and impression tracking URLs.",
            "targeting": "Country targets of the campaign, with optional US regions or metro areas.",
            "created_at": "Creation time of the campaign, in ISO 8601 format (UTC).",
            "start_date": "Start date of the campaign, in ISO 8601 format (UTC).",
            "end_date": "End date of the campaign, in ISO 8601 format (UTC).",
            "is_continuous_delivery": "True when the campaign has no end date.",
            "is_composite_banner_enabled": "Whether the auto-generated banner based on the app icon and name is enabled.",
        },
    },
    "creative_sets": {
        "description": "Creative sets on the account: the assets, languages and countries each set serves with.",
        "docs_url": _CAMPAIGN_MANAGEMENT_DOCS_URL,
        "columns": {
            "id": "ID of the creative set.",
            "hashed_id": "External ID of the creative set. Same value as creative_set_id in the Reporting API.",
            "name": "Name of the creative set.",
            "status": "Status of the creative set: LIVE or PAUSED.",
            "type": "Type of the campaign.",
            "campaign_id": "ID of the campaign this creative set belongs to.",
            "campaign_ids": "IDs of the campaigns the creative set is included in.",
            "assets": "Assets in the creative set, with their ID, name, status, type and URL.",
            "languages": "Languages the creative set serves in.",
            "countries": "ISO 3166-1 alpha-2 codes of the countries the creative set serves in.",
            "product_page": "iOS custom product page or Android store listing of the creative set.",
            "version": "Creative set version: V1 allows one asset per type, V2 allows several.",
        },
    },
    "campaign_operation_logs": {
        "description": "History of operations on campaigns: creation, updates, status changes and archiving.",
        "docs_url": _CAMPAIGN_MANAGEMENT_DOCS_URL,
        "columns": {
            "operation_id": "Unique ID of the operation.",
            "operation_time": "Time the operation occurred, in ISO 8601 format (UTC).",
            "operation_type": "Type of operation: CREATE_CAMPAIGN, UPDATE_CAMPAIGN, UPDATE_CAMPAIGN_STATUS or ARCHIVE_CAMPAIGN.",
            "operator_name": "Person or system that performed the operation.",
            "campaign_id": "ID of the campaign the operation was performed on.",
            "campaign_name": "Name of the campaign the operation was performed on.",
            "campaign_type": "Type of the campaign.",
            "detail": "Operation payload. Holds the campaign before and after an update, or the status before and after a status change.",
        },
    },
}
