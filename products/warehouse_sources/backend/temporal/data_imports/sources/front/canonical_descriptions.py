"""Canonical, documentation-sourced descriptions for Front endpoints and columns.

Sourced from the official Front API reference (https://dev.frontapp.com/reference). Keyed by the
endpoint names in `settings.py` `FRONT_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Front table. Front timestamps are Unix epoch seconds. Columns absent here fall back to LLM
enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "An activity event in Front, such as a conversation being assigned, tagged, or moved.",
        "docs_url": "https://dev.frontapp.com/reference/events",
        "columns": {
            "id": "Unique identifier for the event.",
            "type": "Type of the event (e.g. assign, archive, inbound, comment).",
            "emitted_at": "Time at which the event was emitted, as Unix epoch seconds.",
            "conversation": "The conversation the event relates to.",
            "source": "The actor or system that triggered the event.",
            "target": "The object affected by the event.",
        },
    },
    "contacts": {
        "description": "A person or company in Front's contact directory, with their handles across channels.",
        "docs_url": "https://dev.frontapp.com/reference/contacts",
        "columns": {
            "id": "Unique identifier for the contact.",
            "name": "The contact's name.",
            "description": "Description of the contact.",
            "handles": "List of the contact's handles (email, phone, etc.) across channels.",
            "groups": "Contact groups the contact belongs to.",
            "is_private": "Whether the contact is private to its owner.",
            "is_spammer": "Whether the contact is marked as a spammer.",
            "links": "External links associated with the contact.",
            "custom_fields": "Custom field values set on the contact.",
            "updated_at": "Time at which the contact was last updated, as Unix epoch seconds.",
        },
    },
    "conversations": {
        "description": "A thread of messages and comments in Front, the core unit of work in an inbox.",
        "docs_url": "https://dev.frontapp.com/reference/conversations",
        "columns": {
            "id": "Unique identifier for the conversation.",
            "subject": "Subject of the conversation.",
            "status": "Status of the conversation (e.g. open, archived, deleted, spam).",
            "assignee": "The teammate the conversation is assigned to, if any.",
            "recipient": "The primary recipient of the conversation.",
            "tags": "Tags applied to the conversation.",
            "links": "External links associated with the conversation.",
            "created_at": "Time at which the conversation was created, as Unix epoch seconds.",
            "is_private": "Whether the conversation is a private discussion.",
            "scheduled_reminders": "Reminders scheduled on the conversation.",
        },
    },
    "accounts": {
        "description": "A company account in Front, grouping related contacts together.",
        "docs_url": "https://dev.frontapp.com/reference/accounts",
        "columns": {
            "id": "Unique identifier for the account.",
            "name": "The account's name.",
            "description": "Description of the account.",
            "domains": "Email domains associated with the account.",
            "external_id": "External identifier set on the account.",
            "custom_fields": "Custom field values set on the account.",
            "created_at": "Time at which the account was created, as Unix epoch seconds.",
            "updated_at": "Time at which the account was last updated, as Unix epoch seconds.",
        },
    },
    "tags": {
        "description": "A label that can be applied to conversations to categorize them.",
        "docs_url": "https://dev.frontapp.com/reference/tags",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "The tag's name.",
            "highlight": "Highlight color of the tag.",
            "is_private": "Whether the tag is private to its owner.",
            "is_visible_in_conversation_lists": "Whether the tag is shown in conversation lists.",
            "created_at": "Time at which the tag was created, as Unix epoch seconds.",
            "updated_at": "Time at which the tag was last updated, as Unix epoch seconds.",
        },
    },
    "teammates": {
        "description": "A user (teammate) in the Front workspace.",
        "docs_url": "https://dev.frontapp.com/reference/teammates",
        "columns": {
            "id": "Unique identifier for the teammate.",
            "email": "The teammate's email address.",
            "username": "The teammate's username.",
            "first_name": "The teammate's first name.",
            "last_name": "The teammate's last name.",
            "is_admin": "Whether the teammate is an admin of the workspace.",
            "is_available": "Whether the teammate is currently available.",
            "is_blocked": "Whether the teammate is blocked.",
        },
    },
    "inboxes": {
        "description": "A shared inbox that receives and organizes conversations.",
        "docs_url": "https://dev.frontapp.com/reference/inboxes",
        "columns": {
            "id": "Unique identifier for the inbox.",
            "name": "The inbox's name.",
            "is_private": "Whether the inbox is private to specific teammates.",
        },
    },
    "channels": {
        "description": "A communication channel (email, SMS, etc.) connected to an inbox.",
        "docs_url": "https://dev.frontapp.com/reference/channels",
        "columns": {
            "id": "Unique identifier for the channel.",
            "name": "The channel's name.",
            "address": "Address (e.g. email address) the channel sends and receives from.",
            "type": "Type of the channel (e.g. smtp, imap, twilio, custom).",
            "send_as": "Address used in the From field when sending from the channel.",
            "is_private": "Whether the channel is private.",
            "is_valid": "Whether the channel is currently valid and operational.",
        },
    },
    "teams": {
        "description": "A team in the Front workspace that owns inboxes and teammates.",
        "docs_url": "https://dev.frontapp.com/reference/teams",
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "The team's name.",
            "inboxes": "Inboxes that belong to the team.",
            "members": "Teammates that belong to the team.",
        },
    },
}
