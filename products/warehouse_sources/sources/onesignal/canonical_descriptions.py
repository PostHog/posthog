from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "templates": {
        "description": "Push, email, and SMS message templates with names and timestamps. Excludes template content.",
        "docs_url": "https://documentation.onesignal.com/reference/view-templates",
        "columns": {
            "id": "Unique template identifier. Notifications reference it as template_id.",
            "name": "Internal template name.",
            "created_at": "Time when OneSignal created the template.",
            "updated_at": "Time when OneSignal last updated the template.",
        },
    },
    "journeys": {
        "description": (
            "Journeys (automated messaging flows) with their state, schedule, and audience kind. "
            "Excludes nodes and the full audience definition."
        ),
        "docs_url": "https://documentation.onesignal.com/reference/view-journeys",
        "columns": {
            "id": "Unique journey identifier.",
            "app_id": "Identifier of the OneSignal app that owns the journey.",
            "name": "Internal journey name.",
            "state": "Journey state: draft, scheduled, processing, active, or archived.",
            "created_at": "Time when OneSignal created the journey.",
            "updated_at": "Time when OneSignal last updated the journey.",
            "started_at": "Time when the journey became active, if active.",
            "archived_at": "Time when the journey was archived, if archived.",
            "created_source": "Where the journey was created, such as the dashboard or the API.",
            "schedule": "Start and end schedule of the journey, if set.",
            "audience": "Entry audience of the journey. Holds only its kind: segment or event_trigger.",
            "reentry_rules": "Rules that control if a user can enter the journey again.",
        },
    },
    "journey_stats": {
        "description": (
            "All-time counts for each journey, with counts per node and per branch "
            "and delivery totals for message nodes. One row per journey."
        ),
        "docs_url": "https://documentation.onesignal.com/reference/view-journey-stats",
        "columns": {
            "id": "Identifier of the journey these stats belong to.",
            "started": "Number of users who entered the journey.",
            "completed": "Number of users who reached the end of the journey.",
            "exited_early": "Number of users who left the journey through an early exit rule.",
            "nodes": "Counts for each node, keyed by node identifier. Message nodes include delivery totals.",
            "branches": "Number of users who took each branch, keyed by branch identifier.",
        },
    },
}
