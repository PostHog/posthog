from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_COMMON_COLUMNS = {
    "id": "Unique identifier for the record.",
    "createdAt": "Timestamp when the record was created in Lightfield.",
    "updatedAt": "Timestamp when the record was last updated in Lightfield.",
    "fields": "Map of the record's field values, keyed by field slug; each entry carries a value and its valueType.",
    "relationships": "Map of the record's relationships, keyed by relationship slug; each entry carries the cardinality, related object type, and related record IDs.",
    "httpLink": "URL of the record in the Lightfield web app.",
    "externalId": "Optional external identifier attached to the record via the API.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "Companies and organizations tracked in the Lightfield CRM.",
        "docs_url": "https://docs.lightfield.app/api/resources/account/methods/list/",
        "columns": _COMMON_COLUMNS,
    },
    "contacts": {
        "description": "People associated with accounts in the Lightfield CRM.",
        "docs_url": "https://docs.lightfield.app/api/resources/contact/methods/list/",
        "columns": _COMMON_COLUMNS,
    },
    "opportunities": {
        "description": "Sales opportunities (deals) tracked in the Lightfield CRM.",
        "docs_url": "https://docs.lightfield.app/api/resources/opportunity/methods/list/",
        "columns": _COMMON_COLUMNS,
    },
    "meetings": {
        "description": "Meetings recorded in Lightfield, including scheduling metadata and links to related records.",
        "docs_url": "https://docs.lightfield.app/api/resources/meeting/methods/list/",
        "columns": _COMMON_COLUMNS,
    },
    "tasks": {
        "description": "To-do items and follow-ups tracked in Lightfield.",
        "docs_url": "https://docs.lightfield.app/api/resources/task/methods/list/",
        "columns": _COMMON_COLUMNS,
    },
    "notes": {
        "description": "Free-form notes attached to records in Lightfield.",
        "docs_url": "https://docs.lightfield.app/api/resources/note/methods/list/",
        "columns": _COMMON_COLUMNS,
    },
    "lists": {
        "description": "Saved lists of accounts, contacts, or opportunities in Lightfield.",
        "docs_url": "https://docs.lightfield.app/api/resources/list/methods/list/",
        "columns": _COMMON_COLUMNS,
    },
    "members": {
        "description": "Members of the Lightfield organization (read-only).",
        "docs_url": "https://docs.lightfield.app/api/resources/member/methods/list/",
        "columns": _COMMON_COLUMNS,
    },
    "emails": {
        "description": "Emails synced from connected mailboxes. List items exclude the message body; subjects may be redacted for metadata-only access.",
        "docs_url": "https://docs.lightfield.app/api/resources/email/methods/list/",
        "columns": {
            **_COMMON_COLUMNS,
            "accessLevel": "Access level for the email content: FULL or METADATA.",
            "objectType": "Lightfield object type of the record.",
        },
    },
}
