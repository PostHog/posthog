from sources.sdk import CanonicalDescriptions

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
    "custom_objects": {
        "description": "Records of the customer-defined custom object types in Lightfield, across every type the API key can read.",
        "docs_url": "https://docs.lightfield.app/api/resources/object/methods/list/",
        "columns": {
            **_COMMON_COLUMNS,
            "objectType": "Slug of the custom object type the record belongs to.",
        },
    },
    "field_definitions": {
        "description": "Field definitions for each Lightfield object type, including system and custom fields. Resolves the field slugs used as keys in the fields map of each record.",
        "docs_url": "https://docs.lightfield.app/using-the-api/fields-and-relationships/",
        "columns": {
            "ownerObjectType": "Object type the field belongs to, such as account, contact, or a custom object slug.",
            "key": "Field key as it appears in the fields map of a record. System fields start with $.",
            "id": "Unique identifier of the field definition.",
            "label": "Human-readable display name of the field.",
            "description": "Description of the field, or null.",
            "valueType": "Data type of the field, such as TEXT, NUMBER, CURRENCY, or SINGLE_SELECT.",
            "typeConfiguration": "Type-specific configuration, such as select options, currency code, or uniqueness.",
            "readOnly": "True for fields that the API cannot write, such as AI-generated summaries.",
        },
    },
    "relationship_definitions": {
        "description": "Relationship definitions for each Lightfield object type. Resolves the relationship keys used in the relationships map of each record.",
        "docs_url": "https://docs.lightfield.app/using-the-api/fields-and-relationships/",
        "columns": {
            "ownerObjectType": "Object type the relationship belongs to, such as account, contact, or a custom object slug.",
            "objectType": "Type of the related object, such as account or contact.",
            "key": "Relationship key as it appears in the relationships map of a record. System relationships start with $.",
            "id": "Unique identifier of the relationship definition.",
            "label": "Human-readable display name of the relationship.",
            "description": "Description of the relationship, or null.",
            "cardinality": "Whether the relationship is HAS_ONE or HAS_MANY.",
            "directions": "Directional metadata for a self-referential relationship.",
        },
    },
}
