"""Canonical, documentation-sourced descriptions for Reddit Ads endpoints and columns.

Sourced from the official Reddit Ads API reference (https://ads-api.reddit.com/docs/v3/).
Keyed by the endpoint names in `settings.py` `REDDIT_ADS_CONFIG`, which match the
`ExternalDataSchema.name` of a synced Reddit Ads table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by Reddit Ads entity objects (campaigns, ad groups, ads).
_ENTITY_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "modified_at": "Time at which the object was last modified.",
    "name": "The object's name.",
    "configured_status": "The status configured by the advertiser (e.g. ACTIVE, PAUSED).",
    "effective_status": "The object's effective status after all rules are applied.",
}

# Fields shared by the report endpoints, which return aggregated metrics per breakdown.
_REPORT_COLUMNS = {
    "date": "The date the metrics are aggregated over.",
    "currency": "Three-letter ISO currency code for monetary metrics.",
    "impressions": "Number of times ads were shown.",
    "clicks": "Number of clicks on ads.",
    "spend": "Total amount spent, in the smallest currency unit.",
    "ctr": "Click-through rate (clicks divided by impressions).",
    "cpc": "Average cost per click.",
    "ecpm": "Effective cost per thousand impressions.",
    "reach": "Estimated number of unique users who saw the ads.",
    "frequency": "Average number of times each user saw the ads.",
    "conversion_roas": "Return on ad spend from conversions.",
    "conversion_purchase_total_items": "Total number of items purchased from conversions.",
    "conversion_purchase_total_value": "Total value of purchase conversions.",
    "conversion_purchase_total_value_all": "Total value of purchase conversions across all attribution windows (click and view-through).",
    "conversion_sign_up_views": "Number of sign-up view conversions.",
    "conversion_signup_total_value": "Total value of sign-up conversions.",
    "app_install_install_count": "Number of app installs attributed to ads.",
    "app_install_purchase_count": "Number of in-app purchases attributed to ads.",
    "app_install_revenue": "Revenue from app-install-attributed purchases.",
    "app_install_roas_double": "Return on ad spend from app installs.",
    "key_conversion_rate": "Rate of the key conversion event.",
    "key_conversion_total_count": "Total count of the key conversion event.",
    "video_started": "Number of video views started.",
    "video_view_rate": "Rate at which the video was viewed.",
    "video_completion_rate": "Rate at which the video was watched to completion.",
    "video_watched_25_percent": "Number of times the video was watched to 25%.",
    "video_watched_50_percent": "Number of times the video was watched to 50%.",
    "video_watched_75_percent": "Number of times the video was watched to 75%.",
    "video_watched_100_percent": "Number of times the video was watched to 100%.",
}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "A Reddit Ads campaign grouping ad groups under a shared objective and budget.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Get%20Campaigns",
        "columns": {
            **_ENTITY_COLUMNS,
            "objective": "The campaign's advertising objective (e.g. CONVERSIONS, TRAFFIC).",
            "spend_cap": "Lifetime spend cap for the campaign, if set.",
            "funding_instrument_id": "ID of the funding instrument paying for the campaign.",
        },
    },
    "ad_groups": {
        "description": "A Reddit Ads ad group within a campaign, defining targeting, bidding, and budget.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Get%20Ad%20Groups",
        "columns": {
            **_ENTITY_COLUMNS,
            "campaign_id": "ID of the campaign this ad group belongs to.",
            "bid_strategy": "The bidding strategy used by the ad group.",
            "bid_value": "The bid value for the ad group.",
            "goal_type": "The optimization goal type for the ad group.",
            "goal_value": "The optimization goal value for the ad group.",
            "start_time": "Time at which the ad group is scheduled to start.",
            "end_time": "Time at which the ad group is scheduled to end.",
        },
    },
    "ads": {
        "description": "A Reddit Ads ad — the creative shown to users within an ad group.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Get%20Ads",
        "columns": {
            **_ENTITY_COLUMNS,
            "ad_group_id": "ID of the ad group this ad belongs to.",
            "type": "The ad's creative type.",
            "click_url": "The destination URL users are sent to when clicking the ad.",
            "preview_url": "URL to preview the ad creative.",
            "post_id": "ID of the Reddit post backing the ad creative.",
        },
    },
    "campaign_report": {
        "description": "Daily aggregated performance metrics broken down by campaign.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "campaign_id": "ID of the campaign the metrics are aggregated for.",
        },
    },
    "ad_group_report": {
        "description": "Daily aggregated performance metrics broken down by ad group.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "ad_group_id": "ID of the ad group the metrics are aggregated for.",
        },
    },
    "ad_report": {
        "description": "Daily aggregated performance metrics broken down by ad.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "ad_id": "ID of the ad the metrics are aggregated for.",
        },
    },
    "ad_account": {
        "description": "The connected Reddit Ads account, including the currency and time zone every spend figure is reported in.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/api/get-ad-account",
        "columns": {
            "id": "The ad account ID.",
            "name": "The ad account name.",
            "currency": "The currency the ad account is billed and reported in.",
            "time_zone_id": "The time zone the ad account reports in.",
            "type": "The ad account type. Can only be changed by Reddit.",
            "business_id": "ID of the business that owns the ad account.",
            "admin_approval": "The approval state of the account. Can only be changed by Reddit.",
            "attribution_type": "The attribution conversion type used for cost-per-action bidding and reporting.",
            "click_attribution_window": "The window for click attributions, used in reporting.",
            "view_attribution_window": "The window for view attributions, used in reporting.",
            "app_attribution_type": "The attribution conversion type used for app-install campaigns.",
            "app_click_attribution_window": "The window for app-install click attributions.",
            "app_view_attribution_window": "The window for app-install view attributions.",
            "spend_cap_type": "The spend cap type applied to the ad account.",
            "suspension_reason": "Why the ad account was suspended, if it was.",
            "primary_contact_member_id": "ID of the member listed as the account's primary contact.",
            "excluded_communities": "Communities (subreddits) excluded at the ad account level.",
            "excluded_keywords": "Keywords excluded at the ad account level.",
            "pixel_partner_preferences": "Pixel partners allowed by the advertiser.",
            "created_at": "When the ad account was created.",
            "modified_at": "When the ad account was last changed.",
        },
    },
    "custom_audiences": {
        "description": "An audience built from advertiser-supplied data: a customer list, website or app retargeting via a Pixel, engagement retargeting, or a lookalike.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/api/list-user-custom-audiences",
        "columns": {
            "id": "The custom audience ID.",
            "name": "The custom audience name.",
            "type": "The custom audience type.",
            "status": "The audience's processing status. Only VALID once at least 1,000 users match.",
            "ad_account_id": "ID of the ad account that owns this custom audience.",
            "business_id": "ID of the business that owns this custom audience.",
            "size_range_lower": "Lower bound of the estimated matched users for this audience.",
            "size_range_upper": "Upper bound of the estimated matched users for this audience.",
            "delivery_status": "The delivery statuses for this audience.",
            "customer_list_config": "Details for a customer list audience.",
            "pixel_audience_config": "Details for a website retargeting audience.",
            "engagement_audience_config": "Details for an engagement retargeting audience.",
            "lookalike_config": "Details for a lookalike audience.",
            "cost": "Cost information for audiences sourced from third-party data providers.",
            "created_at": "When the audience was created.",
            "modified_at": "When the audience was last changed.",
        },
    },
    "saved_audiences": {
        "description": "A reusable targeting definition that ad groups can point at instead of redefining targeting each time.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/api/list-saved-audiences",
        "columns": {
            "id": "The saved audience ID.",
            "name": "The saved audience name.",
            "type": "The saved audience type.",
            "status": "The saved audience status.",
            "ad_account_id": "The ad account ID.",
            "targeting": "The targeting definition this saved audience applies.",
            "active_ad_groups_count": "Number of active ad groups using this saved audience.",
            "size_range_lower": "Lower bound of the audience's predicted impressions.",
            "size_range_upper": "Upper bound of the audience's predicted impressions.",
            "delivery_status": "The delivery statuses for this saved audience.",
            "created_at": "When the saved audience was created.",
            "updated_at": "When the saved audience was last updated.",
        },
    },
    "pixels": {
        "description": "A Reddit Pixel, the conversion tracker that reports website events back to Reddit Ads.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/api/list-pixels-by-ad-account",
        "columns": {
            "id": "The Pixel ID.",
            "name": "The Pixel's human-readable name.",
            "business_id": "ID of the business that owns the Pixel.",
            "automatic_matching_config": "The Pixel's automated advanced matching settings.",
            "enhanced_signal_collection_config": "The Pixel's enhanced signal collection settings.",
            "created_by": "ID of the member who created the Pixel.",
            "modified_by": "ID of the member who last modified the Pixel.",
            "created_at": "When the Pixel was created.",
            "modified_at": "When the Pixel was last changed.",
        },
    },
    "funding_instruments": {
        "description": "A payment source campaigns bill against, carrying the currency spend is denominated in.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/api/list-funding-instruments",
        "columns": {
            "id": "The funding instrument ID.",
            "name": "The funding instrument's name.",
            "currency": "The currency used in this invoice (ISO 4217).",
            "credit_limit": "The maximum amount this funding instrument can spend before linked campaigns stop running.",
            "billable_amount": "The funding instrument's current outstanding debt, in local microcurrency.",
            "is_servable": "Whether campaigns linked to this funding instrument are allowed to run.",
            "reasons_not_servable": "Why this funding instrument is not servable. Empty when it is servable.",
            "authorize_status": "The state of the credit card attachment. Only applies to CREDIT_CARD funding instruments.",
            "invoice_group_status": "Eligibility or issues with the invoice group.",
            "start_time": "Campaigns using this funding instrument will not deliver until this time.",
            "end_time": "Campaigns using this funding instrument will not deliver after this time.",
        },
    },
    "lead_gen_forms": {
        "description": "A lead generation form users fill in from an ad, defining the questions asked and the privacy policy shown.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/api/list-lead-gen-forms",
        "columns": {
            "id": "The form's ID.",
            "name": "The form's name. Shown only in the Ads Manager.",
            "ad_account_id": "The ad account ID.",
            "prompt": "The text shown at the top of the form and beside the ad's call to action.",
            "privacy_link": "The privacy policy URL shown on the form.",
            "questions": "The list of questions the user fills out.",
            "created_at": "When the form was created.",
            "modified_at": "When the form was last changed.",
        },
    },
    "profiles": {
        "description": "A Reddit profile the ad account can publish ads from. Ad and post rows reference it by ID.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/api/list-profiles-by-ad-account",
        "columns": {
            "id": "The profile ID.",
            "name": "The profile's Reddit username.",
            "reddit_user_id": "The profile's Reddit user ID.",
            "business_id": "ID of the business associated with this profile.",
            "modified_at": "When the profile was last changed.",
        },
    },
    "structured_posts": {
        "description": "The post backing an ad's creative, carrying the headline, media, and destination the ad actually showed. Join to ads on `post_id` to attribute performance to a creative.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/api/list-structured-posts",
        "columns": {
            "id": "The post ID. Matches an ad's `post_id`.",
            "profile_id": "ID of the profile the post belongs to.",
            "url": "The post URL.",
            "creative": "The creative payload: type, headline, media, and click destination.",
            "allow_comments": "Whether comments are allowed on the post.",
            "created_at": "When the post was created.",
        },
    },
    "campaign_country_report": {
        "description": "Daily campaign performance metrics broken down by the country the impression was served in.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "campaign_id": "ID of the campaign the metrics are aggregated for.",
            "country": "The targeted country.",
        },
    },
    "campaign_gender_report": {
        "description": "Daily campaign performance metrics broken down by the viewer's gender.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "campaign_id": "ID of the campaign the metrics are aggregated for.",
            "gender": "The user's gender.",
        },
    },
    "campaign_placement_report": {
        "description": "Daily campaign performance metrics broken down by where on Reddit the creative was placed.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "campaign_id": "ID of the campaign the metrics are aggregated for.",
            "placement": "Where the creative was placed.",
        },
    },
    "campaign_community_report": {
        "description": "Daily campaign performance metrics broken down by the community (subreddit) the ad ran in.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "campaign_id": "ID of the campaign the metrics are aggregated for.",
            "community": "The targeted community (subreddit).",
        },
    },
    "campaign_os_type_report": {
        "description": "Daily campaign performance metrics broken down by the viewer's device operating system.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "campaign_id": "ID of the campaign the metrics are aggregated for.",
            "os_type": "The device operating system type.",
        },
    },
    "campaign_keyword_report": {
        "description": "Daily campaign performance metrics broken down by the keyword the ad was matched on.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "campaign_id": "ID of the campaign the metrics are aggregated for.",
            "keyword": "The targeted keyword the impression was matched on.",
        },
    },
}
