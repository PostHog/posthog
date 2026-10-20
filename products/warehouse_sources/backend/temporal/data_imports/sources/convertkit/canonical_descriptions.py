"""Canonical, documentation-sourced descriptions for ConvertKit (Kit) endpoints and columns.

Sourced from the official Kit (formerly ConvertKit) v4 API reference
(https://developers.kit.com/api-reference). Keyed by the endpoint names in `settings.py`
`CONVERTKIT_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced ConvertKit table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "subscribers": {
        "description": "A subscriber on your Kit (ConvertKit) account.",
        "docs_url": "https://developers.kit.com/api-reference/subscribers/list-subscribers",
        "columns": {
            "id": "Unique identifier for the subscriber.",
            "first_name": "First name of the subscriber.",
            "email_address": "Email address of the subscriber.",
            "state": "State of the subscriber (active, inactive, bounced, complained, cancelled).",
            "created_at": "Date and time the subscriber was created.",
            "updated_at": "Date and time the subscriber was last updated.",
            "fields": "Custom field values stored for the subscriber.",
        },
    },
    "broadcasts": {
        "description": "A broadcast — a one-time email sent to a segment of your subscribers.",
        "docs_url": "https://developers.kit.com/api-reference/broadcasts/list-broadcasts",
        "columns": {
            "id": "Unique identifier for the broadcast.",
            "subject": "Subject line of the broadcast email.",
            "description": "Internal description of the broadcast.",
            "content": "HTML content of the broadcast email.",
            "public": "Whether the broadcast is publicly visible.",
            "published_at": "Date and time the broadcast was published.",
            "send_at": "Scheduled send date and time of the broadcast.",
            "created_at": "Date and time the broadcast was created.",
        },
    },
    "forms": {
        "description": "A form or landing page used to capture new subscribers.",
        "docs_url": "https://developers.kit.com/api-reference/forms/list-forms",
        "columns": {
            "id": "Unique identifier for the form.",
            "name": "Name of the form.",
            "type": "Type of the form (e.g. embed, hosted).",
            "format": "Display format of the form (e.g. inline, modal, slide in, sticky bar).",
            "url": "URL of the hosted form, if applicable.",
            "archived": "Whether the form has been archived.",
            "created_at": "Date and time the form was created.",
        },
    },
    "sequences": {
        "description": "A sequence — an automated series of emails sent to subscribers over time.",
        "docs_url": "https://developers.kit.com/api-reference/sequences/list-sequences",
        "columns": {
            "id": "Unique identifier for the sequence.",
            "name": "Name of the sequence.",
            "created_at": "Date and time the sequence was created.",
            "updated_at": "Date and time the sequence was last updated.",
            "subscriber_count": "Number of subscribers currently in the sequence.",
        },
    },
    "tags": {
        "description": "A tag used to label and segment subscribers.",
        "docs_url": "https://developers.kit.com/api-reference/tags/list-tags",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "Name of the tag.",
            "created_at": "Date and time the tag was created.",
        },
    },
    "custom_fields": {
        "description": "A custom field used to store additional data about subscribers.",
        "docs_url": "https://developers.kit.com/api-reference/custom-fields/list-custom-fields",
        "columns": {
            "id": "Unique identifier for the custom field.",
            "name": "Internal key of the custom field, used when setting values.",
            "key": "Snake-cased key of the custom field.",
            "label": "Human-readable label of the custom field.",
        },
    },
    "purchases": {
        "description": "A purchase recorded against a subscriber for commerce reporting.",
        "docs_url": "https://developers.kit.com/api-reference/purchases/list-purchases",
        "columns": {
            "id": "Unique identifier for the purchase.",
            "transaction_id": "Identifier of the transaction in your commerce system.",
            "email_address": "Email address of the purchasing subscriber.",
            "currency": "Three-letter ISO currency code of the purchase.",
            "subtotal": "Subtotal amount of the purchase before tax and shipping.",
            "tax": "Tax amount applied to the purchase.",
            "shipping": "Shipping amount applied to the purchase.",
            "discount": "Discount amount applied to the purchase.",
            "total": "Total amount of the purchase.",
            "status": "Status of the purchase (e.g. paid).",
            "transaction_time": "Date and time the transaction occurred.",
            "products": "Line items included in the purchase.",
        },
    },
    "email_templates": {
        "description": "An email template used to style broadcasts and sequence emails.",
        "docs_url": "https://developers.kit.com/api-reference/email-templates/list-email-templates",
        "columns": {
            "id": "Unique identifier for the email template.",
            "name": "Name of the email template.",
            "category": "Category of the email template.",
            "is_default": "Whether this is the account's default template.",
        },
    },
    "broadcast_stats": {
        "description": "Delivery and engagement stats for a broadcast: recipients, opens, clicks and unsubscribes.",
        "docs_url": "https://developers.kit.com/api-reference/broadcasts/get-stats-for-a-list-of-broadcasts",
        "columns": {
            "id": "Unique identifier of the broadcast the stats belong to.",
            "subject": "Subject line of the broadcast email.",
            "send_at": "Scheduled send date and time of the broadcast.",
            "stats": "Delivery and engagement counters: recipients, emails_opened, open_rate, click_rate, total_clicks, unsubscribes, unsubscribe_rate, status, progress, and the open/click tracking flags.",
        },
    },
    "form_subscribers": {
        "description": "A subscriber who joined through, or was added to, a form. This is the form-to-subscriber junction.",
        "docs_url": "https://developers.kit.com/api-reference/forms/list-subscribers-for-a-form",
        "columns": {
            "form_id": "Identifier of the form the subscriber belongs to.",
            "id": "Unique identifier for the subscriber.",
            "first_name": "First name of the subscriber.",
            "email_address": "Email address of the subscriber.",
            "state": "State of the subscriber (active, inactive, bounced, complained, cancelled).",
            "created_at": "Date and time the subscriber was created.",
            "added_at": "Date and time the subscriber was added to the form.",
            "referrer": "URL the subscriber came from when they signed up.",
            "referrer_utm_parameters": "UTM source, medium, campaign, term and content parsed from the referrer.",
            "fields": "Custom field values stored for the subscriber.",
        },
    },
    "tag_subscribers": {
        "description": "A subscriber carrying a tag. This is the tag-to-subscriber junction.",
        "docs_url": "https://developers.kit.com/api-reference/tags/list-subscribers-for-a-tag",
        "columns": {
            "tag_id": "Identifier of the tag applied to the subscriber.",
            "id": "Unique identifier for the subscriber.",
            "first_name": "First name of the subscriber.",
            "email_address": "Email address of the subscriber.",
            "state": "State of the subscriber (active, inactive, bounced, complained, cancelled).",
            "created_at": "Date and time the subscriber was created.",
            "tagged_at": "Date and time the tag was applied to the subscriber.",
            "fields": "Custom field values stored for the subscriber.",
        },
    },
    "sequence_subscribers": {
        "description": "A subscriber enrolled in a sequence. This is the sequence-to-subscriber junction.",
        "docs_url": "https://developers.kit.com/api-reference/sequences/list-subscribers-for-a-sequence",
        "columns": {
            "sequence_id": "Identifier of the sequence the subscriber is enrolled in.",
            "id": "Unique identifier for the subscriber.",
            "first_name": "First name of the subscriber.",
            "email_address": "Email address of the subscriber.",
            "state": "State of the subscriber (active, inactive, bounced, complained, cancelled).",
            "created_at": "Date and time the subscriber was created.",
            "added_at": "Date and time the subscriber entered the sequence.",
            "fields": "Custom field values stored for the subscriber.",
        },
    },
    "segments": {
        "description": "A segment — a saved group of subscribers, created and managed in the Kit app.",
        "docs_url": "https://developers.kit.com/api-reference/segments/list-segments",
        "columns": {
            "id": "Unique identifier for the segment.",
            "name": "Name of the segment.",
            "created_at": "Date and time the segment was created.",
        },
    },
    "growth_stats": {
        "description": "Account-wide subscriber growth over a date range. Kit defaults to the last 90 days and reports the bounds in the account's sending time zone, not UTC.",
        "docs_url": "https://developers.kit.com/api-reference/accounts/get-growth-stats",
        "columns": {
            "starting": "Start of the period the stats cover.",
            "ending": "End of the period the stats cover.",
            "subscribers": "Total subscribers on the account at the end of the period.",
            "new_subscribers": "Subscribers gained during the period.",
            "cancellations": "Subscribers who unsubscribed during the period.",
            "net_new_subscribers": "New subscribers minus cancellations for the period.",
        },
    },
    "sequence_emails": {
        "description": "An individual email inside a sequence, one step on the journey subscribers take through it.",
        "docs_url": "https://developers.kit.com/api-reference/sequence-emails/list-sequence-emails",
        "columns": {
            "sequence_id": "Identifier of the sequence the email belongs to.",
            "id": "Unique identifier for the sequence email.",
            "subject": "Subject line of the email.",
            "preview_text": "Preview text shown next to the subject in the inbox.",
            "email_address": "Address the email is sent from.",
            "email_template_id": "Identifier of the email template the email uses.",
            "published": "Whether the email is live and sent to subscribers.",
            "position": "Order of the email within the sequence.",
            "delay_value": "How long to wait before sending, in units of delay_unit.",
            "delay_unit": "Unit the delay is measured in (for example days or hours).",
            "send_days": "Days of the week the email is allowed to send on.",
        },
    },
    "broadcast_clicks": {
        "description": "Click performance for one link in a broadcast.",
        "docs_url": "https://developers.kit.com/api-reference/broadcasts/get-link-clicks-for-a-broadcast",
        "columns": {
            "broadcast_id": "Identifier of the broadcast the link appeared in.",
            "id": "Unique identifier for the link.",
            "url": "Destination the link points to.",
            "unique_clicks": "Number of subscribers who clicked the link at least once.",
            "click_to_delivery_rate": "Percentage of delivered emails whose recipient clicked the link.",
            "click_to_open_rate": "Percentage of opened emails whose recipient clicked the link.",
        },
    },
}
