"""Canonical, documentation-sourced descriptions for Mailchimp endpoints and columns.

Sourced from the official Mailchimp Marketing API reference (https://mailchimp.com/developer/marketing/api/).
Keyed by the endpoint names in `settings.py` `MAILCHIMP_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Mailchimp table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "lists": {
        "description": "An audience (mailing list) in Mailchimp that contains contacts and their subscription status.",
        "docs_url": "https://mailchimp.com/developer/marketing/api/lists/",
        "columns": {
            "id": "Unique identifier for the audience (list).",
            "web_id": "The ID used in the Mailchimp web application URLs for the list.",
            "name": "The name of the audience.",
            "date_created": "Time the audience was created.",
            "member_count": "The number of active members in the audience.",
            "unsubscribe_count": "The number of members who have unsubscribed from the audience.",
            "cleaned_count": "The number of cleaned (bounced) members in the audience.",
            "permission_reminder": "The permission reminder shown to contacts about how they were added.",
            "campaign_defaults": "Default values for campaigns sent to this audience (from name, email, subject).",
            "contact": "The physical contact (mailing) address for the audience owner.",
            "visibility": "Whether the audience is public or private.",
            "stats": "Statistics for the audience, including member counts and engagement rates.",
            "list_rating": "The audience's star rating (out of 5), based on subscriber engagement.",
        },
    },
    "campaigns": {
        "description": "An email campaign created in Mailchimp, including its settings, recipients, and content.",
        "docs_url": "https://mailchimp.com/developer/marketing/api/campaigns/",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "web_id": "The ID used in the Mailchimp web application URLs for the campaign.",
            "type": "The type of campaign (regular, plaintext, absplit, rss, variate).",
            "create_time": "Time the campaign was created.",
            "send_time": "Time the campaign was sent.",
            "status": "The current status of the campaign (save, paused, schedule, sending, sent).",
            "emails_sent": "The total number of emails sent for this campaign.",
            "archive_url": "The URL of the archived (web) version of the campaign.",
            "recipients": "Recipient details, including the target audience and segment.",
            "settings": "Campaign settings, including subject line, from name, and reply-to address.",
            "tracking": "Tracking options enabled for the campaign (opens, clicks, etc.).",
            "report_summary": "A summary of the campaign's performance (opens, clicks, subscriber activity).",
        },
    },
    "reports": {
        "description": "A performance report for a sent campaign, summarizing opens, clicks, bounces, and engagement.",
        "docs_url": "https://mailchimp.com/developer/marketing/api/reports/",
        "columns": {
            "id": "Unique identifier for the campaign this report is for.",
            "campaign_title": "The title of the campaign.",
            "type": "The type of campaign the report is for.",
            "list_id": "The unique identifier for the audience the campaign was sent to.",
            "emails_sent": "The total number of emails sent for the campaign.",
            "abuse_reports": "The number of abuse (spam) complaints received.",
            "unsubscribed": "The number of members who unsubscribed after the campaign.",
            "send_time": "Time the campaign was sent.",
            "bounces": "Bounce summary for the campaign (hard, soft, syntax errors).",
            "forwards": "Forwarding activity for the campaign.",
            "opens": "Open activity for the campaign, including total and unique opens.",
            "clicks": "Click activity for the campaign, including total and unique clicks.",
            "list_stats": "Audience-level statistics, including average open and click rates.",
            "timewarp": "Per-hour performance breakdown for campaigns sent with Timewarp, by recipient time zone.",
        },
    },
    "contacts": {
        "description": "A member (contact) of a Mailchimp audience, including subscription status and engagement.",
        "docs_url": "https://mailchimp.com/developer/marketing/api/list-members/",
        "columns": {
            "id": "The MD5 hash of the member's lowercase email address, used as the identifier.",
            "email_address": "The contact's email address.",
            "unique_email_id": "An identifier for the address across all of an account's lists.",
            "web_id": "The ID used in the Mailchimp web application URLs for the contact.",
            "email_type": "The type of email the contact prefers (html or text).",
            "status": "Subscription status (subscribed, unsubscribed, cleaned, pending, transactional).",
            "merge_fields": "Audience merge fields and values for the contact (e.g. first name, last name).",
            "list_id": "The unique identifier for the audience the contact belongs to.",
            "timestamp_signup": "Time the contact signed up to the audience.",
            "timestamp_opt": "Time the contact confirmed their opt-in status.",
            "member_rating": "The contact's star rating, based on engagement.",
            "last_changed": "Time the contact's data was last changed.",
            "language": "The contact's language preference.",
            "vip": "Whether the contact is marked as a VIP.",
            "stats": "Engagement statistics for the contact (average open and click rates).",
        },
    },
}
