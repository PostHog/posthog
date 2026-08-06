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
}
