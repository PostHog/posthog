"""Canonical, documentation-sourced descriptions for Campaign Monitor endpoints and columns.

Sourced from the official Campaign Monitor (CreateSend) API v3.3 reference
(https://www.campaignmonitor.com/api/). Keyed by the endpoint names in `settings.py`
`CAMPAIGN_MONITOR_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Campaign
Monitor table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "clients": {
        "description": "A Campaign Monitor client — an account that owns lists, campaigns, and subscribers.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/account/#getting-your-clients",
        "columns": {
            "ClientID": "Unique identifier for the client.",
            "Name": "Name of the client.",
        },
    },
    "campaigns": {
        "description": "A sent email campaign belonging to the client.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/clients/#sent-campaigns",
        "columns": {
            "CampaignID": "Unique identifier for the campaign.",
            "Name": "Internal name of the campaign.",
            "Subject": "Subject line of the campaign email.",
            "FromName": "Sender name shown on the campaign.",
            "FromEmail": "Sender email address used for the campaign.",
            "ReplyTo": "Reply-to email address for the campaign.",
            "SentDate": "Date and time the campaign was sent.",
            "TotalRecipients": "Total number of recipients the campaign was sent to.",
            "WebVersionURL": "Public web (browser) version URL of the campaign.",
            "WebVersionTextURL": "Public web version URL of the plain-text campaign.",
        },
    },
    "scheduled_campaigns": {
        "description": "A campaign that is scheduled to be sent at a future date.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/clients/#scheduled-campaigns",
        "columns": {
            "CampaignID": "Unique identifier for the campaign.",
            "Name": "Internal name of the campaign.",
            "Subject": "Subject line of the campaign email.",
            "FromName": "Sender name shown on the campaign.",
            "FromEmail": "Sender email address used for the campaign.",
            "ReplyTo": "Reply-to email address for the campaign.",
            "DateCreated": "Date and time the campaign was created.",
            "DateScheduled": "Date and time the campaign is scheduled to send.",
            "ScheduledTimeZone": "Time zone the scheduled send time is expressed in.",
            "PreviewURL": "Preview URL for the scheduled campaign.",
        },
    },
    "draft_campaigns": {
        "description": "A draft campaign that has not yet been sent or scheduled.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/clients/#draft-campaigns",
        "columns": {
            "CampaignID": "Unique identifier for the campaign.",
            "Name": "Internal name of the draft campaign.",
            "Subject": "Subject line of the draft campaign email.",
            "FromName": "Sender name configured on the draft.",
            "FromEmail": "Sender email address configured on the draft.",
            "ReplyTo": "Reply-to email address configured on the draft.",
            "DateCreated": "Date and time the draft was created.",
            "PreviewURL": "Preview URL for the draft campaign.",
        },
    },
    "lists": {
        "description": "A subscriber list belonging to the client.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/clients/#subscriber-lists",
        "columns": {
            "ListID": "Unique identifier for the subscriber list.",
            "Name": "Name of the subscriber list.",
        },
    },
    "segments": {
        "description": "A segment — a saved subset of a subscriber list defined by rules.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/clients/#subscriber-segments",
        "columns": {
            "SegmentID": "Unique identifier for the segment.",
            "ListID": "Identifier of the list the segment belongs to.",
            "Title": "Title of the segment.",
        },
    },
    "templates": {
        "description": "An email template available to the client for building campaigns.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/clients/#templates",
        "columns": {
            "TemplateID": "Unique identifier for the template.",
            "Name": "Name of the template.",
            "PreviewURL": "Preview URL for the template.",
            "ScreenshotURL": "URL of the template's thumbnail screenshot.",
        },
    },
    "suppression_list": {
        "description": "Email addresses suppressed for the client (will not receive campaigns).",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/clients/#suppression-list",
        "columns": {
            "EmailAddress": "Suppressed email address.",
            "Date": "Date the address was added to the suppression list.",
            "State": "Suppression state (e.g. Suppressed).",
            "SuppressionReason": "Reason the address was suppressed (e.g. Unsubscribed, Bounced).",
        },
    },
    "active_subscribers": {
        "description": "Subscribers currently active (subscribed) on a list.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/lists/#active-subscribers",
        "columns": {
            "EmailAddress": "Subscriber's email address.",
            "ListID": "Identifier of the list the subscriber belongs to.",
            "Name": "Subscriber's name.",
            "Date": "Date the subscriber was added to or last changed state on the list.",
            "State": "Subscription state of the subscriber (Active).",
            "CustomFields": "Custom field values stored against the subscriber.",
            "ReadsEmailWith": "Email client the subscriber is detected to read email with.",
        },
    },
    "unsubscribed_subscribers": {
        "description": "Subscribers who have unsubscribed from a list.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/lists/#unsubscribed-subscribers",
        "columns": {
            "EmailAddress": "Subscriber's email address.",
            "ListID": "Identifier of the list the subscriber unsubscribed from.",
            "Name": "Subscriber's name.",
            "Date": "Date the subscriber unsubscribed.",
            "State": "Subscription state of the subscriber (Unsubscribed).",
            "CustomFields": "Custom field values stored against the subscriber.",
        },
    },
    "bounced_subscribers": {
        "description": "Subscribers whose email to a list has bounced.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/lists/#bounced-subscribers",
        "columns": {
            "EmailAddress": "Subscriber's email address.",
            "ListID": "Identifier of the list the subscriber belongs to.",
            "Name": "Subscriber's name.",
            "Date": "Date the email to the subscriber bounced.",
            "State": "Subscription state of the subscriber (Bounced).",
            "CustomFields": "Custom field values stored against the subscriber.",
        },
    },
    "campaign_summary": {
        "description": "Aggregate performance summary for a sent campaign — one row per campaign with recipient, open, click, unsubscribe, bounce, and spam complaint totals.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/campaigns/#campaign-summary-2",
        "columns": {
            "CampaignID": "Unique identifier for the campaign the summary belongs to.",
            "Name": "Internal name of the campaign.",
            "Recipients": "Total number of recipients the campaign was sent to.",
            "TotalOpened": "Total number of opens recorded, including repeat opens by the same recipient.",
            "UniqueOpened": "Number of unique recipients who opened the campaign.",
            "Clicks": "Total number of link clicks recorded for the campaign.",
            "Unsubscribed": "Number of recipients who unsubscribed from the campaign.",
            "Bounced": "Number of recipients whose email bounced.",
            "SpamComplaints": "Number of recipients who marked the campaign as spam.",
            "Forwards": "Number of times the campaign was forwarded using the forward-to-a-friend feature.",
            "Likes": "Number of Facebook likes recorded for the campaign.",
            "Mentions": "Number of Twitter mentions recorded for the campaign.",
            "WebVersionURL": "Public web (browser) version URL of the campaign.",
            "WebVersionTextURL": "Public web version URL of the plain-text campaign.",
            "WorldviewURL": "URL of the campaign's public Worldview page.",
        },
    },
    "campaign_opens": {
        "description": "Individual open events for a sent campaign — one row per recorded open, including repeat opens by the same recipient.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/campaigns/#campaign-opens",
        "columns": {
            "CampaignID": "Unique identifier for the campaign the open belongs to.",
            "EmailAddress": "Email address of the recipient who opened the campaign.",
            "ListID": "Identifier of the list the recipient belongs to.",
            "Date": "Date and time the open was recorded.",
            "IPAddress": "IP address the open was recorded from.",
            "Latitude": "Approximate latitude geocoded from the IP address, when available.",
            "Longitude": "Approximate longitude geocoded from the IP address, when available.",
            "City": "City geocoded from the IP address, when available.",
            "Region": "Region geocoded from the IP address, when available.",
            "CountryCode": "Country code geocoded from the IP address, when available.",
            "CountryName": "Country name geocoded from the IP address, when available.",
        },
    },
    "campaign_clicks": {
        "description": "Individual link click events for a sent campaign — one row per recorded click.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/campaigns/#campaign-clicks",
        "columns": {
            "CampaignID": "Unique identifier for the campaign the click belongs to.",
            "EmailAddress": "Email address of the recipient who clicked.",
            "ListID": "Identifier of the list the recipient belongs to.",
            "URL": "The link URL that was clicked.",
            "Date": "Date and time the click was recorded.",
            "IPAddress": "IP address the click was recorded from.",
            "Latitude": "Approximate latitude geocoded from the IP address, when available.",
            "Longitude": "Approximate longitude geocoded from the IP address, when available.",
            "City": "City geocoded from the IP address, when available.",
            "Region": "Region geocoded from the IP address, when available.",
            "CountryCode": "Country code geocoded from the IP address, when available.",
            "CountryName": "Country name geocoded from the IP address, when available.",
        },
    },
    "campaign_unsubscribes": {
        "description": "Recipients who unsubscribed as a result of a sent campaign — one row per recipient per campaign.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/campaigns/#campaign-unsubscribes",
        "columns": {
            "CampaignID": "Unique identifier for the campaign the unsubscribe belongs to.",
            "EmailAddress": "Email address of the recipient who unsubscribed.",
            "ListID": "Identifier of the list the recipient unsubscribed from.",
            "Date": "Date and time the unsubscribe was recorded.",
            "IPAddress": "IP address the unsubscribe was recorded from.",
        },
    },
    "campaign_bounces": {
        "description": "Recipients whose email bounced for a sent campaign — one row per recipient per campaign.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/campaigns/#campaign-bounces",
        "columns": {
            "CampaignID": "Unique identifier for the campaign the bounce belongs to.",
            "EmailAddress": "Email address of the recipient whose email bounced.",
            "ListID": "Identifier of the list the recipient belongs to.",
            "BounceType": "Type of bounce (Hard or Soft).",
            "Date": "Date and time the bounce was recorded.",
            "Reason": "Reason reported for the bounce.",
        },
    },
    "campaign_spam_complaints": {
        "description": "Recipients who marked a sent campaign as spam — one row per recipient per campaign.",
        "docs_url": "https://www.campaignmonitor.com/api/v3-3/campaigns/#campaign-spam-complaints",
        "columns": {
            "CampaignID": "Unique identifier for the campaign the complaint belongs to.",
            "EmailAddress": "Email address of the recipient who marked the campaign as spam.",
            "ListID": "Identifier of the list the recipient belongs to.",
            "Date": "Date and time the spam complaint was recorded.",
        },
    },
}
