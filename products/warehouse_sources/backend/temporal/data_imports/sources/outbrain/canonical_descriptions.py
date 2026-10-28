"""Canonical, documentation-sourced descriptions for Outbrain Amplify endpoints and columns.

Sourced from the official Outbrain Amplify API reference (https://amplifyv01.docs.apiary.io/).
Keyed by the endpoint names in `settings.py` `OUTBRAIN_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Outbrain table. Report endpoints carry synthetic
identifier columns (`_marketer_id`, `_date`) injected by the transport. Columns absent here fall
back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Performance metrics shared by the Amplify report endpoints.
_REPORT_METRICS = {
    "impressions": "Number of times the promoted content was shown.",
    "clicks": "Number of clicks on the promoted content.",
    "spend": "Amount spent over the reporting window.",
    "ecpc": "Effective cost per click over the reporting window.",
    "ctr": "Click-through rate (clicks divided by impressions).",
    "conversions": "Number of conversions attributed over the reporting window.",
    "conversionRate": "Conversion rate (conversions divided by clicks).",
    "cpa": "Cost per acquisition (spend divided by conversions).",
    "currency": "Three-letter ISO currency code the monetary metrics are reported in.",
}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "marketers": {
        "description": "An Outbrain Amplify marketer (advertiser account) that owns campaigns.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/marketers",
        "columns": {
            "id": "Unique identifier for the marketer.",
            "name": "The marketer's name.",
            "currency": "Three-letter ISO currency code the marketer's account bills in.",
            "enabled": "Whether the marketer account is enabled.",
            "creationTime": "Time at which the marketer account was created.",
            "lastModified": "Time at which the marketer account was last modified.",
            "blockedSiteFateMessage": "Status message for blocked-site policy, if applicable.",
        },
    },
    "campaigns": {
        "description": "An advertising campaign run by a marketer, with budget, bidding, and targeting.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/campaigns",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "name": "The campaign's name.",
            "_marketer_id": "ID of the marketer that owns the campaign (injected during sync).",
            "enabled": "Whether the campaign is enabled.",
            "budget": "The budget object associated with the campaign.",
            "cpc": "Cost-per-click bid for the campaign.",
            "autoArchived": "Whether the campaign was automatically archived.",
            "status": "Current status of the campaign (e.g. RUNNING, PAUSED, PENDING).",
            "objective": "The campaign's objective (e.g. traffic, conversions).",
            "creationTime": "Time at which the campaign was created.",
            "lastModified": "Time at which the campaign was last modified.",
            "startDate": "Date the campaign is scheduled to start.",
            "endDate": "Date the campaign is scheduled to end, if set.",
        },
    },
    "budgets": {
        "description": "A spending budget shared across one or more of a marketer's campaigns.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/budgets",
        "columns": {
            "id": "Unique identifier for the budget.",
            "name": "The budget's name.",
            "_marketer_id": "ID of the marketer that owns the budget (injected during sync).",
            "amount": "Total budget amount.",
            "currency": "Three-letter ISO currency code of the budget amount.",
            "amountSpent": "Amount of the budget already spent.",
            "amountRemaining": "Amount of the budget remaining.",
            "type": "Budget renewal type (e.g. CAMPAIGN, MONTHLY).",
            "pacing": "Pacing mode for spending the budget (e.g. SPEND_ASAP, AUTOMATIC).",
            "startDate": "Date the budget becomes active.",
            "endDate": "Date the budget expires, if set.",
            "runForever": "Whether the budget has no end date.",
        },
    },
    "promoted_links": {
        "description": "A piece of promoted content (ad creative) within a campaign.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/promoted-links",
        "columns": {
            "id": "Unique identifier for the promoted link.",
            "_campaign_id": "ID of the campaign the promoted link belongs to (injected during sync).",
            "text": "Headline text of the promoted link.",
            "url": "Destination URL the promoted link points to.",
            "siteName": "Display name of the site the content is promoted from.",
            "imageUrl": "URL of the promoted link's image.",
            "enabled": "Whether the promoted link is enabled.",
            "status": "Approval/serving status of the promoted link.",
            "creationTime": "Time at which the promoted link was created.",
            "lastModified": "Time at which the promoted link was last modified.",
            "cachedImageUrl": "URL of the cached version of the promoted link's image.",
        },
    },
    "conversion_events": {
        "description": "A conversion event (pixel or URL rule) defined by a marketer. Resolves the conversion ids in report conversion details.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/multiple-conversions",
        "columns": {
            "id": "Unique identifier for the conversion event.",
            "_marketer_id": "ID of the marketer that owns the conversion event (injected during sync).",
            "marketerId": "ID of the marketer that owns the conversion event.",
            "name": "The conversion event's name.",
            "type": "How the conversion is detected (e.g. URL_BASED, EVENT_BASED).",
            "category": "Conversion category (e.g. PURCHASE).",
            "enabled": "Whether the conversion event is enabled.",
            "trackingStatus": "Whether the conversion event is currently receiving data (ACTIVE or INACTIVE).",
            "conversionWindow": "Number of days after a click in which a conversion is attributed.",
            "includeInConversions": "Whether the event counts toward the reported conversions metric.",
            "url": "URL rule that triggers a URL_BASED conversion.",
            "creationTime": "Time at which the conversion event was created.",
            "lastModified": "Time at which the conversion event was last modified.",
        },
    },
    "segments": {
        "description": "An audience segment (pixel-based or campaign clickers) defined by a marketer, including archived segments. Resolves the segment ids used in campaign targeting.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/segments",
        "columns": {
            "id": "Unique identifier for the segment.",
            "_marketer_id": "ID of the marketer that owns the segment (injected during sync).",
            "marketerId": "ID of the marketer that owns the segment.",
            "name": "The segment's name.",
            "description": "The segment's description.",
            "segmentType": "How segment membership is built (PIXEL or CLICKERS).",
            "pixelTypeRules": "URL rules that add users to a PIXEL segment.",
            "clickersCampaigns": "Campaigns whose clickers make up a CLICKERS segment.",
            "enabled": "Whether the segment is enabled.",
            "archived": "Whether the segment is archived.",
            "membershipDuration": "Number of days a user stays in the segment.",
            "trackingStatus": "Whether the segment is currently receiving data (ACTIVE or INACTIVE).",
            "size": "Number of users in the segment.",
            "creationTime": "Time at which the segment was created.",
            "lastModified": "Time at which the segment was last modified.",
        },
    },
    "campaign_locations": {
        "description": "The geo locations a campaign targets or excludes, one row per location per campaign.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/campaigns",
        "columns": {
            "id": "Unique identifier for the geo location.",
            "_campaign_id": "ID of the campaign the targeting belongs to (injected during sync).",
            "_excluded": "True when the campaign excludes the location, false when it targets it (injected during sync).",
            "name": "The location's name.",
            "canonicalName": "The location's full name, including its parent locations.",
            "geoType": "Location level (e.g. Country, Region, DMA, City, PostalCode).",
            "code": "Location code, e.g. the ISO country code for countries.",
            "parent": "The parent location, for locations below country level.",
        },
    },
    "marketer_performance_daily": {
        "description": "Daily performance metrics (impressions, clicks, spend, conversions) per marketer.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/performance-reporting",
        "columns": {
            "_marketer_id": "ID of the marketer the metrics belong to (injected during sync).",
            "_date": "The day the metrics cover, used as the incremental cursor (injected during sync).",
            "metadata": "Metadata for the report row, including the date range it covers.",
            **_REPORT_METRICS,
        },
    },
    "campaign_performance_daily": {
        "description": "Daily performance metrics (impressions, clicks, spend, conversions) per campaign, including paused and archived campaigns.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/performance-reporting/periodic-by-campaign",
        "columns": {
            "_marketer_id": "ID of the marketer the metrics belong to (injected during sync).",
            "_campaign_id": "ID of the campaign the metrics belong to (injected during sync).",
            "_date": "The day the metrics cover, used as the incremental cursor (injected during sync).",
            "metadata": "Metadata for the report row, including the date range it covers.",
            "metrics": "Performance metrics (impressions, clicks, spend, conversions) for the campaign on that day.",
        },
    },
    "campaign_performance": {
        "description": "Per-campaign performance totals for a trailing window (a snapshot, full-refreshed each sync).",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/performance-reporting",
        "columns": {
            "_marketer_id": "ID of the marketer the metrics belong to (injected during sync).",
            "metadata": "Metadata identifying the campaign the metrics belong to.",
            **_REPORT_METRICS,
        },
    },
    "promoted_link_performance": {
        "description": "Per-promoted-link performance totals for a trailing window (a snapshot, full-refreshed each sync).",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/performance-reporting/promoted-content",
        "columns": {
            "_marketer_id": "ID of the marketer the metrics belong to (injected during sync).",
            "metadata": "The promoted link the metrics belong to, including its id, campaignId, title, url and status.",
            "metrics": "Performance metrics (impressions, clicks, spend, conversions) for the promoted link.",
        },
    },
    "publisher_performance": {
        "description": "Per-publisher performance totals for a trailing window (a snapshot, full-refreshed each sync).",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/performance-reporting/publishers",
        "columns": {
            "_marketer_id": "ID of the marketer the metrics belong to (injected during sync).",
            "metadata": "The publisher the metrics belong to, including its id, name, url and block status.",
            "metrics": "Performance metrics (impressions, clicks, spend, conversions) for the publisher.",
        },
    },
    "section_performance": {
        "description": "Per-section performance totals for a trailing window (a snapshot, full-refreshed each sync). Sections with fewer than 1 click or 10 impressions are omitted.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/performance-reporting/sections",
        "columns": {
            "_marketer_id": "ID of the marketer the metrics belong to (injected during sync).",
            "metadata": "The section the metrics belong to, including its id, name, publisherId, publisherName and block status.",
            "metrics": "Performance metrics (impressions, clicks, spend, conversions) for the section.",
        },
    },
    "interest_performance": {
        "description": "Per-interest performance totals for a trailing window (a snapshot, full-refreshed each sync). A user can have many interests, so the same action counts toward each of them and rows do not sum to the account total.",
        "docs_url": "https://amplifyv01.docs.apiary.io/#reference/performance-reporting/interests",
        "columns": {
            "_marketer_id": "ID of the marketer the metrics belong to (injected during sync).",
            "metadata": "The interest the metrics belong to, including its id, name (e.g. 'News > Weather') and targetingStatus.",
            "metrics": "Performance metrics (impressions, clicks, spend, conversions) for the interest.",
        },
    },
}
