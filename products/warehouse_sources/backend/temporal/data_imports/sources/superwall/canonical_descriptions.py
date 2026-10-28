from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "paywalls": {
        "description": "Paywalls for the application, including their products and presentation settings.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique paywall identifier.",
            "application_id": "Application that owns the paywall.",
            "created_at": "ISO 8601 timestamp when the paywall was created.",
            "updated_at": "ISO 8601 timestamp when the paywall was last updated.",
        },
    },
    "campaigns": {
        "description": "Campaigns for the application, including placements, audiences, and delivery settings.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique campaign identifier.",
            "application_id": "Application that owns the campaign.",
            "created_at": "ISO 8601 timestamp when the campaign was created.",
        },
    },
    "products": {
        "description": "Products for the project, including store identifiers, prices, and subscription details.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique product identifier.",
            "project_id": "Project that owns the product.",
            "created_at": "ISO 8601 timestamp when the product was created.",
        },
    },
    "entitlements": {
        "description": "Entitlements for the project and the products that provide them.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique entitlement identifier.",
            "project_id": "Project that owns the entitlement.",
            "created_at": "ISO 8601 timestamp when the entitlement was created.",
        },
    },
    "surveys": {
        "description": "Non-archived surveys for the application, including questions and response options.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique survey identifier.",
            "application_id": "Application that owns the survey.",
            "created_at": "ISO 8601 timestamp when the survey was created.",
        },
    },
    "webhook_events": {
        "description": "Webhook event messages retained for the project, including their payloads and delivery channels.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique webhook message identifier.",
            "event_id": "Identifier of the underlying event.",
            "event_type": "Type of event that triggered the message.",
            "timestamp": "Timestamp of the event message.",
            "payload": "Event message payload.",
        },
    },
}
