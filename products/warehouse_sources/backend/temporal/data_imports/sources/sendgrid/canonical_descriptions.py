"""Canonical, documentation-sourced descriptions for SendGrid endpoints and columns.

Sourced from the official Twilio SendGrid v3 API reference
(https://www.twilio.com/docs/sendgrid/api-reference). Keyed by the schema names in `settings.py`
`SENDGRID_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced SendGrid table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Shared shape of the suppression endpoints (bounces, blocks, invalid emails, spam reports).
_SUPPRESSION_COLUMNS = {
    "email": "The email address that was suppressed.",
    "created": "Time at which the suppression record was created, as a Unix timestamp.",
    "reason": "Reason the email was suppressed.",
    "status": "Status code associated with the suppression event.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "bounces": {
        "description": "Email addresses that bounced — the receiving server rejected the message.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/bounces-api/retrieve-all-bounces",
        "columns": dict(_SUPPRESSION_COLUMNS),
    },
    "blocks": {
        "description": "Email addresses blocked due to temporary delivery issues such as a full mailbox or server outage.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/blocks-api/retrieve-all-blocks",
        "columns": dict(_SUPPRESSION_COLUMNS),
    },
    "invalid_emails": {
        "description": "Email addresses that are invalid or malformed and cannot receive mail.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/invalid-e-mails-api/retrieve-all-invalid-emails",
        "columns": dict(_SUPPRESSION_COLUMNS),
    },
    "spam_reports": {
        "description": "Email addresses of recipients who marked your mail as spam.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/spam-reports-api/retrieve-all-spam-reports",
        "columns": {
            "email": "The email address that reported the message as spam.",
            "created": "Time at which the spam report was recorded, as a Unix timestamp.",
            "ip": "IP address the message was sent from.",
        },
    },
    "global_unsubscribes": {
        "description": "Email addresses on the global unsubscribe list, suppressed from all future mail.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/suppressions-global-suppressions/retrieve-all-global-suppressions",
        "columns": {
            "email": "The globally unsubscribed email address.",
            "created": "Time at which the address was added to the global unsubscribe list, as a Unix timestamp.",
        },
    },
    "stats": {
        "description": "Global email statistics aggregated per day — the send-side volume (requests, delivered, opens, clicks) that turns suppression counts into deliverability rates.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/stats/retrieve-global-email-statistics",
        "columns": {
            "date": "The day the statistics cover, as a YYYY-MM-DD date.",
            "requests": "Number of emails requested to be sent.",
            "processed": "Number of emails processed and handed off for delivery.",
            "delivered": "Number of emails successfully delivered to the recipient's mail server.",
            "deferred": "Number of emails temporarily rejected by the recipient's mail server.",
            "bounces": "Number of emails that bounced — permanently rejected by the receiving server.",
            "bounce_drops": "Number of emails dropped before sending because the address was on the bounce suppression list.",
            "blocks": "Number of emails blocked due to a temporary delivery issue such as a full mailbox.",
            "opens": "Total number of times delivered emails were opened, including repeat opens.",
            "unique_opens": "Number of unique recipients who opened a delivered email.",
            "clicks": "Total number of times links in delivered emails were clicked, including repeat clicks.",
            "unique_clicks": "Number of unique recipients who clicked a link in a delivered email.",
            "unsubscribes": "Number of recipients who unsubscribed.",
            "unsubscribe_drops": "Number of emails dropped because the address was on an unsubscribe suppression list.",
            "spam_reports": "Number of recipients who marked a delivered email as spam.",
            "spam_report_drops": "Number of emails dropped because the address had previously reported spam.",
            "invalid_emails": "Number of emails dropped because the recipient address was invalid.",
        },
    },
    "categories": {
        "description": "Categories: the tags senders attach to emails to group them by topic, used to segment statistics.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/categories/retrieve-all-categories",
        "columns": {
            "category": "Name of the category used to group emails by broad topic.",
        },
    },
    "category_stats": {
        "description": "Daily email statistics for each category, such as requests, deliveries, opens, clicks, and bounces.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/categories/retrieve-email-statistics-for-categories",
        "columns": {
            "date": "The date the statistics were gathered, in YYYY-MM-DD format.",
            "category": "Name of the category that the statistics are for.",
            "requests": "Number of emails that were requested to be delivered.",
            "processed": "Number of requests that SendGrid processed.",
            "delivered": "Number of emails that SendGrid confirmed were delivered to a recipient.",
            "deferred": "Number of emails that temporarily could not be delivered.",
            "opens": "Total number of times the emails were opened by recipients.",
            "unique_opens": "Number of unique recipients who opened the emails.",
            "clicks": "Number of links that were clicked.",
            "unique_clicks": "Number of unique recipients who clicked links in the emails.",
            "bounces": "Number of emails that bounced instead of being delivered.",
            "bounce_drops": "Number of emails that were dropped because of a bounce.",
            "blocks": "Number of emails that were not allowed to be delivered by ISPs.",
            "invalid_emails": "Number of recipients with malformed addresses or addresses that the mail provider reported as invalid.",
            "spam_reports": "Number of recipients who marked the email as spam.",
            "spam_report_drops": "Number of emails that were dropped because the recipient previously marked emails as spam.",
            "unsubscribes": "Number of recipients who unsubscribed.",
            "unsubscribe_drops": "Number of emails that were dropped because the recipient unsubscribed.",
        },
    },
    "unsubscribe_groups": {
        "description": "Suppression (unsubscribe) groups used to let recipients opt out of specific categories of mail.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/suppressions-unsubscribe-groups/retrieve-all-suppression-groups-associated-with-the-user",
        "columns": {
            "id": "Unique identifier for the unsubscribe group.",
            "name": "Name of the unsubscribe group.",
            "description": "Description of the unsubscribe group.",
            "is_default": "Whether this is the default unsubscribe group.",
            "unsubscribes": "Number of unsubscribes recorded against this group.",
        },
    },
    "unsubscribe_group_suppressions": {
        "description": "Membership rows of unsubscribe groups: one row per email address suppressed from a group.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/suppressions-suppressions/retrieve-all-suppressions",
        "columns": {
            "email": "The email address that was suppressed.",
            "group_id": "The id of the unsubscribe group that this email address belongs to.",
            "group_name": "The name of the unsubscribe group that this email address belongs to.",
            "created_at": "Time at which the suppression was created, as a Unix timestamp.",
        },
    },
    "marketing_lists": {
        "description": "Marketing contact lists used to segment recipients for campaigns.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/lists/get-all-lists",
        "columns": {
            "id": "Unique identifier for the list.",
            "name": "Name of the list.",
            "contact_count": "Number of contacts on the list.",
        },
    },
    "singlesends": {
        "description": "Single Sends: one-time Marketing Campaigns emails sent to lists or segments.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/single-sends/get-all-single-sends",
        "columns": {
            "id": "Unique identifier for the Single Send.",
            "name": "Name of the Single Send.",
            "status": "Current status of the Single Send: draft, scheduled, or triggered.",
            "categories": "Categories associated with the Single Send.",
            "send_at": "Time at which the Single Send is scheduled to send, in ISO 8601 format.",
            "is_abtest": "Whether the A/B test feature is turned on for the Single Send.",
            "abtest": "Summary of the A/B test settings of the Single Send.",
            "created_at": "Time at which the Single Send was created, in ISO 8601 format.",
            "updated_at": "Time at which the Single Send was last updated, in ISO 8601 format.",
        },
    },
    "singlesend_stats": {
        "description": "Lifetime engagement statistics for each Single Send, such as requests, deliveries, opens, and clicks.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/marketing-campaign-stats/get-all-single-sends-stats",
        "columns": {
            "id": "Unique identifier for the Single Send that the statistics are for.",
            "ab_variation": "The A/B variation of the statistics, or all when the statistics cover every variation.",
            "ab_phase": "The A/B phase of the statistics (send, test, or all).",
            "aggregation": "The time unit that the statistics are rolled up to, total for lifetime totals.",
            "stats": "The metrics: requests, delivered, opens, unique_opens, clicks, unique_clicks, bounces, bounce_drops, invalid_emails, spam_reports, spam_report_drops, and unsubscribes.",
        },
    },
    "singlesend_link_stats": {
        "description": "Click counts for each link in each Single Send.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/marketing-campaign-stats/get-single-send-click-tracking-stats-by-id",
        "columns": {
            "singlesend_id": "Unique identifier for the Single Send that contains the link.",
            "url": "The URL of the clicked link, including any custom fields in the URL.",
            "url_location": "The position of the link in the email, numbered from the top down starting at 0.",
            "ab_variation": "The A/B variation of the statistics, or all when the statistics cover every variation.",
            "ab_phase": "The A/B phase of the statistics (send, test, or all).",
            "clicks": "Number of clicks on this link.",
        },
    },
    "automation_stats": {
        "description": "Lifetime engagement statistics for each Marketing Campaigns Automation, such as requests, deliveries, opens, and clicks.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/marketing-campaign-stats/get-all-automation-stats",
        "columns": {
            "id": "Unique identifier for the Automation that the statistics are for.",
            "aggregation": "The time unit that the statistics are rolled up to, total for lifetime totals.",
            "step_id": "The Automation step that the statistics are for, or all when they cover every step.",
            "stats": "The metrics: requests, delivered, opens, unique_opens, clicks, unique_clicks, bounces, bounce_drops, invalid_emails, spam_reports, spam_report_drops, and unsubscribes.",
        },
    },
    "automation_link_stats": {
        "description": "Click counts for each link in each Marketing Campaigns Automation.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/marketing-campaign-stats/get-automation-click-tracking-stats-by-id",
        "columns": {
            "automation_id": "Unique identifier for the Automation that contains the link.",
            "url": "The URL of the clicked link, including any custom fields in the URL.",
            "url_location": "The position of the link in the Automation step, numbered from the top down starting at 0.",
            "step_id": "The Automation step that contains the link.",
            "clicks": "Number of clicks on this link.",
        },
    },
    "templates": {
        "description": "Email templates (legacy and dynamic) used to compose messages.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/transactional-templates/retrieve-paged-transactional-templates",
        "columns": {
            "id": "Unique identifier for the template.",
            "name": "Name of the template.",
            "generation": "Template generation: legacy or dynamic.",
            "updated_at": "Time at which the template was last updated.",
            "versions": "List of versions belonging to the template.",
        },
    },
    "message_activity": {
        "description": "Per-message activity from the Email Activity feed: one row per sent message with its latest delivery status and engagement counts. Requires SendGrid's paid additional email activity history add-on.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/email-activity/filter-all-messages",
        "columns": {
            "msg_id": "Unique identifier for the message.",
            "from_email": "Sender address of the message.",
            "to_email": "Recipient address of the message.",
            "subject": "Subject line of the message.",
            "status": "Latest delivery status of the message: processed, delivered, or not_delivered.",
            "opens_count": "Number of times the message was opened.",
            "clicks_count": "Number of times links in the message were clicked.",
            "last_event_time": "Time of the most recent event recorded for the message, in ISO 8601 format.",
        },
    },
}
