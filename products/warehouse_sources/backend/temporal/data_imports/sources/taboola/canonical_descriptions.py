"""Canonical, documentation-sourced descriptions for Taboola endpoints and columns.

Sourced from the official Taboola Backstage API reference (https://developers.taboola.com/backstage-api).
Keyed by the endpoint names in `settings.py` `TABOOLA_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Taboola table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "An advertising campaign in your Taboola account, with its budget, schedule, and targeting.",
        "docs_url": "https://developers.taboola.com/backstage-api/reference/list-campaigns",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "advertiser_id": "ID of the advertiser account that owns the campaign.",
            "name": "The campaign's name.",
            "status": "Status of the campaign (e.g. RUNNING, PAUSED, PENDING_APPROVAL, TERMINATED).",
            "is_active": "Whether the campaign is currently active.",
            "spending_limit": "Total spending limit configured for the campaign.",
            "spending_limit_model": "How the spending limit is applied (e.g. ENTIRE, MONTHLY).",
            "daily_cap": "Maximum amount the campaign can spend per day.",
            "cpc": "Cost-per-click bid for the campaign.",
            "bid_type": "Bidding strategy used by the campaign (e.g. FIXED, MAX_CONVERSIONS).",
            "marketing_objective": "The campaign's marketing objective (e.g. LEADS_GENERATION, BRAND_AWARENESS).",
            "start_date": "Date the campaign starts running.",
            "end_date": "Date the campaign stops running, if set.",
            "pricing_model": "Pricing model for the campaign (e.g. CPC, CPM).",
            "branding_text": "Branding text shown alongside the campaign's items.",
        },
    },
    "campaign_items": {
        "description": "A single promoted item (ad creative) within a Taboola campaign.",
        "docs_url": "https://developers.taboola.com/backstage-api/reference/list-campaign-items",
        "columns": {
            "id": "Unique identifier for the campaign item.",
            "campaign_id": "ID of the campaign this item belongs to.",
            "type": "Type of the item (e.g. ITEM, RSS_CHILD).",
            "url": "Landing page URL the item links to.",
            "thumbnail_url": "URL of the item's thumbnail image.",
            "title": "The item's headline text.",
            "status": "Status of the item (e.g. RUNNING, PAUSED, PENDING, REJECTED).",
            "is_active": "Whether the item is currently active.",
            "approval_state": "Editorial approval state of the item (e.g. APPROVED, PENDING, REJECTED).",
            "cpc": "Cost-per-click bid override for this item, if set.",
        },
    },
    "conversion_rules": {
        "description": "A conversion rule defined on your Taboola universal pixel for tracking advertiser conversions.",
        "docs_url": "https://developers.taboola.com/backstage-api/reference/list-conversion-rules",
        "columns": {
            "id": "Unique identifier for the conversion rule.",
            "display_name": "Human-readable name of the conversion rule.",
            "status": "Status of the conversion rule (e.g. ACTIVE, INACTIVE).",
            "category": "Conversion category (e.g. LEAD, PURCHASE, SIGN_UP).",
            "type": "How the conversion is counted (e.g. EVENT_BASED, URL_BASED).",
            "include_in_total_conversions": "Whether this rule contributes to total conversion reporting.",
            "look_back_window": "Click-through attribution window, in days.",
            "view_look_back_window": "View-through attribution window, in days.",
        },
    },
    "campaign_summary_by_day": {
        "description": "Daily performance metrics broken down per campaign and date.",
        "docs_url": "https://developers.taboola.com/backstage-api/reference/campaign-summary-report",
        "columns": {
            "date": "Date the metrics are reported for.",
            "campaign": "ID of the campaign the metrics belong to.",
            "campaign_name": "Name of the campaign the metrics belong to.",
            "impressions": "Number of times the campaign's items were shown.",
            "clicks": "Number of clicks on the campaign's items.",
            "spent": "Amount spent by the campaign on this date.",
            "ctr": "Click-through rate (clicks divided by impressions).",
            "cpc": "Average cost per click on this date.",
            "cpm": "Average cost per thousand impressions on this date.",
            "conversions_value": "Total monetary value of conversions attributed on this date.",
            "cpa": "Average cost per acquisition (conversion) on this date.",
            "cpa_conversion_rate": "Conversion rate for the date.",
            "currency": "Currency the monetary metrics are reported in.",
        },
    },
    "top_campaign_content": {
        "description": "Aggregate performance of the top-performing campaign items over the requested window.",
        "docs_url": "https://developers.taboola.com/backstage-api/reference/top-campaign-content-report",
        "columns": {
            "campaign": "ID of the campaign the item belongs to.",
            "item": "ID of the promoted item.",
            "item_name": "Headline text of the promoted item.",
            "content_provider_name": "Name of the content provider for the item.",
            "thumbnail_url": "URL of the item's thumbnail image.",
            "url": "Landing page URL the item links to.",
            "impressions": "Number of times the item was shown.",
            "clicks": "Number of clicks on the item.",
            "spent": "Amount spent on the item over the window.",
            "ctr": "Click-through rate for the item.",
            "cpc": "Average cost per click for the item.",
            "currency": "Currency the monetary metrics are reported in.",
        },
    },
}
