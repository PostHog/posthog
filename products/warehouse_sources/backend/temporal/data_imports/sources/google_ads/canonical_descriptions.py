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
    "ad_group_criterion": {
        "description": "Every targeting criterion at ad group level, including negative keywords and other exclusions. Unlike the keyword table, this reaches negative and non-keyword criteria.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/ad_group_criterion",
        "columns": {
            **_IDS,
            "ad_group_criterion_criterion_id": "Unique ID of the criterion.",
            "ad_group_criterion_type": "Type of the criterion (e.g. keyword, placement, age range, user list).",
            "ad_group_criterion_status": "Status of the criterion (enabled, paused, or removed).",
            "ad_group_criterion_negative": "Whether the criterion is a negative (exclusion) rather than a target.",
            "ad_group_criterion_system_serving_status": "System-determined serving status of the criterion.",
            "ad_group_criterion_approval_status": "Approval status of the criterion.",
            "ad_group_criterion_display_name": "Display name of the criterion.",
            "ad_group_criterion_bid_modifier": "Bid modifier applied to the criterion.",
            "ad_group_criterion_cpc_bid_micros": "Cost-per-click bid on the criterion, in micros.",
            "ad_group_criterion_effective_cpc_bid_micros": "Effective cost-per-click bid, in micros, after inheritance.",
            "ad_group_criterion_keyword_text": "Keyword text, when the criterion is a keyword.",
            "ad_group_criterion_keyword_match_type": "Keyword match type (exact, phrase, or broad), when the criterion is a keyword.",
            "ad_group_criterion_placement_url": "Placement URL, when the criterion is a placement.",
            "ad_group_criterion_age_range_type": "Age range bucket, when the criterion is an age range.",
            "ad_group_criterion_gender_type": "Gender, when the criterion is a gender.",
            "ad_group_criterion_topic_topic_constant": "Topic constant, when the criterion is a topic.",
            "ad_group_criterion_user_list_user_list": "Resource name of the user list, when the criterion is a user list.",
            "ad_group_criterion_final_urls": "Final landing page URLs for the criterion.",
            "ad_group_criterion_tracking_url_template": "URL template for constructing tracking URLs for the criterion.",
        },
    },
    "campaign_criterion": {
        "description": "Every targeting criterion at campaign level, including negative keywords, excluded locations, languages, devices and other exclusions.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/campaign_criterion",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID the row belongs to.",
            "campaign_id": "The campaign ID the row belongs to.",
            "campaign_criterion_criterion_id": "Unique ID of the criterion.",
            "campaign_criterion_type": "Type of the criterion (e.g. keyword, location, language, device).",
            "campaign_criterion_status": "Status of the criterion (enabled, paused, or removed).",
            "campaign_criterion_negative": "Whether the criterion is a negative (exclusion) rather than a target.",
            "campaign_criterion_bid_modifier": "Bid modifier applied to the criterion.",
            "campaign_criterion_display_name": "Display name of the criterion.",
            "campaign_criterion_keyword_text": "Keyword text, when the criterion is a keyword.",
            "campaign_criterion_keyword_match_type": "Keyword match type (exact, phrase, or broad), when the criterion is a keyword.",
            "campaign_criterion_location_geo_target_constant": "Resource name of the targeted geo location, when the criterion is a location.",
            "campaign_criterion_language_language_constant": "Resource name of the targeted language, when the criterion is a language.",
            "campaign_criterion_device_type": "Device type, when the criterion is a device.",
            "campaign_criterion_age_range_type": "Age range bucket, when the criterion is an age range.",
            "campaign_criterion_gender_type": "Gender, when the criterion is a gender.",
            "campaign_criterion_placement_url": "Placement URL, when the criterion is a placement.",
            "campaign_criterion_user_list_user_list": "Resource name of the user list, when the criterion is a user list.",
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
    "customer": {
        "description": "Account-level settings for the Google Ads customer — timezone, currency, auto-tagging, manager status and conversion tracking. One row per account, distinct from the daily metrics in customer_stats.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/customer",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID.",
            "customer_descriptive_name": "Human-readable name of the account.",
            "customer_currency_code": "Three-letter ISO 4217 currency code of the account.",
            "customer_time_zone": "IANA time zone of the account (e.g. America/New_York).",
            "customer_tracking_url_template": "URL template for constructing tracking URLs, applied account-wide.",
            "customer_final_url_suffix": "Query parameters appended to landing page URLs, applied account-wide.",
            "customer_auto_tagging_enabled": "Whether auto-tagging (the gclid URL parameter) is enabled.",
            "customer_has_partners_badge": "Whether the account holds the Google Partners badge.",
            "customer_manager": "Whether the account is a manager (MCC) account.",
            "customer_test_account": "Whether the account is a test account.",
            "customer_status": "Status of the account (enabled, canceled, suspended, or closed).",
            "customer_optimization_score": "Optimization score of the account, from 0 to 1.",
            "customer_optimization_score_weight": "Weight used to combine this account's optimization score into a manager-level score.",
            "customer_pay_per_conversion_eligibility_failure_reasons": "Reasons the account is ineligible for pay-per-conversion billing, if any.",
            "customer_conversion_tracking_setting_conversion_tracking_id": "Conversion tracking ID used for this account's conversions.",
            "customer_conversion_tracking_setting_cross_account_conversion_tracking_id": "Conversion tracking ID of the manager account, when conversion tracking is managed at manager level.",
            "customer_conversion_tracking_setting_accepted_customer_data_terms": "Whether the customer has accepted the customer data terms.",
            "customer_conversion_tracking_setting_conversion_tracking_status": "Conversion tracking status of the account (e.g. not converting, converting with this account, or converting with a manager).",
            "customer_conversion_tracking_setting_enhanced_conversions_for_leads_enabled": "Whether enhanced conversions for leads is enabled.",
            "customer_conversion_tracking_setting_google_ads_conversion_customer": "Resource name of the account that owns the conversions this account reports.",
            "customer_remarketing_setting_google_global_site_tag": "The global site tag snippet for remarketing.",
        },
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
    "campaign_budget": {
        "description": "A campaign budget, including the daily amount, delivery method and Google's recommended budget.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/campaign_budget",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID the budget belongs to.",
            "customer_currency_code": "Three-letter ISO 4217 currency code of the account.",
            "campaign_budget_id": "Unique ID of the campaign budget. Join to campaign.campaign_budget.",
            "campaign_budget_name": "Name of the budget. Only explicitly shared budgets are required to have one.",
            "campaign_budget_amount_micros": "Average daily amount to spend, in micros, when the period is daily.",
            "campaign_budget_total_amount_micros": "Total amount to spend over the whole run, in micros, when the period is a custom period.",
            "campaign_budget_status": "Status of the budget (enabled or removed).",
            "campaign_budget_delivery_method": "Rate at which the budget is spent (standard or accelerated).",
            "campaign_budget_explicitly_shared": "Whether the budget was created to be shared across several campaigns.",
            "campaign_budget_reference_count": "Number of campaigns actively using the budget.",
            "campaign_budget_has_recommended_budget": "Whether Google has a recommended budget for this budget.",
            "campaign_budget_recommended_budget_amount_micros": "Google's recommended budget amount, in micros. Falls back to the current amount when there is no recommendation.",
            "campaign_budget_period": "Period the budget is spent over (daily or a custom period).",
            "campaign_budget_type": "Type of the budget (standard or Smart campaign).",
            "campaign_budget_aligned_bidding_strategy_id": "ID of the portfolio bidding strategy this shared budget is aligned with.",
        },
    },
    "bidding_strategy": {
        "description": "A portfolio bidding strategy shared across campaigns, including its targets and how many campaigns use it.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/bidding_strategy",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID the strategy belongs to.",
            "bidding_strategy_id": "Unique ID of the bidding strategy. Join to campaign.bidding_strategy.",
            "bidding_strategy_name": "Name of the bidding strategy, unique within the account.",
            "bidding_strategy_type": "Type of the strategy (e.g. target CPA, target ROAS, maximize conversions).",
            "bidding_strategy_status": "Status of the strategy (enabled or removed).",
            "bidding_strategy_currency_code": "Currency the strategy bids in, as an ISO 4217 three-letter code.",
            "bidding_strategy_effective_currency_code": "Currency actually used by the strategy, as an ISO 4217 three-letter code.",
            "bidding_strategy_campaign_count": "Number of campaigns attached to the strategy.",
            "bidding_strategy_non_removed_campaign_count": "Number of non-removed campaigns attached to the strategy.",
            "bidding_strategy_aligned_campaign_budget_id": "ID of the campaign budget this portfolio strategy is aligned with.",
            "bidding_strategy_target_cpa_target_cpa_micros": "Average cost-per-action target, in micros.",
            "bidding_strategy_target_cpa_cpc_bid_ceiling_micros": "Highest CPC bid the target CPA strategy may set, in micros.",
            "bidding_strategy_target_cpa_cpc_bid_floor_micros": "Lowest CPC bid the target CPA strategy may set, in micros.",
            "bidding_strategy_target_roas_target_roas": "Target return on ad spend: revenue per unit of spend.",
            "bidding_strategy_target_spend_target_spend_micros": "Spend target to maximize clicks under, in micros. Deprecated by Google in favour of the campaign budget.",
            "bidding_strategy_target_spend_cpc_bid_ceiling_micros": "Highest CPC bid the maximize clicks strategy may set, in micros.",
            "bidding_strategy_maximize_conversions_target_cpa_micros": "Target cost per conversion for a maximize conversions strategy, in micros.",
            "bidding_strategy_maximize_conversion_value_target_roas": "Target return on ad spend for a maximize conversion value strategy.",
            "bidding_strategy_target_impression_share_location": "Where on the search results page the strategy targets impressions.",
            "bidding_strategy_target_impression_share_location_fraction_micros": "Chosen share of ads to show in the targeted location, in micros (1% is 10,000).",
            "bidding_strategy_target_impression_share_cpc_bid_ceiling_micros": "Highest CPC bid the target impression share strategy may set, in micros.",
        },
    },
    "label": {
        "description": "A label that can be applied to campaigns, ad groups, ads and keywords for grouping and reporting.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/label",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID the label belongs to.",
            "label_id": "Unique ID of the label.",
            "label_name": "Name of the label.",
            "label_status": "Status of the label (enabled or removed).",
            "label_text_label_background_color": "Background color of the label, in hex format.",
            "label_text_label_description": "Short description of the label.",
        },
    },
    "audience": {
        "description": "An audience: a reusable targeting definition combining segments such as user lists, interests and demographics.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/audience",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID the audience belongs to.",
            "audience_id": "Unique ID of the audience.",
            "audience_name": "Name of the audience, unique within the account.",
            "audience_description": "Description of the audience.",
            "audience_scope": "Whether the audience is available account-wide or only to one asset group.",
            "audience_status": "Status of the audience (enabled or removed).",
            "audience_asset_group": "Resource name of the asset group the audience is scoped to, when the scope is asset group.",
            "audience_dimensions": "Positive dimensions making up the audience, as JSON.",
            "audience_exclusion_dimension": "Negative dimension excluded from the audience, as JSON.",
        },
    },
    "asset": {
        "description": "An individual asset (text, image, video, sitelink, callout and so on) that can be attached to campaigns, ad groups and ads.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/asset",
        "columns": {
            "customer_id": "The Google Ads customer (account) ID the asset belongs to.",
            "asset_id": "Unique ID of the asset.",
            "asset_name": "Optional name of the asset.",
            "asset_type": "Type of the asset (e.g. text, image, youtube video, sitelink, callout).",
            "asset_source": "Where the asset came from (advertiser-provided or automatically created).",
            "asset_final_urls": "Landing-page URLs the asset sends users to.",
            "asset_final_mobile_urls": "Mobile landing-page URLs the asset sends users to.",
            "asset_tracking_url_template": "URL template used to build a tracking URL for the asset.",
            "asset_policy_summary_approval_status": "Overall policy approval status of the asset.",
            "asset_policy_summary_review_status": "Where the asset is in Google's review process.",
            "asset_text_asset_text": "Text content, for text assets.",
            "asset_image_asset_file_size": "File size of the image, in bytes.",
            "asset_image_asset_mime_type": "MIME type of the image.",
            "asset_image_asset_full_size_url": "URL that returns the image at its full size.",
            "asset_image_asset_full_size_height_pixels": "Height of the image, in pixels.",
            "asset_image_asset_full_size_width_pixels": "Width of the image, in pixels.",
            "asset_youtube_video_asset_youtube_video_id": "YouTube video ID, the 11-character string from the video URL.",
            "asset_youtube_video_asset_youtube_video_title": "Title of the YouTube video.",
            "asset_callout_asset_callout_text": "Callout text, for callout assets.",
            "asset_sitelink_asset_link_text": "Display text of the sitelink.",
            "asset_sitelink_asset_description1": "First description line of the sitelink.",
            "asset_sitelink_asset_description2": "Second description line of the sitelink.",
            "asset_call_asset_phone_number": "Advertiser phone number, for call assets.",
            "asset_call_asset_country_code": "Two-letter country code of the phone number.",
            "asset_promotion_asset_promotion_code": "Code the user enters to qualify for the promotion.",
            "asset_structured_snippet_asset_header": "Header of the structured snippet.",
            "asset_structured_snippet_asset_values": "Values listed in the structured snippet.",
            "asset_mobile_app_asset_app_id": "Store ID of the promoted mobile app.",
            "asset_mobile_app_asset_app_store": "App store the promoted app is distributed on.",
            "asset_lead_form_asset_business_name": "Name of the business advertised on the lead form.",
            "asset_lead_form_asset_headline": "Headline of the lead form.",
        },
    },
    "age_range_stats": {
        "description": "Daily performance broken out by the age range of the user (age_range_view).",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/age_range_view",
        "columns": _stats_columns(
            **{
                "ad_group_criterion_criterion_id": "Criterion ID of the age range within the ad group.",
                "ad_group_criterion_age_range_type": "The age range bucket the metrics are reported for (e.g. 25-34, undetermined).",
                "ad_group_criterion_status": "Status of the age range criterion (enabled, paused, or removed).",
                "ad_group_criterion_bid_modifier": "Bid modifier applied to this age range.",
            }
        ),
    },
    "gender_stats": {
        "description": "Daily performance broken out by the gender of the user (gender_view).",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/gender_view",
        "columns": _stats_columns(
            **{
                "ad_group_criterion_criterion_id": "Criterion ID of the gender within the ad group.",
                "ad_group_criterion_gender_type": "The gender bucket the metrics are reported for (male, female, or undetermined).",
                "ad_group_criterion_status": "Status of the gender criterion (enabled, paused, or removed).",
                "ad_group_criterion_bid_modifier": "Bid modifier applied to this gender.",
            }
        ),
    },
    "detail_placement_stats": {
        "description": "Daily performance broken out by the individual placement (website, app, or YouTube channel) an ad ran on (detail_placement_view).",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/detail_placement_view",
        "columns": _stats_columns(
            **{
                "detail_placement_view_placement": "Automatic placement string, e.g. a website URL, a mobile app ID, or a YouTube video or channel ID.",
                "detail_placement_view_display_name": "Human-readable name of the placement: the website name, app name, or YouTube video or channel title.",
                "detail_placement_view_placement_type": "Type of the placement (website, mobile app, YouTube video, or YouTube channel).",
                "detail_placement_view_target_url": "URL of the placement, e.g. the website, the app store listing, or the YouTube video.",
                "detail_placement_view_group_placement_target_url": "URL of the group that contains the placement, e.g. the domain or the YouTube channel.",
            }
        ),
    },
    "landing_page_stats": {
        "description": "Daily performance broken out by the unexpanded final URL of the landing page ads sent users to (landing_page_view).",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/landing_page_view",
        "columns": _stats_columns(
            **{
                "landing_page_view_unexpanded_final_url": "The final URL as entered by the advertiser, before URL expansion.",
                "metrics_speed_score": "Google's 0-100 estimate of how fast the landing page loads on mobile, relative to other pages.",
                "metrics_mobile_friendly_clicks_percentage": "Percentage of mobile clicks that went to a mobile-friendly page.",
                "metrics_valid_accelerated_mobile_pages_clicks_percentage": "Percentage of clicks to a landing page that is a valid AMP page.",
            }
        ),
    },
    "user_location_stats": {
        "description": "Daily performance broken out by the country the user was physically in, regardless of the locations the campaign targets (user_location_view).",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/user_location_view",
        "columns": _stats_columns(
            **{
                "user_location_view_country_criterion_id": "Criterion ID of the country the user was physically located in.",
                "user_location_view_targeting_location": "Whether the location was one the campaign targets.",
            }
        ),
    },
    "location_stats": {
        "description": "Daily performance broken out by the location criteria a campaign targets (location_view).",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/location_view",
        "columns": _stats_columns(
            **{
                "campaign_criterion_criterion_id": "Criterion ID of the targeted location within the campaign.",
                "campaign_criterion_location_geo_target_constant": "Resource name of the targeted geo target constant.",
                "campaign_criterion_negative": "Whether the location is excluded rather than targeted.",
                "campaign_criterion_bid_modifier": "Bid modifier applied to this location.",
                "campaign_criterion_status": "Status of the location criterion (enabled, paused, or removed).",
            }
        ),
    },
    "product_group_stats": {
        "description": "Daily performance broken out by the product group nodes of a Shopping campaign's product partition tree (product_group_view).",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/product_group_view",
        "columns": _stats_columns(
            **{
                "ad_group_criterion_criterion_id": "Criterion ID of the product group node.",
                "ad_group_criterion_listing_group_type": "Type of the node: a subdivision that splits further, or a unit that can be bid on.",
                "ad_group_criterion_listing_group_parent_ad_group_criterion": "Resource name of the parent node in the product partition tree.",
                "ad_group_criterion_listing_group_case_value_product_item_id_value": "Product item ID the node splits on.",
                "ad_group_criterion_listing_group_case_value_product_brand_value": "Product brand the node splits on.",
                "ad_group_criterion_listing_group_case_value_product_condition_condition": "Product condition the node splits on (new, refurbished, or used).",
                "ad_group_criterion_listing_group_case_value_product_type_value": "Product type value the node splits on.",
                "ad_group_criterion_listing_group_case_value_product_type_level": "Level of the product type the node splits on.",
                "ad_group_criterion_listing_group_case_value_product_channel_channel": "Sales channel the node splits on (online or local).",
                "ad_group_criterion_negative": "Whether the node is excluded rather than bid on.",
                "ad_group_criterion_status": "Status of the product group criterion (enabled, paused, or removed).",
                "ad_group_criterion_cpc_bid_micros": "Maximum cost-per-click bid on the node, in micros.",
            }
        ),
    },
    "campaign_hourly_stats": {
        "description": "Hourly campaign performance, one row per campaign, day, hour, device and network. Use it for dayparting analysis.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/campaign",
        "columns": _stats_columns(
            **{
                "segments_hour": "Hour of day the metrics are reported for, as an integer from 0 to 23 in the account time zone.",
            }
        ),
    },
    "campaign_conversion_action_stats": {
        "description": "Daily campaign conversions broken out by conversion action. Only conversion metrics are available alongside this segmentation, so clicks, impressions and cost are not included.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/campaign",
        "columns": _stats_columns(
            **{
                "segments_conversion_action": "Resource name of the conversion action the conversions are attributed to. Join to conversion_action.",
                "segments_conversion_action_name": "Name of the conversion action.",
                "segments_conversion_action_category": "Category of the conversion action (e.g. purchase, lead, sign-up).",
                "metrics_cross_device_conversions": "Conversions where the conversion happened on a different device to the ad interaction.",
            }
        ),
    },
    "ad_group_conversion_action_stats": {
        "description": "Daily ad group conversions broken out by conversion action. Only conversion metrics are available alongside this segmentation, so clicks, impressions and cost are not included.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/ad_group",
        "columns": _stats_columns(
            **{
                "segments_conversion_action": "Resource name of the conversion action the conversions are attributed to. Join to conversion_action.",
                "segments_conversion_action_name": "Name of the conversion action.",
                "segments_conversion_action_category": "Category of the conversion action (e.g. purchase, lead, sign-up).",
                "metrics_cross_device_conversions": "Conversions where the conversion happened on a different device to the ad interaction.",
            }
        ),
    },
    "keyword_conversion_action_stats": {
        "description": "Daily keyword conversions broken out by conversion action. Only conversion metrics are available alongside this segmentation, so clicks, impressions and cost are not included.",
        "docs_url": "https://developers.google.com/google-ads/api/fields/v25/keyword_view",
        "columns": _stats_columns(
            **{
                "ad_group_criterion_criterion_id": "Unique ID of the keyword criterion the conversions belong to.",
                "segments_conversion_action": "Resource name of the conversion action the conversions are attributed to. Join to conversion_action.",
                "segments_conversion_action_name": "Name of the conversion action.",
                "segments_conversion_action_category": "Category of the conversion action (e.g. purchase, lead, sign-up).",
                "metrics_cross_device_conversions": "Conversions where the conversion happened on a different device to the ad interaction.",
            }
        ),
    },
}
