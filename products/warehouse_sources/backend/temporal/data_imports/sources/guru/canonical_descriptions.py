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
    "group_members": {
        "description": "Membership of a user in a Guru group, one row per group and member.",
        "docs_url": "https://developer.getguru.com/reference/getv1groupsgetgroupmembers",
        "columns": {
            "group_id": "ID of the group the member belongs to.",
            "email": "Email address of the member.",
            "id": "ID of the group member.",
            "user": "The underlying user object for the member.",
            "dateCreated": "Time at which the member was added to the group.",
            "managedByScim": "Whether the membership is managed by SCIM provisioning.",
        },
    },
    "folders": {
        "description": "A folder that organizes cards inside a collection.",
        "docs_url": "https://developer.getguru.com/reference/getv1foldersgetfolders",
        "columns": {
            "id": "Unique identifier for the folder.",
            "title": "Title of the folder.",
            "description": "Optional short description of the folder.",
            "slug": "URL slug of the folder.",
            "collection": "The collection the folder belongs to.",
            "home": "Whether this folder is the top level folder for its collection.",
            "lastModified": "Time at which the folder was last modified.",
            "lastModifiedBy": "The user who last modified the folder.",
            "numberOfFacts": "Number of cards in the folder.",
            "groupsSharedWith": "Groups the folder is shared with.",
        },
    },
    "folder_items": {
        "description": "A card or subfolder that sits directly inside a folder, one row per folder and item.",
        "docs_url": "https://developer.getguru.com/reference/getv1foldersgetfolderitems",
        "columns": {
            "folder_id": "ID of the folder that contains the item.",
            "id": "ID of the card or subfolder.",
            "itemId": "ID of the item placement within the folder.",
            "type": "Kind of item: card or folder.",
        },
    },
    "tag_categories": {
        "description": "A tag category that groups related tags for the team.",
        "docs_url": "https://developer.getguru.com/reference/getv1teamstagcategoriesgettagcategories",
        "columns": {
            "id": "Unique identifier for the tag category.",
            "name": "Name of the tag category.",
            "defaultCategory": "Whether this is the default tag category.",
            "createdBy": "The user who created the tag category.",
            "dateCreated": "Time at which the tag category was created.",
            "tags": "Tags in the category.",
        },
    },
    "tags": {
        "description": "A tag that labels cards, one row per tag, taken from its tag category.",
        "docs_url": "https://developer.getguru.com/reference/getv1teamstagcategoriesgettagcategories",
        "columns": {
            "id": "Unique identifier for the tag. Cards reference tags by this ID.",
            "value": "Name of the tag.",
            "categoryId": "ID of the tag category the tag belongs to.",
            "categoryName": "Name of the tag category the tag belongs to.",
            "numberOfCards": "Number of cards that have the tag.",
        },
    },
    "analytics_events": {
        "description": "A usage event from the Guru analytics export, such as a card view, copy, or search.",
        "docs_url": "https://developer.getguru.com/docs/list-analytics-data",
        "columns": {
            "id": "Unique identifier for the event.",
            "type": "Type of the event (e.g. card-viewed, search).",
            "eventType": "Type of the event.",
            "eventDate": "Time at which the event occurred.",
            "user": "Email address of the user who performed the event.",
            "properties": "Event-specific properties. The most common is cardId, the card the event applies to.",
        },
    },
}
