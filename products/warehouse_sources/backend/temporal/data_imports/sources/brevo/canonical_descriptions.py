"""Canonical, documentation-sourced descriptions for Brevo endpoints and columns.

Sourced from the official Brevo (v3) API reference (https://developers.brevo.com/reference).
Keyed by the endpoint names in `settings.py` `BREVO_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Brevo table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "A contact in Brevo — a recipient with attributes, list memberships, and subscription status.",
        "docs_url": "https://developers.brevo.com/reference/getcontacts-1",
        "columns": {
            "id": "Unique identifier of the contact.",
            "email": "Email address of the contact.",
            "emailBlacklisted": "Whether the contact is blacklisted from email campaigns.",
            "smsBlacklisted": "Whether the contact is blacklisted from SMS campaigns.",
            "createdAt": "Time at which the contact was created.",
            "modifiedAt": "Time at which the contact was last modified.",
            "listIds": "Identifiers of the lists the contact belongs to.",
            "attributes": "Custom attributes set on the contact.",
        },
    },
    "contact_lists": {
        "description": "A contact list used to group contacts for Brevo campaigns.",
        "docs_url": "https://developers.brevo.com/reference/getlists-1",
        "columns": {
            "id": "Unique identifier of the list.",
            "name": "Name of the list.",
            "totalSubscribers": "Number of subscribed contacts in the list.",
            "totalBlacklisted": "Number of blacklisted contacts in the list.",
            "folderId": "Identifier of the folder the list belongs to.",
            "uniqueSubscribers": "Number of unique subscribers in the list.",
        },
    },
    "contact_folders": {
        "description": "A folder used to organize Brevo contact lists.",
        "docs_url": "https://developers.brevo.com/reference/getfolders-1",
        "columns": {
            "id": "Unique identifier of the folder.",
            "name": "Name of the folder.",
            "totalSubscribers": "Total number of subscribers across the folder's lists.",
            "uniqueSubscribers": "Number of unique subscribers across the folder's lists.",
            "totalBlacklisted": "Total number of blacklisted contacts across the folder's lists.",
        },
    },
    "contact_segments": {
        "description": "A saved segment of contacts defined by filter criteria in Brevo.",
        "docs_url": "https://developers.brevo.com/reference/getsegments",
        "columns": {
            "id": "Unique identifier of the segment.",
            "segmentName": "Name of the segment.",
            "categoryId": "Identifier of the category the segment belongs to.",
        },
    },
    "email_campaigns": {
        "description": "An email marketing campaign created in Brevo.",
        "docs_url": "https://developers.brevo.com/reference/getemailcampaigns-1",
        "columns": {
            "id": "Unique identifier of the email campaign.",
            "name": "Internal name of the campaign.",
            "subject": "Subject line of the campaign email.",
            "type": "Type of campaign (e.g. classic, trigger).",
            "status": "Status of the campaign (e.g. draft, sent, queued, suspended).",
            "createdAt": "Time at which the campaign was created.",
            "modifiedAt": "Time at which the campaign was last modified.",
            "scheduledAt": "Time at which the campaign is scheduled to send.",
            "sentDate": "Time at which the campaign was sent.",
            "statistics": "Aggregate send and engagement statistics for the campaign.",
        },
    },
    "sms_campaigns": {
        "description": "An SMS marketing campaign created in Brevo.",
        "docs_url": "https://developers.brevo.com/reference/getsmscampaigns-1",
        "columns": {
            "id": "Unique identifier of the SMS campaign.",
            "name": "Internal name of the campaign.",
            "status": "Status of the campaign (e.g. draft, sent, queued, suspended).",
            "content": "Text content of the SMS message.",
            "sender": "Sender name displayed for the SMS.",
            "unsubscribe_instruction": "Opt-out instruction text appended to the SMS, containing the STOP keyword.",
            "createdAt": "Time at which the campaign was created.",
            "modifiedAt": "Time at which the campaign was last modified.",
            "scheduledAt": "Time at which the campaign is scheduled to send.",
            "sentDate": "Time at which the campaign was sent.",
            "statistics": "Aggregate send and engagement statistics for the campaign.",
        },
    },
    "email_templates": {
        "description": "A reusable transactional email template stored in Brevo.",
        "docs_url": "https://developers.brevo.com/reference/getsmtptemplates",
        "columns": {
            "id": "Unique identifier of the template.",
            "name": "Name of the template.",
            "subject": "Default subject line of the template email.",
            "isActive": "Whether the template is active.",
            "sender": "Default sender configured for the template.",
            "tag": "Tag associated with the template.",
            "createdAt": "Time at which the template was created.",
            "modifiedAt": "Time at which the template was last modified.",
        },
    },
    "senders": {
        "description": "A verified sender (name and email) available for Brevo campaigns.",
        "docs_url": "https://developers.brevo.com/reference/getsenders-1",
        "columns": {
            "id": "Unique identifier of the sender.",
            "name": "Display name of the sender.",
            "email": "Email address of the sender.",
            "active": "Whether the sender is active and verified.",
        },
    },
}
