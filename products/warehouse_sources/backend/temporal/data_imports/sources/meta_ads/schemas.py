from enum import StrEnum
from typing import Any

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class MetaAdsResource(StrEnum):
    Campaigns = "campaigns"
    CampaignStats = "campaign_stats"
    Adsets = "adsets"
    AdStats = "ad_stats"
    Ads = "ads"
    AdsetStats = "adset_stats"  # TODO: remove this
    AdAccount = "ad_account"
    AdCreatives = "ad_creatives"
    AdImages = "ad_images"
    AdsPixels = "ads_pixels"
    CustomConversions = "custom_conversions"
    CampaignStatsByAgeGender = "campaign_stats_by_age_gender"
    CampaignStatsByCountry = "campaign_stats_by_country"
    CampaignStatsByRegion = "campaign_stats_by_region"
    CampaignStatsByPlatform = "campaign_stats_by_platform"
    CampaignStatsHourly = "campaign_stats_hourly"
    AdsetStatsByAgeGender = "adset_stats_by_age_gender"
    AdsetStatsByCountry = "adset_stats_by_country"
    AdsetStatsByRegion = "adset_stats_by_region"
    AdsetStatsByPlatform = "adset_stats_by_platform"
    AdsetStatsHourly = "adset_stats_hourly"
    AdStatsByAgeGender = "ad_stats_by_age_gender"
    AdStatsByCountry = "ad_stats_by_country"
    AdStatsByRegion = "ad_stats_by_region"
    AdStatsByPlatform = "ad_stats_by_platform"
    AdStatsHourly = "ad_stats_hourly"


# Insights broken down by a dimension. Each one multiplies the daily row count by the
# cardinality of its breakdown, and only some accounts care about any given dimension, so
# they stay off in the schema picker until a user asks for them. The same breakdown dimensions
# are offered at campaign, adset and ad grain — creative testing and ad-fatigue analysis only
# make sense at ad level, which campaign-grain rows can't express.
BREAKDOWN_STATS_ENDPOINTS = (
    MetaAdsResource.CampaignStatsByAgeGender,
    MetaAdsResource.CampaignStatsByCountry,
    MetaAdsResource.CampaignStatsByRegion,
    MetaAdsResource.CampaignStatsByPlatform,
    MetaAdsResource.CampaignStatsHourly,
    MetaAdsResource.AdsetStatsByAgeGender,
    MetaAdsResource.AdsetStatsByCountry,
    MetaAdsResource.AdsetStatsByRegion,
    MetaAdsResource.AdsetStatsByPlatform,
    MetaAdsResource.AdsetStatsHourly,
    MetaAdsResource.AdStatsByAgeGender,
    MetaAdsResource.AdStatsByCountry,
    MetaAdsResource.AdStatsByRegion,
    MetaAdsResource.AdStatsByPlatform,
    MetaAdsResource.AdStatsHourly,
)

ENDPOINTS = (
    MetaAdsResource.Campaigns,
    MetaAdsResource.CampaignStats,
    MetaAdsResource.Adsets,
    MetaAdsResource.AdsetStats,
    MetaAdsResource.Ads,
    MetaAdsResource.AdStats,
    MetaAdsResource.AdAccount,
    MetaAdsResource.AdCreatives,
    MetaAdsResource.AdImages,
    MetaAdsResource.AdsPixels,
    MetaAdsResource.CustomConversions,
    *BREAKDOWN_STATS_ENDPOINTS,
)

INCREMENTAL_ENDPOINTS = (
    MetaAdsResource.AdStats,
    MetaAdsResource.AdsetStats,
    MetaAdsResource.CampaignStats,
    *BREAKDOWN_STATS_ENDPOINTS,
)

SHOULD_SYNC_DEFAULT: dict[str, bool] = dict.fromkeys(BREAKDOWN_STATS_ENDPOINTS, False)


def _date_start_incremental_field() -> list[IncrementalField]:
    return [
        {
            "label": "date_start",
            "type": IncrementalFieldType.Date,
            "field": "date_start",
            "field_type": IncrementalFieldType.Date,
        }
    ]


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: _date_start_incremental_field() for endpoint in INCREMENTAL_ENDPOINTS
}

# Insights metrics requested for every breakdown table, at any level, mirroring the plain stats
# tables. The grain columns (`ad_id`, `adset_id`, `campaign_id`) that identify a row are prepended
# per level below. Breakdown dimensions are deliberately absent: Meta returns them as columns
# automatically and rejects the request when they are also passed in `fields`, since they are
# breakdowns rather than AdsInsights fields.
_BREAKDOWN_METRIC_FIELDS = [
    "account_id",
    "account_currency",
    "date_start",
    "date_stop",
    "impressions",
    "clicks",
    "spend",
    "reach",
    "frequency",
    "cpm",
    "cpc",
    "ctr",
    "cpp",
    "cost_per_unique_click",
    "unique_clicks",
    "unique_ctr",
    "inline_link_clicks",
    "outbound_clicks",
    "actions",
    "unique_actions",
    "conversions",
    "conversion_values",
    "cost_per_action_type",
    "action_values",
    "purchase_roas",
    "website_purchase_roas",
    # The attribution window Meta actually applied to these rows, so imported numbers can be
    # reconciled against Ads Manager (see the source's attribution-window config).
    "attribution_setting",
]

CAMPAIGN_BREAKDOWN_STATS_FIELDS = ["campaign_id", *_BREAKDOWN_METRIC_FIELDS]
ADSET_BREAKDOWN_STATS_FIELDS = ["adset_id", "campaign_id", *_BREAKDOWN_METRIC_FIELDS]
AD_BREAKDOWN_STATS_FIELDS = ["ad_id", "adset_id", "campaign_id", *_BREAKDOWN_METRIC_FIELDS]

# Meta: "Hourly breakdowns do not support unique fields, which are any fields prepended with
# `unique_*`, `reach` or `frequency`." `cpp` and `cost_per_unique_click` are derived from those,
# so the hourly table asks for none of them rather than storing columns Meta zeroes out.
_HOURLY_UNSUPPORTED_FIELDS = {
    "reach",
    "frequency",
    "cpp",
    "cost_per_unique_click",
    "unique_clicks",
    "unique_ctr",
    "unique_actions",
}


def _hourly_fields(field_names: list[str]) -> list[str]:
    return [f for f in field_names if f not in _HOURLY_UNSUPPORTED_FIELDS]


HOURLY_BREAKDOWN_STATS_FIELDS = _hourly_fields(CAMPAIGN_BREAKDOWN_STATS_FIELDS)

# The Insights `level` and its grain column, which heads that level's primary key and field list.
_LEVEL_GRAIN_COLUMN = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}


def _breakdown_stats(level: str, breakdowns: list[str], field_names: list[str]) -> dict[str, Any]:
    """Insights split by `breakdowns` at `level` (campaign/adset/ad).

    Every breakdown dimension joins the primary key: a grain/day pair now yields one row per
    combination of dimension values, so keying on the grain id + `date_start` alone would collapse
    them into duplicates that merge multi-matches on every sync.
    """
    return {
        "primary_keys": [_LEVEL_GRAIN_COLUMN[level], "account_id", "date_start", *breakdowns],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/insights",
        "extra_params": {
            "level": level,
            "time_increment": 1,  # daily
            "breakdowns": ",".join(breakdowns),
        },
        "field_names": field_names,
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["date_start"],
        "is_stats": True,
    }


RESOURCE_SCHEMAS: dict[MetaAdsResource, dict[str, Any]] = {
    MetaAdsResource.Ads: {
        "primary_keys": ["id", "account_id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/ads",
        "extra_params": {},
        "field_names": [
            "id",
            "account_id",
            "adset_id",
            "campaign_id",
            "name",
            "status",
            "configured_status",
            "effective_status",
            "creative",
            "bid_amount",
            "created_time",
            "updated_time",
            "tracking_specs",
            "conversion_specs",
        ],
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["created_time"],
    },
    MetaAdsResource.AdStats: {
        "primary_keys": ["ad_id", "account_id", "date_start"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/insights",
        "extra_params": {
            "level": "ad",
            "time_increment": 1,  # daily
        },
        "field_names": [
            "ad_id",
            "account_id",
            "account_currency",
            "adset_id",
            "campaign_id",
            "date_start",
            "date_stop",
            "impressions",
            "clicks",
            "spend",
            "reach",
            "frequency",
            "cpm",
            "cpc",
            "ctr",
            "cpp",
            "cost_per_unique_click",
            "unique_clicks",
            "unique_ctr",
            "inline_link_clicks",
            "outbound_clicks",
            "actions",
            "unique_actions",
            "conversions",
            "conversion_values",
            "cost_per_action_type",
            "action_values",
            "purchase_roas",
            "website_purchase_roas",
            "attribution_setting",
            "video_30_sec_watched_actions",
            "video_p25_watched_actions",
            "video_p50_watched_actions",
            "video_p75_watched_actions",
            "video_p95_watched_actions",
            "video_p100_watched_actions",
        ],
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["date_start"],
        "is_stats": True,
    },
    MetaAdsResource.Adsets: {
        "primary_keys": ["id", "account_id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/adsets",
        "extra_params": {},
        "field_names": [
            "id",
            "account_id",
            "campaign_id",
            "name",
            "status",
            "configured_status",
            "effective_status",
            "optimization_goal",
            "billing_event",
            "bid_amount",
            "budget_remaining",
            "daily_budget",
            "lifetime_budget",
            "created_time",
            "updated_time",
            "start_time",
            "end_time",
            "targeting",
            "promoted_object",
        ],
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["created_time"],
    },
    MetaAdsResource.AdsetStats: {
        "primary_keys": ["adset_id", "account_id", "date_start"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/insights",
        "extra_params": {
            "level": "adset",
            "time_increment": 1,  # daily
        },
        "field_names": [
            "adset_id",
            "account_id",
            "account_currency",
            "campaign_id",
            "date_start",
            "date_stop",
            "impressions",
            "clicks",
            "spend",
            "reach",
            "frequency",
            "cpm",
            "cpc",
            "ctr",
            "cpp",
            "cost_per_unique_click",
            "unique_clicks",
            "unique_ctr",
            "inline_link_clicks",
            "outbound_clicks",
            "actions",
            "unique_actions",
            "conversions",
            "conversion_values",
            "cost_per_action_type",
            "action_values",
            "purchase_roas",
            "website_purchase_roas",
            "attribution_setting",
        ],
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["date_start"],
        "is_stats": True,
    },
    MetaAdsResource.Campaigns: {
        "primary_keys": ["id", "account_id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/campaigns",
        "extra_params": {},
        "field_names": [
            "id",
            "account_id",
            "name",
            "status",
            "configured_status",
            "effective_status",
            "objective",
            "buying_type",
            "daily_budget",
            "lifetime_budget",
            "budget_remaining",
            "created_time",
            "updated_time",
            "start_time",
            "stop_time",
            "special_ad_categories",
        ],
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["created_time"],
    },
    MetaAdsResource.CampaignStats: {
        "primary_keys": ["campaign_id", "account_id", "date_start"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/insights",
        "extra_params": {
            "level": "campaign",
            "time_increment": 1,  # daily
        },
        "field_names": [
            "campaign_id",
            "account_id",
            "account_currency",
            "date_start",
            "date_stop",
            "impressions",
            "clicks",
            "spend",
            "reach",
            "frequency",
            "cpm",
            "cpc",
            "ctr",
            "cpp",
            "cost_per_unique_click",
            "unique_clicks",
            "unique_ctr",
            "inline_link_clicks",
            "outbound_clicks",
            "actions",
            "unique_actions",
            "conversions",
            "conversion_values",
            "cost_per_action_type",
            "action_values",
            "purchase_roas",
            "website_purchase_roas",
            "attribution_setting",
        ],
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["date_start"],
        "is_stats": True,
    },
    # `GET /act_<id>` returns the account node itself, not a `data` list, so this one endpoint
    # reads a single object. One row per source, carrying the currency every spend figure in the
    # stats tables is denominated in.
    MetaAdsResource.AdAccount: {
        "primary_keys": ["id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}",
        "extra_params": {},
        "field_names": [
            "id",
            "account_id",
            "name",
            "account_status",
            "currency",
            "timezone_id",
            "timezone_name",
            "timezone_offset_hours_utc",
            "amount_spent",
            "balance",
            "spend_cap",
            "min_campaign_group_spend_cap",
            "min_daily_budget",
            "created_time",
            "business_country_code",
            "business_name",
            "disable_reason",
            "capabilities",
            # No `business`, `owner`, `funding_source_details`, `is_prepay_account`, or
            # `tos_accepted`: each needs the `business_management` scope, which the Meta OAuth
            # consent doesn't request (`ads_read` only) — see `AD_ACCOUNT_FIELDS` in meta_ads.py,
            # which excludes `business` from the account-listing request for the same reason.
            # Meta rejects the whole field set when any one of them is asked for without that
            # scope, so a single one of these sneaking back in fails this table's sync outright.
        ],
        "single_object": True,
    },
    # AdCreative carries no created_time or updated_time, so there is no stable column to
    # partition on.
    MetaAdsResource.AdCreatives: {
        "primary_keys": ["id", "account_id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/adcreatives",
        "extra_params": {},
        "field_names": [
            "id",
            "account_id",
            "name",
            "status",
            "object_type",
            "object_story_id",
            "effective_object_story_id",
            "object_story_spec",
            "thumbnail_url",
            "image_url",
            "image_hash",
            "video_id",
            "body",
            "title",
            "call_to_action_type",
            "link_url",
            "url_tags",
            "instagram_permalink_url",
            "actor_id",
            "asset_feed_spec",
            "degrees_of_freedom_spec",
            "effective_authorization_category",
        ],
    },
    # `hash` rather than `id` as the key: Meta documents it as AdImage's default field, and the
    # `id` it returns is just the account and hash joined.
    MetaAdsResource.AdImages: {
        "primary_keys": ["hash", "account_id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/adimages",
        "extra_params": {},
        "field_names": [
            "id",
            "hash",
            "account_id",
            "name",
            "url",
            "url_128",
            "permalink_url",
            "width",
            "height",
            "original_width",
            "original_height",
            "status",
            "created_time",
            "updated_time",
            "creatives",
            "is_associated_creatives_in_adgroups",
        ],
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["created_time"],
    },
    # AdsPixel returns no account_id, and pixel ids are unique across Meta, so `id` alone keys
    # the table.
    MetaAdsResource.AdsPixels: {
        "primary_keys": ["id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/adspixels",
        "extra_params": {},
        "field_names": [
            "id",
            "name",
            "code",
            "creation_time",
            "last_fired_time",
            "is_created_by_business",
            "is_unavailable",
            "data_use_setting",
            "enable_automatic_matching",
            "automatic_matching_fields",
            "owner_business",
        ],
    },
    MetaAdsResource.CustomConversions: {
        "primary_keys": ["id", "account_id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/customconversions",
        "extra_params": {},
        "field_names": [
            "id",
            "account_id",
            "name",
            "description",
            "creation_time",
            "first_fired_time",
            "last_fired_time",
            "custom_event_type",
            "default_conversion_value",
            "event_source_type",
            "is_archived",
            "is_unavailable",
            "pixel",
            "rule",
            "retention_days",
            "data_sources",
            "business",
        ],
    },
    MetaAdsResource.CampaignStatsByAgeGender: _breakdown_stats(
        "campaign", ["age", "gender"], CAMPAIGN_BREAKDOWN_STATS_FIELDS
    ),
    MetaAdsResource.CampaignStatsByCountry: _breakdown_stats("campaign", ["country"], CAMPAIGN_BREAKDOWN_STATS_FIELDS),
    MetaAdsResource.CampaignStatsByRegion: _breakdown_stats("campaign", ["region"], CAMPAIGN_BREAKDOWN_STATS_FIELDS),
    MetaAdsResource.CampaignStatsByPlatform: _breakdown_stats(
        "campaign", ["publisher_platform", "platform_position", "impression_device"], CAMPAIGN_BREAKDOWN_STATS_FIELDS
    ),
    MetaAdsResource.CampaignStatsHourly: _breakdown_stats(
        "campaign", ["hourly_stats_aggregated_by_advertiser_time_zone"], HOURLY_BREAKDOWN_STATS_FIELDS
    ),
    MetaAdsResource.AdsetStatsByAgeGender: _breakdown_stats("adset", ["age", "gender"], ADSET_BREAKDOWN_STATS_FIELDS),
    MetaAdsResource.AdsetStatsByCountry: _breakdown_stats("adset", ["country"], ADSET_BREAKDOWN_STATS_FIELDS),
    MetaAdsResource.AdsetStatsByRegion: _breakdown_stats("adset", ["region"], ADSET_BREAKDOWN_STATS_FIELDS),
    MetaAdsResource.AdsetStatsByPlatform: _breakdown_stats(
        "adset", ["publisher_platform", "platform_position", "impression_device"], ADSET_BREAKDOWN_STATS_FIELDS
    ),
    MetaAdsResource.AdsetStatsHourly: _breakdown_stats(
        "adset", ["hourly_stats_aggregated_by_advertiser_time_zone"], _hourly_fields(ADSET_BREAKDOWN_STATS_FIELDS)
    ),
    MetaAdsResource.AdStatsByAgeGender: _breakdown_stats("ad", ["age", "gender"], AD_BREAKDOWN_STATS_FIELDS),
    MetaAdsResource.AdStatsByCountry: _breakdown_stats("ad", ["country"], AD_BREAKDOWN_STATS_FIELDS),
    MetaAdsResource.AdStatsByRegion: _breakdown_stats("ad", ["region"], AD_BREAKDOWN_STATS_FIELDS),
    MetaAdsResource.AdStatsByPlatform: _breakdown_stats(
        "ad", ["publisher_platform", "platform_position", "impression_device"], AD_BREAKDOWN_STATS_FIELDS
    ),
    MetaAdsResource.AdStatsHourly: _breakdown_stats(
        "ad", ["hourly_stats_aggregated_by_advertiser_time_zone"], _hourly_fields(AD_BREAKDOWN_STATS_FIELDS)
    ),
}
