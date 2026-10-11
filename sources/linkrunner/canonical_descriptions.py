"""Canonical, documentation-sourced descriptions for Linkrunner endpoints and columns.

Sourced from the official Linkrunner API reference (https://docs.linkrunner.io/api-reference/data-apis).
Keyed by the endpoint names in `settings.py` `LINKRUNNER_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Linkrunner table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "All campaigns configured in your Linkrunner account, including their tracking links and store listings.",
        "docs_url": "https://docs.linkrunner.io/api-reference/data-apis",
        "columns": {
            "display_id": "The campaign's unique display identifier, used across the Linkrunner API.",
            "name": "Human-readable campaign name.",
            "created_at": "Time at which the campaign was created (ISO 8601).",
            "update_at": "Time at which the campaign was last updated (ISO 8601).",
            "google": "Whether the campaign is linked to a Google Ads source.",
            "meta": "Whether the campaign is linked to a Meta (Facebook/Instagram) Ads source.",
            "meta_campaign_id": "The associated Meta campaign identifier, if any.",
            "meta_web_to_app": "Whether the campaign uses Meta's web-to-app flow.",
            "active": "Whether the campaign is currently active.",
            "default_link": "The default deep link for the campaign.",
            "attributed_users": "Count of users attributed to the campaign.",
            "link": "The campaign's tracking link.",
            "shareable_link": "A shareable version of the campaign's link.",
            "domain": "The domain used for the campaign's links.",
            "store_listings": "Store listings (App Store / Play Store configurations) attached to the campaign.",
        },
    },
    "attributed_users": {
        "description": "Users attributed to a campaign, with attribution metadata, ad-network details, and device data.",
        "docs_url": "https://docs.linkrunner.io/api-reference/data-apis",
        "columns": {
            "campaign_display_id": "Display identifier of the campaign the user was attributed to.",
            "campaign_name": "Name of the campaign the user was attributed to.",
            "attributed_at": "Time at which the user was attributed to the campaign (ISO 8601).",
            "installed_at": "Time at which the app was installed (ISO 8601).",
            "store_click_at": "Time at which the store listing was clicked (ISO 8601).",
            "ad_channel": "The ad channel that drove the attribution (e.g. Google, Meta).",
            "link": "The tracking link the user came through.",
            "meta_ad_id": "Meta ad identifier associated with the attribution.",
            "ad_creative_id": "Identifier of the ad creative.",
            "ad_creative_name": "Name of the ad creative.",
            "ad_set_id": "Identifier of the ad set.",
            "ad_set_name": "Name of the ad set.",
            "publisher_platform": "The publisher platform where the ad was shown.",
            "platform_position": "The position/placement of the ad on the platform.",
            "user_id": "Linkrunner user identifier (lifted from the nested user_data object).",
            "user_name": "Name provided for the attributed user.",
            "user_email": "Email provided for the attributed user.",
            "user_phone": "Phone number provided for the attributed user.",
            "device_data": "Device metadata for the attributed user (brand, OS, device id, etc.).",
        },
    },
    "reporting_campaigns": {
        "description": "Campaign-level performance metrics from the Reporting API: clicks, installs, signups, spend, revenue, ROAS, ad sets, ad creatives, and keywords.",
        "docs_url": "https://docs.linkrunner.io/api-reference/reporting-campaigns",
        "columns": {
            "id": "Numeric unique identifier for the campaign.",
            "display_id": "The campaign's unique display identifier.",
            "name": "Human-readable campaign name.",
            "created_at": "Time at which the campaign was created (ISO 8601).",
        },
    },
}
