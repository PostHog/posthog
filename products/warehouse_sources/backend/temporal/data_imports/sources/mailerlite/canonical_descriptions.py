"""Canonical, documentation-sourced descriptions for MailerLite endpoints and columns.

Sourced from the official MailerLite API reference (https://developers.mailerlite.com/docs).
Keyed by the endpoint names in `settings.py` `MAILERLITE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced MailerLite table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "subscribers": {
        "description": "A subscriber (contact) in the MailerLite account, including status and custom fields.",
        "docs_url": "https://developers.mailerlite.com/docs/subscribers.html",
        "columns": {
            "id": "Unique identifier for the subscriber.",
            "email": "The subscriber's email address.",
            "status": "Subscription status (active, unsubscribed, unconfirmed, bounced, junk).",
            "source": "How the subscriber was added to the account.",
            "sent": "The total number of emails sent to the subscriber.",
            "opens_count": "The number of emails the subscriber has opened.",
            "clicks_count": "The number of emails in which the subscriber clicked a link.",
            "open_rate": "The subscriber's average email open rate.",
            "click_rate": "The subscriber's average email click rate.",
            "ip_address": "The IP address the subscriber signed up from.",
            "subscribed_at": "Time the subscriber subscribed.",
            "unsubscribed_at": "Time the subscriber unsubscribed, if applicable.",
            "created_at": "Time the subscriber was created.",
            "updated_at": "Time the subscriber was last updated.",
            "fields": "Custom field values for the subscriber.",
            "groups": "The groups the subscriber belongs to.",
        },
    },
    "campaigns": {
        "description": "An email campaign in MailerLite, including its type, status, and delivery settings.",
        "docs_url": "https://developers.mailerlite.com/docs/campaigns.html",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "name": "The internal name of the campaign.",
            "type": "The type of campaign (regular, ab, resend).",
            "status": "The current status of the campaign (draft, ready, sent).",
            "emails": "The emails (content variations) associated with the campaign.",
            "settings": "Delivery and tracking settings for the campaign.",
            "scheduled_for": "Time the campaign is scheduled to be delivered.",
            "delivered_at": "Time the campaign was delivered.",
            "created_at": "Time the campaign was created.",
            "updated_at": "Time the campaign was last updated.",
        },
    },
    "groups": {
        "description": "A group (segment-like collection) of subscribers in MailerLite.",
        "docs_url": "https://developers.mailerlite.com/docs/groups.html",
        "columns": {
            "id": "Unique identifier for the group.",
            "name": "The name of the group.",
            "active_count": "The number of active subscribers in the group.",
            "sent_count": "The number of emails sent to the group.",
            "opens_count": "The number of opens for the group.",
            "clicks_count": "The number of clicks for the group.",
            "unsubscribed_count": "The number of subscribers who unsubscribed from the group.",
            "open_rate": "The average open rate for the group.",
            "click_rate": "The average click rate for the group.",
            "created_at": "Time the group was created.",
        },
    },
    "segments": {
        "description": "A dynamic segment of subscribers in MailerLite defined by filter conditions.",
        "docs_url": "https://developers.mailerlite.com/docs/segments.html",
        "columns": {
            "id": "Unique identifier for the segment.",
            "name": "The name of the segment.",
            "total": "The total number of subscribers matching the segment.",
            "open_rate": "The average open rate for the segment.",
            "click_rate": "The average click rate for the segment.",
            "created_at": "Time the segment was created.",
        },
    },
    "fields": {
        "description": "A custom field definition used to store extra data on subscribers.",
        "docs_url": "https://developers.mailerlite.com/docs/fields.html",
        "columns": {
            "id": "Unique identifier for the field.",
            "name": "The display name of the field.",
            "key": "The key used to reference the field on subscribers.",
            "type": "The data type of the field (text, number, date).",
        },
    },
    "automations": {
        "description": "An automation (workflow) in MailerLite that triggers emails based on subscriber events.",
        "docs_url": "https://developers.mailerlite.com/docs/automations.html",
        "columns": {
            "id": "Unique identifier for the automation.",
            "name": "The name of the automation.",
            "enabled": "Whether the automation is currently enabled.",
            "trigger_data": "The trigger configuration that starts the automation.",
            "steps": "The sequence of steps in the automation workflow.",
            "stats": "Statistics for the automation (subscribers, opens, clicks).",
            "first_email_screenshot_url": "URL of a screenshot preview of the automation's first email.",
            "created_at": "Time the automation was created.",
        },
    },
    "forms_popup": {
        "description": "A pop-up subscription form in MailerLite used to capture new subscribers.",
        "docs_url": "https://developers.mailerlite.com/docs/forms.html",
        "columns": {
            "id": "Unique identifier for the form.",
            "name": "The name of the form.",
            "type": "The type of form (popup).",
            "conversions_count": "The number of conversions (sign-ups) from the form.",
            "opens_count": "The number of times the form was shown.",
            "conversion_rate": "The conversion rate for the form.",
            "created_at": "Time the form was created.",
        },
    },
    "forms_embedded": {
        "description": "An embedded subscription form in MailerLite used to capture new subscribers.",
        "docs_url": "https://developers.mailerlite.com/docs/forms.html",
        "columns": {
            "id": "Unique identifier for the form.",
            "name": "The name of the form.",
            "type": "The type of form (embedded).",
            "conversions_count": "The number of conversions (sign-ups) from the form.",
            "opens_count": "The number of times the form was shown.",
            "conversion_rate": "The conversion rate for the form.",
            "created_at": "Time the form was created.",
        },
    },
    "forms_promotion": {
        "description": "A promotion form in MailerLite used to display promotional content to visitors.",
        "docs_url": "https://developers.mailerlite.com/docs/forms.html",
        "columns": {
            "id": "Unique identifier for the form.",
            "name": "The name of the form.",
            "type": "The type of form (promotion).",
            "conversions_count": "The number of conversions from the form.",
            "opens_count": "The number of times the form was shown.",
            "conversion_rate": "The conversion rate for the form.",
            "created_at": "Time the form was created.",
        },
    },
    "webhooks": {
        "description": "A webhook subscription in MailerLite that delivers event notifications to an external URL.",
        "docs_url": "https://developers.mailerlite.com/docs/webhooks.html",
        "columns": {
            "id": "Unique identifier for the webhook.",
            "name": "The name of the webhook.",
            "url": "The destination URL the webhook posts events to.",
            "events": "The list of events the webhook is subscribed to.",
            "enabled": "Whether the webhook is currently enabled.",
            "created_at": "Time the webhook was created.",
            "updated_at": "Time the webhook was last updated.",
        },
    },
}
