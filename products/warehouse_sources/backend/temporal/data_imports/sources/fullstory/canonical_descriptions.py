"""Canonical, documentation-sourced descriptions for Fullstory endpoints and columns.

Sourced from the official Fullstory Server API v2 reference (https://developer.fullstory.com/server/v2/).
Keyed by the endpoint names in `fullstory.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Fullstory table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "A tracked end user in Fullstory, identified by your application's user id.",
        "docs_url": "https://developer.fullstory.com/server/v2/users/list-users/",
        "columns": {
            "id": "Fullstory-assigned unique identifier for the user.",
            "uid": "Application-specific user id you set when identifying the user.",
            "display_name": "Human-readable display name for the user.",
            "email": "Email address associated with the user.",
            "properties": "Set of custom key-value attributes attached to the user.",
            "is_being_deleted": "Whether the user is currently queued for deletion.",
            "created": "Time at which the user record was created in Fullstory.",
        },
    },
}
