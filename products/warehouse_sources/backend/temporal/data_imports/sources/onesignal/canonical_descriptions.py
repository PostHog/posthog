from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "notifications": {
        "description": (
            "Push, email, and SMS messages with delivery and engagement totals. "
            "API messages have 30-day retention. Journey messages are excluded."
        ),
        "docs_url": "https://documentation.onesignal.com/reference/view-messages",
        "columns": {
            "id": "Unique message identifier.",
            "app_id": "Identifier of the OneSignal app that sent the message.",
            "name": "Internal message name.",
            "contents": "Message text for each language.",
            "queued_at": "Unix timestamp when OneSignal created the message.",
            "send_after": "Unix timestamp of the scheduled delivery time.",
            "completed_at": "Unix timestamp when OneSignal completed delivery.",
            "successful": "Number of successful message deliveries.",
            "failed": "Number of failed message deliveries.",
            "converted": "Number of push notification clicks.",
            "remaining": "Number of subscriptions that await delivery.",
        },
    },
    "segments": {
        "description": "Audience segment metadata, including names, creation times, and status. Excludes filters and audience members.",
        "docs_url": "https://documentation.onesignal.com/reference/view-segments",
        "columns": {
            "id": "Unique segment identifier.",
            "app_id": "Identifier of the OneSignal app that owns the segment.",
            "name": "Internal segment name.",
            "description": "Segment description, if set.",
            "created_at": "Time when OneSignal created the segment.",
            "updated_at": "Time when OneSignal last updated the segment.",
            "read_only": "Whether the segment is read-only.",
            "is_active": "Whether the segment is active and available for sending messages.",
        },
    },
}
