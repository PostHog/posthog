"""Canonical, documentation-sourced descriptions for Amazon Ads endpoints and columns.

Sourced from the official Amazon Ads API reference (https://advertising.amazon.com/API/docs/en-us/).
Keyed by the endpoint names in `settings.py` `AMAZON_ADS_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Amazon Ads table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "profiles": {
        "description": "An advertising profile representing an account in a specific marketplace/region.",
        "docs_url": "https://advertising.amazon.com/API/docs/en-us/reference/2/profiles",
        "columns": {
            "profileId": "Unique identifier for the advertising profile.",
            "countryCode": "Two-letter ISO country code of the marketplace the profile belongs to.",
            "currencyCode": "Three-letter ISO currency code used for the profile's spend.",
            "timezone": "Time zone configured for the profile.",
            "marketplaceStringId": "Identifier of the Amazon marketplace the profile is registered in.",
            "dailyBudget": "Default daily budget for the profile, if set.",
            "accountInfo": "Account metadata, including the account type (seller, vendor, agency) and name.",
        },
    },
    "sp_campaigns": {
        "description": "A Sponsored Products campaign that groups ad groups under a budget and targeting strategy.",
        "docs_url": "https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod#tag/Campaigns",
        "columns": {
            "campaignId": "Unique identifier for the campaign.",
            "name": "Name of the campaign.",
            "state": "Current state of the campaign: enabled, paused, or archived.",
            "budget": "Budget configuration for the campaign, including amount and budget type.",
            "targetingType": "Targeting strategy of the campaign: manual or auto.",
            "startDate": "Date the campaign starts running.",
            "endDate": "Date the campaign stops running, if set.",
            "dynamicBidding": "Dynamic bidding strategy and placement bid adjustments for the campaign.",
            "portfolioId": "Identifier of the portfolio the campaign belongs to, if any.",
        },
    },
    "sp_ad_groups": {
        "description": "A Sponsored Products ad group within a campaign, grouping ads and keywords under a default bid.",
        "docs_url": "https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod#tag/Ad-groups",
        "columns": {
            "adGroupId": "Unique identifier for the ad group.",
            "campaignId": "Identifier of the campaign the ad group belongs to.",
            "name": "Name of the ad group.",
            "state": "Current state of the ad group: enabled, paused, or archived.",
            "defaultBid": "Default bid applied to targets in the ad group, in the profile's currency.",
        },
    },
}
