from products.warehouse_sources.sources.sdk import CanonicalDescriptions
from products.warehouse_sources.sources.twitter_ads.settings import (
    CONVERSION_ATTRIBUTIONS,
    CONVERSION_METRICS,
    VIDEO_METRICS,
    conversion_column,
)

_VIDEO_DESCRIPTIONS = {
    "video_total_views": "Video views where the video was 100% in view for at least 3 seconds, plus views a user started by clicking play.",
    "video_views_25": "Video views that reached 25% of the video.",
    "video_views_50": "Video views that reached 50% of the video.",
    "video_views_75": "Video views that reached 75% of the video.",
    "video_views_100": "Video views that reached the end of the video.",
    "video_3s100pct_views": "Video views where at least 3 seconds played while the video was 100% in view, without click-to-play views. X's original view definition.",
    "video_6s_views": "Video views that lasted at least 6 seconds.",
    "video_15s_views": "Video views that lasted at least 15 seconds or 95% of the video.",
    "video_content_starts": "Video views where playback started.",
    "video_cta_clicks": "Clicks on the video's call to action.",
}

_CONVERSION_LABELS = {
    "conversion_purchases": "Purchase",
    "conversion_sign_ups": "Sign-up",
    "conversion_site_visits": "Site visit",
    "conversion_downloads": "Download",
    "conversion_custom": "Custom",
    "conversion_add_to_carts": "Add-to-cart",
    "conversion_checkouts_initiated": "Checkout",
    "conversion_content_views": "Content view",
    "conversion_payment_info_additions": "Payment info",
    "conversion_add_to_wishlists": "Add-to-wishlist",
    "conversion_searches": "Search",
    "conversion_landing_page_views": "Landing page view",
    "conversion_subscriptions": "Subscription",
}

_ATTRIBUTION_SUFFIXES = {
    "metric": "attributed to the ad",
    "post_view": "after a user viewed the ad without engaging",
    "post_engagement": "after a user engaged with the ad",
    "assisted": "the ad assisted, as reported by X",
}

# Indexing by the settings tuples makes import fail when a synced column has no description.
_METRIC_DESCRIPTIONS = {
    **{key: _VIDEO_DESCRIPTIONS[key] for key in VIDEO_METRICS},
    **{
        conversion_column(metric, attribution): (
            f"{_CONVERSION_LABELS[metric]} website conversions {_ATTRIBUTION_SUFFIXES[attribution]}."
        )
        for metric in CONVERSION_METRICS
        for attribution in CONVERSION_ATTRIBUTIONS
    },
}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "An X advertising campaign containing line items and funded by a funding instrument.",
        "docs_url": "https://docs.x.com/x-ads-api/campaign-management/reference#campaigns",
        "columns": {
            "id": "Campaign identifier.",
            "funding_instrument_id": "Funding instrument that supplies the campaign's budget and billing currency.",
            "name": "Campaign name.",
            "deleted": "Whether the campaign has been deleted.",
        },
    },
    "line_items": {
        "description": "An ad group within an X campaign, with its objective, targeting, and bid settings.",
        "docs_url": "https://docs.x.com/x-ads-api/campaign-management/reference#line-items",
        "columns": {
            "id": "Line item identifier.",
            "campaign_id": "Parent campaign identifier.",
            "objective": "Advertising objective.",
        },
    },
    "promoted_tweets": {
        "description": "An association between an X Post and the line item that promotes it.",
        "docs_url": "https://docs.x.com/x-ads-api/campaign-management/reference#promoted-tweets",
        "columns": {
            "id": "Promoted Post identifier.",
            "tweet_id": "Identifier of the promoted Post.",
            "line_item_id": "Line item that promotes the Post.",
        },
    },
    "funding_instruments": {
        "description": "A payment or credit arrangement funding X advertising campaigns.",
        "docs_url": "https://docs.x.com/x-ads-api/campaign-management/reference#funding-instruments",
        "columns": {
            "id": "Funding instrument identifier.",
            "currency": "ISO 4217 billing currency.",
            "type": "Funding instrument type.",
        },
    },
    "media_creatives": {
        "description": "A media creative associated with an X advertising line item.",
        "docs_url": "https://docs.x.com/x-ads-api/campaign-management/reference#media-creatives",
        "columns": {"id": "Media creative identifier.", "line_item_id": "Line item that promotes the creative."},
    },
    "lead_forms": {
        "description": "A native lead form that Lead Gen ads attach to a card to collect leads.",
        "docs_url": "https://docs.x.com/x-ads-api/lead-generation/reference#lead-forms",
        "columns": {
            "id": "Lead form identifier (UUID).",
            "name": "Form name.",
            "purpose": "What the collected leads are used for.",
            "fields": "Fields the lead fills in, each with a key such as EMAIL and whether it is optional.",
            "privacy_policy": "Privacy policy URL and company name of the advertiser collecting the leads.",
            "deleted": "Whether the lead form has been archived.",
        },
    },
    **{
        table: {
            "description": f"Daily unsegmented X advertising metrics for a {entity}, separated by placement.",
            "docs_url": "https://docs.x.com/x-ads-api/analytics",
            "columns": {
                "entity_id": f"Identifier of the {entity} whose metrics are reported.",
                "date": "Report day in the ad account's reporting timezone.",
                "placement": "Advertising placement for these metrics.",
                "billed_charge_local_micro": "Billed spend in millionths of the funding instrument's currency.",
                "currency": "ISO 4217 billing currency from the campaign's funding instrument.",
                "impressions": "Number of times the ad was served.",
                "clicks": "Total clicks, including favorites and other engagements.",
                **_METRIC_DESCRIPTIONS,
            },
        }
        for table, entity in (("campaign_stats", "campaign"), ("line_item_stats", "line item"))
    },
}
