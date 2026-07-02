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
}
