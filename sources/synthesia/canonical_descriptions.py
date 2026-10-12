from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "videos": {
        "description": "Videos created through the Synthesia API or Studio that the API key can access.",
        "docs_url": "https://docs.synthesia.io/reference/list-videos",
        "columns": {
            "id": "Unique video identifier.",
            "createdAt": "Video creation time as a Unix timestamp.",
            "lastUpdatedAt": "Time of the last video update.",
            "title": "Video title displayed on its share page.",
            "description": "Video description displayed on its share page.",
            "status": "Video processing or review status.",
            "visibility": "Whether the video share page is public or private.",
            "callbackId": "Identifier supplied to link the video to its creation request.",
            "test": "Whether the video uses test mode with a watermark.",
        },
    },
    "templates": {
        "description": "Synthesia and workspace templates available to the API key, including their variables.",
        "docs_url": "https://docs.synthesia.io/reference/list-templates",
        "columns": {
            "id": "Unique template identifier.",
            "title": "Template title.",
            "description": "Template description.",
            "variables": "Variables accepted when creating a video from this template.",
            "createdAt": "Template creation time.",
            "lastUpdatedAt": "Time of the last template update.",
        },
    },
    "webhooks": {
        "description": "Active webhook subscriptions for the account that owns the API key. Signing secrets are excluded.",
        "docs_url": "https://docs.synthesia.io/reference/list-webhooks",
        "columns": {
            "id": "Unique webhook identifier.",
            "url": "Destination URL for webhook notifications.",
            "status": "Webhook status.",
            "createdAt": "Webhook creation time.",
            "lastUpdatedAt": "Time of the last webhook update.",
        },
    },
}
