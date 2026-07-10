"""Canonical, documentation-sourced descriptions for Google Ads endpoints and columns.

Sourced from the official Google Ads API reference
(https://developers.google.com/google-ads/api/fields/v17/overview). Keyed by the table aliases in
`schemas.py` `RESOURCE_SCHEMAS`, which match the `ExternalDataSchema.name` of a synced Google Ads
table. Column names use the synced form (the qualified API field with dots replaced by underscores,
e.g. `campaign.id` -> `campaign_id`, `metrics.clicks` -> `metrics_clicks`). Columns absent here fall
back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Resource-identifier columns shared by most reports.
_IDS = {
    "customer_id": "The Google Ads customer (account) ID the row belongs to.",
    "customer_currency_code": "Three-letter ISO 4217 currency code of the account.",
    "campaign_id": "The campaign ID the row belongs to.",
    "ad_group_id": "The ad group ID the row belongs to.",
}

# Performance metrics shared by the *_stats reports. Google Ads returns money in micros
# (1,000,000 micros = one unit of the account currency).
_METRICS = {
    "metrics_clicks": "Number of clicks.",
    "metrics_impressions": "Number of times the ad was shown.",
    "metrics_ctr": "Click-through rate (clicks divided by impressions).",
    "metrics_cost_micros": "Total cost in micros (1,000,000 micros = one currency unit).",
    "metrics_average_cpc": "Average cost-per-click, in micros.",
    "metrics_average_cpm": "Average cost-per-thousand-impressions, in micros.",
    "metrics_average_cost": "Average amount paid per interaction, in micros.",
    "metrics_conversions": "Number of conversions.",
    "metrics_conversions_value": "Total value of conversions.",
    "metrics_conversions_from_interactions_rate": "Conversions divided by interactions.",
    "metrics_cost_per_conversion": "Average cost per conversion, in micros.",
    "metrics_value_per_conversion": "Average value per conversion.",
    "metrics_interactions": "Number of interactions (the main user action for the ad format).",
    "metrics_interaction_rate": "Interactions divided by impressions.",
    "metrics_all_conversions": "Number of conversions across all conversion actions, including non-primary.",
    "metrics_all_conversions_value": "Total value of all conversions.",
    "metrics_view_through_conversions": "Conversions counted from view-through (no click) attribution.",
}

# Date/time segmentation columns shared by the *_stats reports.
_SEGMENTS = {
    "segments_date": "The date the metrics are reported for (YYYY-MM-DD).",
    "segments_day_of_week": "Day of week the metrics are reported for.",
    "segments_week": "Week (starting Monday) the metrics are reported for.",
    "segments_month": "Month the metrics are reported for.",
    "segments_quarter": "Quarter the metrics are reported for.",
    "segments_year": "Year the metrics are reported for.",
    "segments_device": "Device the metrics are reported for (e.g. mobile, desktop, tablet).",
    "segments_ad_network_type": "Ad network the metrics are reported for (e.g. search, display, YouTube).",
    "segments_click_type": "Type of click the metrics are reported for.",
}


def _stats_columns(**overrides: str) -> dict[str, str]:
    return {**_IDS, **_METRICS, **_SEGMENTS, **overrides}


def _overview_stats_columns(**overrides: str) -> dict[str, str]:
    """Like _stats_columns but without segments_click_type — overview tables don't segment by click type."""
    segments = {k: v for k, v in _SEGMENTS.items() if k != "segments_click_type"}
    return {**_IDS, **_METRICS, **segments, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "ad": {
        "description": "An ad within an ad group (ad_group_ad), including its creative content and status.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/ad_group_ad",
        "columns": {
            **_IDS,
            "ad_group_ad_ad_id": "Unique ID of the ad.",
            "ad_group_ad_ad_name": "Name of the ad.",
            "ad_group_ad_ad_type": "Type of the ad (e.g. responsive search ad, image ad).",
            "ad_group_ad_status": "Status of the ad (enabled, paused, or removed).",
            "ad_group_ad_ad_display_url": "Display URL shown with the ad.",
            "ad_group_ad_ad_final_urls": "Landing-page URLs the ad sends users to.",
            "ad_group_ad_ad_strength": "Google's rated strength of the ad.",
            "ad_group_ad_policy_summary_approval_status": "Overall policy approval status of the ad.",
        },
    },
    "ad_stats": {
        "description": "Daily performance metrics for ads (ad_group_ad), segmented by date, device, and network.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/ad_group_ad",
        "columns": _stats_columns(
            ad_group_ad_ad_id="Unique ID of the ad the metrics belong to.",
            metrics_active_view_measurability="Share of impressions that were measurable by Active View.",
        ),
    },
    "ad_overview_stats": {
        "description": "Daily ad (ad_group_ad) performance without click-type segmentation, so cost totals reconcile to the Google Ads UI. Segmented by date, device, and network.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/ad_group_ad",
        "columns": _overview_stats_columns(
            ad_group_ad_ad_id="Unique ID of the ad the metrics belong to.",
            metrics_active_view_measurability="Share of impressions that were measurable by Active View.",
        ),
    },
    "ad_group": {
        "description": "An ad group — a set of ads and keywords sharing bids and targeting within a campaign.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/ad_group",
        "columns": {
            **_IDS,
            "ad_group_name": "Name of the ad group.",
            "ad_group_status": "Status of the ad group (enabled, paused, or removed).",
            "ad_group_type": "Type of the ad group (e.g. search standard, display standard).",
            "ad_group_cpc_bid_micros": "Maximum cost-per-click bid for the ad group, in micros.",
            "ad_group_cpm_bid_micros": "Maximum cost-per-thousand-impressions bid, in micros.",
            "ad_group_tracking_url_template": "URL template for constructing tracking URLs for the ad group.",
            "campaign_bidding_strategy_type": "Bidding strategy type of the parent campaign.",
        },
    },
    "ad_group_stats": {
        "description": "Daily performance metrics for ad groups, segmented by date, device, and network.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/ad_group",
        "columns": _stats_columns(),
    },
    "ad_group_overview_stats": {
        "description": "Daily ad group performance without click-type segmentation, so cost totals reconcile to the Google Ads UI. Segmented by date, device, and network.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/ad_group",
        "columns": _overview_stats_columns(),
    },
    "campaign": {
        "description": "A Google Ads campaign — a budgeted set of ad groups sharing settings and goals.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/campaign",
        "columns": {
            **_IDS,
            "campaign_name": "Name of the campaign.",
            "campaign_status": "Status of the campaign (enabled, paused, or removed).",
            "campaign_serving_status": "Whether the campaign is currently able to serve ads.",
            "campaign_advertising_channel_type": "Primary serving target (e.g. search, display, shopping, video).",
            "campaign_advertising_channel_sub_type": "More specific serving target within the channel type.",
            "campaign_bidding_strategy_type": "Automated or manual bidding strategy in use.",
            "campaign_start_date": "Date the campaign started serving.",
            "campaign_end_date": "Date the campaign stops serving.",
            "campaign_budget_amount_micros": "Daily budget of the campaign, in micros.",
        },
    },
    "campaign_stats": {
        "description": "Daily performance metrics for campaigns, segmented by date, device, and network.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/campaign",
        "columns": _stats_columns(
            campaign_name="Name of the campaign.",
            campaign_advertising_channel_type="Primary serving target of the campaign.",
            campaign_bidding_strategy_type="Bidding strategy of the campaign.",
        ),
    },
    "campaign_overview_stats": {
        "description": "Daily campaign performance overview including video metrics, segmented by date and device.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/campaign",
        "columns": _overview_stats_columns(
            campaign_name="Name of the campaign.",
            campaign_advertising_channel_type="Primary serving target of the campaign.",
            metrics_video_views="Number of views of a video ad.",
            metrics_average_cpv="Average cost-per-view of a video ad, in micros.",
            metrics_video_view_rate="Video views divided by video ad impressions.",
        ),
    },
    "keyword": {
        "description": "A keyword criterion (keyword_view) — a search term that triggers an ad, with its bid and quality.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/keyword_view",
        "columns": {
            **_IDS,
            "ad_group_criterion_criterion_id": "Unique ID of the keyword criterion.",
            "ad_group_criterion_keyword_text": "The keyword text.",
            "ad_group_criterion_keyword_match_type": "Match type (exact, phrase, or broad).",
            "ad_group_criterion_status": "Status of the keyword (enabled, paused, or removed).",
            "ad_group_criterion_negative": "Whether the keyword is a negative (exclusion) keyword.",
            "ad_group_criterion_quality_info_quality_score": "Google's 1-10 quality score for the keyword.",
            "ad_group_criterion_system_serving_status": "System-determined serving status of the keyword (e.g. eligible or rare searches).",
            "ad_group_criterion_position_estimates_first_position_cpc_micros": "Estimated CPC bid, in micros, required to show the ad in the first position.",
        },
    },
    "keyword_stats": {
        "description": "Daily performance metrics for keywords (keyword_view), segmented by date, device, and network.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/keyword_view",
        "columns": _stats_columns(
            ad_group_criterion_criterion_id="Unique ID of the keyword criterion the metrics belong to.",
        ),
    },
    "video": {
        "description": "A video asset used in video ads, with its title and duration.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/video",
        "columns": {
            **_IDS,
            "video_id": "Unique ID of the video (the YouTube video ID).",
            "video_title": "Title of the video.",
            "video_duration_millis": "Duration of the video in milliseconds.",
            "ad_group_ad_status": "Status of the ad serving the video.",
        },
    },
    "video_stats": {
        "description": "Daily performance metrics for videos, segmented by date, device, and network.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/video",
        "columns": _stats_columns(
            video_id="Unique ID of the video the metrics belong to.",
            video_channel_id="YouTube channel ID the video belongs to.",
        ),
    },
    "video_performance_stats": {
        "description": "Daily video performance with view-quartile metrics, segmented by date and device.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/video",
        "columns": _stats_columns(
            video_id="Unique ID of the video the metrics belong to.",
            video_channel_id="YouTube channel ID the video belongs to.",
            metrics_video_views="Number of views of the video ad.",
            metrics_average_cpv="Average cost-per-view, in micros.",
            metrics_video_view_rate="Video views divided by video ad impressions.",
            metrics_video_quartile_p25_rate="Share of impressions that watched at least 25% of the video.",
            metrics_video_quartile_p50_rate="Share of impressions that watched at least 50% of the video.",
            metrics_video_quartile_p75_rate="Share of impressions that watched at least 75% of the video.",
            metrics_video_quartile_p100_rate="Share of impressions that watched the entire video.",
        ),
    },
    "customer_stats": {
        "description": "Daily account-level performance totals for the Google Ads customer.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/customer",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID.",
            "customer_descriptive_name": "Human-readable name of the account.",
            "customer_currency_code": "Three-letter ISO 4217 currency code of the account.",
            "metrics_clicks": "Number of clicks.",
            "metrics_impressions": "Number of impressions.",
            "metrics_cost_micros": "Total cost in micros.",
            "metrics_conversions": "Number of conversions.",
            "segments_date": "The date the metrics are reported for.",
        },
    },
    "search_term_stats": {
        "description": "Daily performance for the actual search terms that triggered ads (search_term_view).",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/search_term_view",
        "columns": {
            **_IDS,
            "search_term_view_search_term": "The search query a user entered that triggered an ad.",
            "search_term_view_status": "Whether the search term has been added or excluded as a keyword.",
            "metrics_clicks": "Number of clicks.",
            "metrics_impressions": "Number of impressions.",
            "metrics_cost_micros": "Total cost in micros.",
            "metrics_conversions": "Number of conversions.",
            "segments_date": "The date the metrics are reported for.",
        },
    },
    "geographic_stats": {
        "description": "Daily performance broken out by user geographic location (geographic_view).",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/geographic_view",
        "columns": {
            **_IDS,
            "geographic_view_country_criterion_id": "Criterion ID of the country the user was in.",
            "geographic_view_location_type": "Whether location is based on area of interest or physical presence.",
            "metrics_clicks": "Number of clicks.",
            "metrics_impressions": "Number of impressions.",
            "metrics_cost_micros": "Total cost in micros.",
            "metrics_conversions": "Number of conversions.",
            "segments_date": "The date the metrics are reported for.",
        },
    },
    "asset_group": {
        "description": "An asset group within a Performance Max campaign, grouping creative assets for a theme.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/asset_group",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID the asset group belongs to.",
            "campaign_id": "The campaign the asset group belongs to.",
            "asset_group_id": "Unique ID of the asset group.",
            "asset_group_name": "Name of the asset group.",
            "asset_group_status": "Status of the asset group (enabled, paused, or removed).",
            "asset_group_primary_status": "Aggregated primary serving status of the asset group.",
            "asset_group_ad_strength": "Google's rated ad strength of the asset group.",
            "asset_group_final_urls": "Landing-page URLs for the asset group.",
            "asset_group_path2": "Second part of optional text appended to the auto-generated display URL.",
        },
    },
    "asset_group_stats": {
        "description": "Daily performance metrics for Performance Max asset groups, segmented by date.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/asset_group",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID.",
            "customer_currency_code": "Three-letter ISO 4217 currency code of the account.",
            "campaign_id": "The campaign the asset group belongs to.",
            "asset_group_id": "Unique ID of the asset group the metrics belong to.",
            "metrics_clicks": "Number of clicks.",
            "metrics_impressions": "Number of impressions.",
            "metrics_cost_micros": "Total cost in micros.",
            "metrics_conversions": "Number of conversions.",
            "metrics_conversions_value": "Total value of conversions.",
            "metrics_all_conversions": "Number of conversions across all conversion actions.",
            "metrics_all_conversions_value": "Total value of all conversions.",
            "metrics_view_through_conversions": "View-through conversions.",
            "segments_date": "The date the metrics are reported for.",
            "segments_month": "Month the metrics are reported for.",
        },
    },
    "shopping_performance_view": {
        "description": "Daily Shopping ad performance broken out by product attributes (shopping_performance_view).",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/shopping_performance_view",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID.",
            "customer_currency_code": "Three-letter ISO 4217 currency code of the account.",
            "campaign_id": "The campaign the metrics belong to.",
            "segments_product_item_id": "Merchant Center item ID of the product.",
            "segments_product_title": "Title of the product.",
            "segments_product_brand": "Brand of the product.",
            "segments_product_condition": "Condition of the product (new, used, refurbished).",
            "segments_product_channel": "Sales channel of the product (online or local).",
            "segments_product_type_l1": "First-level product type category.",
            "segments_product_type_l2": "Second-level product type category.",
            "metrics_clicks": "Number of clicks.",
            "metrics_impressions": "Number of impressions.",
            "metrics_cost_micros": "Total cost in micros.",
            "metrics_conversions": "Number of conversions.",
            "metrics_conversions_value": "Total value of conversions.",
            "segments_date": "The date the metrics are reported for.",
        },
    },
    "conversion_action": {
        "description": "A conversion action — an event (purchase, sign-up, call) that Google Ads counts as a conversion.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v17/conversion_action",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID the conversion action belongs to.",
            "conversion_action_id": "Unique ID of the conversion action.",
            "conversion_action_name": "Name of the conversion action.",
            "conversion_action_status": "Status of the conversion action (enabled, removed, or hidden).",
            "conversion_action_type": "Type/source of the conversion action (e.g. website, app, phone calls).",
            "conversion_action_category": "Category of the conversion (e.g. purchase, lead, sign-up).",
            "conversion_action_origin": "Origin of the conversion action.",
            "conversion_action_primary_for_goal": "Whether this action is primary for its conversion goal.",
            "conversion_action_counting_type": "Whether every conversion or one per click/interaction is counted.",
        },
    },
}
