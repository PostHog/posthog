"""Canonical, documentation-sourced descriptions for Guru endpoints and columns.

Sourced from the official Guru API reference (https://developer.getguru.com/reference). Keyed by the
endpoint names in `settings.py` `GURU_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Guru table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "cards": {
        "description": "A knowledge card (article) in Guru, the core unit of documented knowledge.",
        "docs_url": "https://developer.getguru.com/reference/getv1searchquery",
        "columns": {
            "id": "Unique identifier for the card.",
            "preferredPhrase": "Title of the card.",
            "content": "HTML content of the card.",
            "collection": "The collection the card belongs to.",
            "owner": "The user who owns the card.",
            "verificationState": "Whether the card is trusted, needs verification, etc.",
            "verificationInterval": "How often the card must be re-verified, in days.",
            "lastVerified": "Time at which the card was last verified.",
            "lastModified": "Time at which the card was last modified.",
            "lastModifiedBy": "The user who last modified the card.",
            "dateCreated": "Time at which the card was created.",
            "boards": "Boards the card is organized under.",
            "tags": "Tags applied to the card.",
            "shareStatus": "Sharing scope of the card (e.g. team, author).",
        },
    },
    "collections": {
        "description": "A collection — a top-level grouping of cards in Guru, owned by a group.",
        "docs_url": "https://developer.getguru.com/reference/getv1collections",
        "columns": {
            "id": "Unique identifier for the collection.",
            "name": "Name of the collection.",
            "description": "Description of the collection.",
            "color": "Display color of the collection.",
            "collectionType": "Type of the collection (e.g. internal, external).",
            "publicCardsEnabled": "Whether public cards are enabled for the collection.",
            "roiEnabled": "Whether ROI tracking is enabled for the collection.",
            "cards": "Number of cards in the collection.",
            "dateCreated": "Time at which the collection was created.",
        },
    },
    "groups": {
        "description": "A group of users in Guru used to control access to collections.",
        "docs_url": "https://developer.getguru.com/reference/getv1groups",
        "columns": {
            "id": "Unique identifier for the group.",
            "name": "Name of the group.",
            "modifiable": "Whether the group can be modified.",
            "dateCreated": "Time at which the group was created.",
            "numberOfMembers": "Number of members in the group.",
        },
    },
    "members": {
        "description": "A member (user) of the Guru team.",
        "docs_url": "https://developer.getguru.com/reference/getv1members",
        "columns": {
            "email": "Email address of the member (used as the primary key).",
            "user": "The underlying user object for the member.",
            "status": "Account status of the member (e.g. active, invited).",
            "dateCreated": "Time at which the member was added.",
            "lastSeen": "Time the member was last active.",
            "groups": "Groups the member belongs to.",
        },
    },
}
