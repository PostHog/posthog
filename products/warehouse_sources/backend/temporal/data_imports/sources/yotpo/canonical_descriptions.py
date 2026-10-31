from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "reviews": {
        "description": "Product and site reviews submitted to the store.",
        "docs_url": "https://apidocs.yotpo.com/reference/retrieve-all-reviews",
        "columns": {
            "id": "The Yotpo review ID.",
            "created_at": "The time the review was created.",
            "updated_at": "The time the review was last updated.",
            "score": "The review's star rating.",
            "sku": "The product SKU associated with the review.",
            "deleted": "Whether the review is unpublished.",
        },
    },
    "email_analytics": {
        "description": "Daily counts of emails sent, grouped by email type.",
        "docs_url": "https://apidocs.yotpo.com/reference/email-analytics",
        "columns": {
            "since": "The first date included in this reporting period.",
            "until": "The last date included in this reporting period.",
            "values": "Email counts grouped by email type.",
        },
    },
    "raw_data": {
        "description": "Email delivery and engagement records.",
        "docs_url": "https://apidocs.yotpo.com/reference/raw-data",
        "columns": {
            "email_address": "The recipient's email address.",
            "email_type": "The type of email sent by Yotpo.",
            "email_sent_timestamp": "The time Yotpo sent the email.",
            "opened_timestamp": "The time the recipient opened the email.",
            "unsubscribed_timestamp": "The time the recipient unsubscribed.",
        },
    },
    "unsubscribers": {
        "description": "Email addresses excluded from Yotpo email distribution lists.",
        "docs_url": "https://apidocs.yotpo.com/reference/retrieve-a-list-of-unsubscribers",
        "columns": {
            "user_email": "The unsubscribed email address.",
            "email_type_id": "The email distribution list identifier.",
            "unsubscribed_by_name": "Who requested the unsubscribe action.",
        },
    },
}
