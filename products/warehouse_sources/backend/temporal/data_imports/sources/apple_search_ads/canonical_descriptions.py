"""Canonical, documentation-sourced descriptions for Apple Ads endpoints and columns.

Sourced from Apple's Ads Platform API reference
(https://developer.apple.com/documentation/apple-ads-platform-api) and the Campaign Management
API 5 reference it supersedes (https://developer.apple.com/documentation/apple_search_ads).
Keyed by the endpoint names in `settings.py`, which match the `ExternalDataSchema.name` of a
synced table. Both versions' column names are described here, because a source pinned to either
one syncs into the same table; columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Metrics shared by every reporting table, so the daily grain reads the same everywhere.
_REPORT_METRIC_COLUMNS: dict[str, str] = {
    "date": "Calendar day the metrics cover, in the organization's time zone.",
    "impressions": "Number of times the ad was shown on that day.",
    "taps": "Number of taps on the ad.",
    "installs": "Total conversions attributed to the ad, combining new downloads and redownloads.",
    "newDownloads": "Conversions from users who had not previously downloaded the app.",
    "redownloads": "Conversions from users who had previously downloaded the app.",
    "latOnInstalls": "Conversions from devices with Limit Ad Tracking enabled.",
    "latOffInstalls": "Conversions from devices with Limit Ad Tracking disabled.",
    "ttr": "Tap-through rate: taps divided by impressions.",
    "conversionRate": "Conversion rate: installs divided by taps.",
    "localSpend": "Amount spent on that day, as an amount plus currency code.",
    "avgCPA": "Average cost per acquisition, in the organization's currency.",
    "avgCPT": "Average cost per tap, in the organization's currency.",
    "avgCPM": "Average cost per thousand impressions, in the organization's currency.",
    # The Platform API renamed these two and split installs by attribution type.
    "cpt": "Average cost per tap, as an amount plus currency code.",
    "cpm": "Average cost per thousand impressions, as an amount plus currency code.",
    "tapInstalls": "Conversions attributed to a tap on the ad.",
    "viewInstalls": "Conversions attributed to an impression the user did not tap.",
    "totalInstalls": "Conversions attributed to the ad, combining tap-through and view-through.",
    "tapNewDownloads": "Tap-through conversions from users who had not downloaded the app before.",
    "tapRedownloads": "Tap-through conversions from users who had downloaded the app before.",
    "viewNewDownloads": "View-through conversions from users who had not downloaded the app before.",
    "viewRedownloads": "View-through conversions from users who had downloaded the app before.",
    "totalNewDownloads": "Conversions from users who had not downloaded the app before.",
    "totalRedownloads": "Conversions from users who had downloaded the app before.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "acls": {
        "description": "Ad accounts the API credentials can read, with the roles granted on each.",
        "docs_url": "https://developer.apple.com/documentation/apple-ads-platform-api/get-user-acls",
        "columns": {
            "id": "Identifier of the ad account, used as the `adAccountId` in the API context header.",
            "name": "Display name of the ad account.",
            "roles": "Roles the API user holds on the ad account, such as API Account Read Only.",
            "orgId": "Identifier of the organization the ad account belongs to.",
            "orgName": "Display name of the organization.",
            "currency": "Three-letter ISO currency code the organization is billed in.",
            "timeZone": "Time zone the organization's reporting is expressed in.",
            "paymentModel": "Billing model for the organization: LOC (line of credit), PAYG, or unset.",
            "roleNames": "Roles the API user holds on the organization, such as API Read Only.",
        },
    },
    "campaigns": {
        "description": "Campaigns in the organization, each targeting one app in one or more storefronts.",
        "docs_url": "https://developer.apple.com/documentation/apple_search_ads/campaign",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "orgId": "Identifier of the organization that owns the campaign.",
            "name": "Name of the campaign.",
            "adamId": "App Store identifier of the app the campaign promotes.",
            "budgetAmount": "Total budget for the campaign, as an amount plus currency code.",
            "dailyBudgetAmount": "Daily budget cap, as an amount plus currency code.",
            "countriesOrRegions": "Storefronts the campaign runs in, as country or region codes.",
            "adChannelType": "Channel the campaign advertises on, such as SEARCH or DISPLAY.",
            "supplySources": "App Store placements the campaign serves in, such as APPSTORE_SEARCH_RESULTS.",
            "billingEvent": "Event the campaign is billed on — TAPS for Search Ads campaigns.",
            "paymentModel": "Billing model in effect for the campaign.",
            "startTime": "When the campaign starts serving.",
            "endTime": "When the campaign stops serving, if an end is set.",
            "status": "Status the advertiser set: ENABLED or PAUSED.",
            "servingStatus": "Whether the campaign is currently RUNNING or NOT_RUNNING.",
            "servingStateReasons": "Reasons the campaign is not serving, if any.",
            "displayStatus": "Combined status shown in the Search Ads UI.",
            "modificationTime": "When the campaign was last changed.",
            "deleted": "Whether the campaign has been deleted.",
        },
    },
    "ad_groups": {
        "description": "Ad groups across every campaign in the organization, holding bids and targeting.",
        "docs_url": "https://developer.apple.com/documentation/apple_search_ads/adgroup",
        "columns": {
            "id": "Unique identifier for the ad group.",
            "campaignId": "Identifier of the campaign the ad group belongs to.",
            "orgId": "Identifier of the organization that owns the ad group.",
            "name": "Name of the ad group.",
            "defaultBidAmount": "Default cost-per-tap bid, as an amount plus currency code.",
            "cpaGoal": "Optional cost-per-acquisition goal, as an amount plus currency code.",
            "pricingModel": "Pricing model for the ad group, such as CPC.",
            "automatedKeywordsOptIn": "Whether Apple may add matching keywords automatically.",
            "targetingDimensions": "Audience, device, demographic and locality targeting for the ad group.",
            "startTime": "When the ad group starts serving.",
            "endTime": "When the ad group stops serving, if an end is set.",
            "status": "Status the advertiser set: ENABLED or PAUSED.",
            "servingStatus": "Whether the ad group is currently RUNNING or NOT_RUNNING.",
            "servingStateReasons": "Reasons the ad group is not serving, if any.",
            "displayStatus": "Combined status shown in the Search Ads UI.",
            "modificationTime": "When the ad group was last changed.",
            "deleted": "Whether the ad group has been deleted.",
        },
    },
    "keywords": {
        "description": "Targeting keywords across every ad group in the organization.",
        "docs_url": "https://developer.apple.com/documentation/apple_search_ads/keyword",
        "columns": {
            "id": "Unique identifier for the keyword.",
            "adGroupId": "Identifier of the ad group the keyword targets within.",
            "campaignId": "Identifier of the campaign the keyword belongs to.",
            "text": "The keyword text bid on.",
            "matchType": "How the search term must match the keyword: EXACT or BROAD.",
            "bidAmount": "Cost-per-tap bid for the keyword, as an amount plus currency code.",
            "status": "Status the advertiser set: ACTIVE or PAUSED.",
            "modificationTime": "When the keyword was last changed.",
            "deleted": "Whether the keyword has been deleted.",
        },
    },
    "campaign_report": {
        "description": "Daily performance metrics per campaign, one row per campaign per day.",
        "docs_url": "https://developer.apple.com/documentation/apple_search_ads/get_campaign-level_reports",
        "columns": {
            "campaignId": "Identifier of the campaign the metrics belong to.",
            "campaignName": "Name of the campaign at the time the report was run.",
            "campaignStatus": "Status of the campaign at the time the report was run.",
            "app": "App the campaign promotes, with its App Store identifier and name.",
            "countriesOrRegions": "Storefronts the campaign served in.",
            "deleted": "Whether the campaign has since been deleted.",
            **_REPORT_METRIC_COLUMNS,
        },
    },
    "ad_group_report": {
        "description": "Daily performance metrics per ad group, one row per ad group per day.",
        "docs_url": "https://developer.apple.com/documentation/apple_search_ads/get_ad_group-level_reports",
        "columns": {
            "campaignId": "Identifier of the campaign the ad group belongs to.",
            "adGroupId": "Identifier of the ad group the metrics belong to.",
            "adGroupName": "Name of the ad group at the time the report was run.",
            "adGroupStatus": "Status of the ad group at the time the report was run.",
            "defaultBidAmount": "Default cost-per-tap bid in effect for the ad group.",
            "deleted": "Whether the ad group has since been deleted.",
            **_REPORT_METRIC_COLUMNS,
        },
    },
    "keyword_report": {
        "description": "Daily performance metrics per targeting keyword, one row per keyword per day.",
        "docs_url": "https://developer.apple.com/documentation/apple_search_ads/get_keyword-level_reports",
        "columns": {
            "campaignId": "Identifier of the campaign the keyword belongs to.",
            "keywordId": "Identifier of the keyword the metrics belong to.",
            "keyword": "The keyword text bid on.",
            "matchType": "How the search term matched the keyword: EXACT or BROAD.",
            "adGroupId": "Identifier of the ad group the keyword targets within.",
            "adGroupName": "Name of the ad group at the time the report was run.",
            "bid": "Cost-per-tap bid in effect for the keyword.",
            "keywordStatus": "Status of the keyword at the time the report was run.",
            "keywordDisplayStatus": "Combined keyword status shown in the Search Ads UI.",
            "deleted": "Whether the keyword has since been deleted.",
            **_REPORT_METRIC_COLUMNS,
        },
    },
}
