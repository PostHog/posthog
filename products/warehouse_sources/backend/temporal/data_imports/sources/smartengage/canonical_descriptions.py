from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://smartengage.com/docs/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "avatars": {
        "description": "An avatar is a SmartEngage bot/brand persona, typically linked to a Facebook page. Tags, custom fields, and sequences are all scoped to an avatar.",
        "docs_url": _DOCS_URL,
        "columns": {
            "avatar_id": "Unique identifier for the avatar.",
            "brand_image": "URL of the brand image associated with the avatar.",
            "brand_name": "Name of the brand or company the avatar represents.",
            "facebook_page_id": "Identifier of the Facebook page linked to the avatar.",
            "user_role": "Role of the authenticated user on the avatar.",
        },
    },
    "tags": {
        "description": "Tags defined on an avatar, used to segment and trigger automations for subscribers.",
        "docs_url": _DOCS_URL,
        "columns": {
            "avatar_id": "Identifier of the avatar the tag belongs to.",
            "tag_id": "Unique identifier for the tag.",
            "tag_name": "Display name of the tag.",
        },
    },
    "custom_fields": {
        "description": "Custom subscriber profile fields defined on an avatar.",
        "docs_url": _DOCS_URL,
        "columns": {
            "avatar_id": "Identifier of the avatar the custom field belongs to.",
            "custom_field_id": "Unique identifier for the custom field.",
            "custom_field_name": "Display name of the custom field.",
        },
    },
    "sequences": {
        "description": "Automation sequences (drip campaigns) defined on an avatar.",
        "docs_url": _DOCS_URL,
        "columns": {
            "avatar_id": "Identifier of the avatar the sequence belongs to.",
            "sequence_id": "Unique identifier for the sequence.",
            "sequence_name": "Display name of the sequence.",
        },
    },
}
