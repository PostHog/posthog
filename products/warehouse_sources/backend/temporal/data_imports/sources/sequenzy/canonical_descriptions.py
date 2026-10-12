"""Canonical, documentation-sourced descriptions for Sequenzy endpoints and columns.

Sourced from the official Sequenzy API reference (https://docs.sequenzy.com/api-reference).
Keyed by the endpoint names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Sequenzy table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "subscribers": {
        "description": "An email contact in the workspace, with status, tags, and custom attributes.",
        "docs_url": "https://docs.sequenzy.com/api-reference/subscribers/list",
        "columns": {
            "id": "Unique identifier for the subscriber.",
            "email": "The subscriber's email address.",
            "firstName": "The subscriber's first name.",
            "lastName": "The subscriber's last name.",
            "status": "Delivery status: active, unsubscribed, or bounced.",
            "unsubscribedAt": "When the contact opted out. Null unless the contact is currently unsubscribed, and null for contacts imported as already unsubscribed.",
            "emailProvider": "Detected mailbox provider of the address (e.g. gmail).",
            "tags": "Names of the tags applied to the subscriber.",
            "customAttributes": "Custom attribute key-value pairs stored on the subscriber.",
            "createdAt": "When the subscriber was created.",
            "updatedAt": "When the subscriber was last updated. Moves on any tag or attribute write.",
        },
    },
    "tags": {
        "description": "A tag definition used to segment subscribers and trigger automations.",
        "docs_url": "https://docs.sequenzy.com/api-reference/tags/list",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "The tag's name.",
            "color": "Display color of the tag in the Sequenzy dashboard.",
            "isSystem": "Whether the tag is a built-in system tag rather than a user-created one.",
        },
    },
    "lists": {
        "description": "A subscriber list, with current membership counts.",
        "docs_url": "https://docs.sequenzy.com/api-reference/lists/list",
        "columns": {
            "id": "Unique identifier for the list.",
            "name": "The list's name.",
            "description": "Description of the list.",
            "isPrivate": "Whether the list is hidden from subscribers' preference pages.",
            "allowMemberUnsubscribe": "Whether current members of a private list can see it and opt out through preferences.",
            "createdAt": "When the list was created.",
            "subscriberCount": "Current members of any status. Members who unsubscribed from the list are not counted.",
            "activeSubscriberCount": "Current members with status active.",
        },
    },
    "segments": {
        "description": "A saved segment: a set of filters over subscribers, with live match counts.",
        "docs_url": "https://docs.sequenzy.com/api-reference/segments/list",
        "columns": {
            "id": "Unique identifier for the segment.",
            "name": "The segment's name.",
            "filters": "The segment's saved filter conditions.",
            "filterJoinOperator": "How the top-level filters combine: and / or.",
            "format": "Version of the stored filter format.",
            "createdAt": "When the segment was created.",
            "subscriberCount": "Matching contacts of every status, recalculated from the saved filters on each request.",
            "activeSubscriberCount": "Matching contacts with status active.",
        },
    },
    "campaigns": {
        "description": "An email campaign (broadcast), with scheduling, delivery pacing, and audience state.",
        "docs_url": "https://docs.sequenzy.com/api-reference/campaigns/list",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "name": "The campaign's name.",
            "subject": "Subject line of the campaign email.",
            "emailId": "ID of the email content linked to the campaign.",
            "emailPreset": "The linked email's format: branded, minimal, or null for SMS campaigns and raw-HTML emails.",
            "status": "Campaign status: draft, scheduled, sent, sending, cancelled, paused, waiting_approval, or rejected.",
            "hasAudience": "Whether an explicit audience is configured. Does not count eligible recipients or validate that referenced audiences still exist.",
            "labels": "Dashboard label names assigned to the campaign.",
            "scheduledAt": "When the campaign is scheduled to send.",
            "sentAt": "When the campaign finished sending.",
            "spreadOverHours": "Hours the send is spread over, for paced delivery.",
            "sendTimeOptimization": "Whether per-recipient send-time optimization is enabled.",
            "sendTimeWindowHours": "Size of the send-time optimization window in hours.",
            "sendInRecipientTimezone": "Whether the scheduled time is interpreted in each recipient's timezone.",
            "scheduledTimezone": "Timezone the scheduled time was set in.",
            "maxRecipients": "Recipient cap for the send. Null when the whole audience is targeted.",
            "createdAt": "When the campaign was created.",
        },
    },
    "sequences": {
        "description": "An automation sequence (email workflow), with trigger, run state, and sending window.",
        "docs_url": "https://docs.sequenzy.com/api-reference/sequences/list",
        "columns": {
            "id": "Unique identifier for the sequence.",
            "name": "The sequence's name.",
            "status": "Stored status: draft, active, paused, or archived. An active sequence may still have enrollments paused.",
            "enrollmentPaused": "Whether new enrollments are paused while existing recipients continue.",
            "effectiveStatus": "Combined run state: draft, live, enrollment_paused, paused, or archived. Prefer this over status.",
            "acceptsNewEnrollments": "Whether new subscribers can enter the sequence.",
            "processesExistingEnrollments": "Whether recipients already in the sequence continue to advance.",
            "trigger": "What enrolls subscribers into the sequence.",
            "sendingWindow": "Days and hours the sequence is allowed to send in, with timezone.",
            "createdAt": "When the sequence was created.",
        },
    },
    "email_metrics": {
        "description": "Per-email engagement metrics: one row per campaign and per sequence email step, with delivery funnel, conversions, and revenue.",
        "docs_url": "https://docs.sequenzy.com/api-reference/analytics/email-metrics",
        "columns": {
            "emailType": "Whether the row is a campaign or a sequence email step.",
            "emailId": "Campaign ID for campaigns, automation node ID for sequence emails.",
            "name": "Campaign name, or the step's subject line falling back to its node label.",
            "campaignId": "Campaign ID, or null for sequence emails.",
            "sequenceId": "Sequence ID, or null for campaigns.",
            "sequenceName": "Name of the sequence the step belongs to.",
            "automationNodeId": "Node ID of the sequence step.",
            "step": "1-based position of the email in its sequence, or null for campaigns.",
            "stats": "Delivery funnel for this email alone: sends, deliveries, bounces, opens, clicks, unsubscribes and rates.",
            "conversions": "Goal conversions attributed to this email (last-touch).",
            "revenueCents": "Attributed revenue in cents from purchase events.",
        },
    },
}
