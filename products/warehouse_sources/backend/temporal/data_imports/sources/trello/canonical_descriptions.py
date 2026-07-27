"""Canonical, documentation-sourced descriptions for Trello endpoints and columns.

Sourced from the official Trello REST API reference (https://developer.atlassian.com/cloud/trello/rest).
Keyed by the endpoint names in `settings.py` `TRELLO_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Trello table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "boards": {
        "description": "A Trello board that organizes lists and cards for a project.",
        "docs_url": "https://developer.atlassian.com/cloud/trello/rest/api-group-boards/",
        "columns": {
            "id": "Unique identifier for the board.",
            "name": "The board's name.",
            "desc": "Description of the board.",
            "closed": "Whether the board is archived (closed).",
            "idOrganization": "ID of the workspace (organization) the board belongs to.",
            "url": "URL of the board.",
            "shortUrl": "Shortened URL of the board.",
            "starred": "Whether the board is starred by the authenticated member.",
            "dateLastActivity": "Time of the most recent activity on the board.",
            "created_at": "Time at which the board was created (derived from its ID).",
        },
    },
    "organizations": {
        "description": "A Trello workspace (organization) that groups boards and members.",
        "docs_url": "https://developer.atlassian.com/cloud/trello/rest/api-group-organizations/",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "The workspace's short name (unique identifier slug).",
            "displayName": "The workspace's display name.",
            "desc": "Description of the workspace.",
            "url": "URL of the workspace.",
            "website": "Website associated with the workspace.",
            "created_at": "Time at which the workspace was created (derived from its ID).",
        },
    },
    "lists": {
        "description": "A list (column) on a board that holds an ordered set of cards.",
        "docs_url": "https://developer.atlassian.com/cloud/trello/rest/api-group-lists/",
        "columns": {
            "id": "Unique identifier for the list.",
            "name": "The list's name.",
            "idBoard": "ID of the board the list belongs to.",
            "closed": "Whether the list is archived (closed).",
            "pos": "Position of the list on the board.",
            "subscribed": "Whether the authenticated member is subscribed to the list.",
            "created_at": "Time at which the list was created (derived from its ID).",
        },
    },
    "cards": {
        "description": "A card on a board, representing a task or item that moves through lists.",
        "docs_url": "https://developer.atlassian.com/cloud/trello/rest/api-group-cards/",
        "columns": {
            "id": "Unique identifier for the card.",
            "name": "The card's name (title).",
            "desc": "Description of the card.",
            "idBoard": "ID of the board the card belongs to.",
            "idList": "ID of the list the card currently sits in.",
            "idMembers": "IDs of the members assigned to the card.",
            "idLabels": "IDs of the labels applied to the card.",
            "closed": "Whether the card is archived (closed).",
            "due": "Due date set on the card, if any.",
            "dueComplete": "Whether the card's due date has been marked complete.",
            "pos": "Position of the card within its list.",
            "url": "URL of the card.",
            "shortUrl": "Shortened URL of the card.",
            "dateLastActivity": "Time of the most recent activity on the card.",
            "created_at": "Time at which the card was created (derived from its ID).",
        },
    },
    "checklists": {
        "description": "A checklist attached to a card, containing a set of check items.",
        "docs_url": "https://developer.atlassian.com/cloud/trello/rest/api-group-checklists/",
        "columns": {
            "id": "Unique identifier for the checklist.",
            "name": "The checklist's name.",
            "idBoard": "ID of the board the checklist belongs to.",
            "idCard": "ID of the card the checklist is attached to.",
            "pos": "Position of the checklist on the card.",
            "checkItems": "Array of check items in the checklist.",
            "created_at": "Time at which the checklist was created (derived from its ID).",
        },
    },
    "labels": {
        "description": "A label that can be applied to cards on a board for categorization.",
        "docs_url": "https://developer.atlassian.com/cloud/trello/rest/api-group-labels/",
        "columns": {
            "id": "Unique identifier for the label.",
            "name": "The label's name.",
            "color": "The label's color.",
            "idBoard": "ID of the board the label belongs to.",
            "created_at": "Time at which the label was created (derived from its ID).",
        },
    },
    "members": {
        "description": "A Trello member who belongs to a board.",
        "docs_url": "https://developer.atlassian.com/cloud/trello/rest/api-group-members/",
        "columns": {
            "id": "Unique identifier for the member.",
            "fullName": "The member's full name.",
            "username": "The member's username.",
            "initials": "The member's initials.",
            "email": "The member's email address, if visible.",
            "url": "URL of the member's profile.",
            "created_at": "Time at which the member was created (derived from its ID).",
        },
    },
    "actions": {
        "description": "An action recording an event that happened on a board (e.g. a card moved or comment added).",
        "docs_url": "https://developer.atlassian.com/cloud/trello/rest/api-group-actions/",
        "columns": {
            "id": "Unique identifier for the action.",
            "type": "Type of the action (e.g. createCard, updateCard, commentCard, moveCardToBoard).",
            "date": "Time at which the action occurred.",
            "idMemberCreator": "ID of the member who performed the action.",
            "memberCreator": "Details of the member who performed the action.",
            "data": "Payload describing what the action did (board, list, card references, etc.).",
            "created_at": "Time at which the action was created (derived from its ID).",
        },
    },
}
