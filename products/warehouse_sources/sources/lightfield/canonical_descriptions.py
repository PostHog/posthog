from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "messages": {
        "description": "Sequence and chat messages sent and received in Lightfield, limited to the channels the API key can see.",
        "docs_url": "https://docs.lightfield.app/api/resources/message/methods/list/",
        "columns": {
            **_COMMON_COLUMNS,
            "createdAt": "Timestamp when the message record was created in Lightfield. This is not the time the message was sent.",
            "accessLevel": "Access level for the message content: FULL or METADATA.",
            "objectType": "Lightfield object type of the record. Always message.",
        },
    },
    "sequences": {
        "description": "Outbound email and LinkedIn sequences in Lightfield, including sequences that were never published.",
        "docs_url": "https://docs.lightfield.app/api/resources/sequence/methods/list/",
        "columns": {
            "id": "Unique identifier of the sequence.",
            "name": "Name of the sequence.",
            "status": "Sequence status: DRAFT, ACTIVE, or DEACTIVATED.",
            "channels": "Channels the published steps send on (EMAIL, LINKEDIN). Empty before the first publish.",
            "createdAt": "Timestamp when the sequence was created.",
            "firstActivatedAt": "Timestamp when the sequence was first activated, or null.",
            "lastActivatedAt": "Timestamp when the sequence was last activated, or null.",
            "definition": "Published configuration: messaging, pacing, priority, send window, and steps. Null before the first publish.",
            "reviewers": "Members who review messages that need approval before sending.",
            "senders": "Senders the sequence sends from.",
            "objectType": "Lightfield object type of the record. Always sequence.",
        },
    },
    "sequence_enrollments": {
        "description": "Contacts enrolled in each Lightfield sequence, with their progress and outcome. Test runs are not included.",
        "docs_url": "https://docs.lightfield.app/api/resources/sequence/methods/listEnrollments/",
        "columns": {
            "sequenceId": "ID of the sequence the enrollment belongs to.",
            "id": "Unique identifier of the enrollment.",
            "contactId": "ID of the enrolled contact.",
            "status": "Enrollment status: ACTIVE, AWAITING_REVIEW, NEEDS_ATTENTION, REPLIED, COMPLETED, PAUSED, CANCELLED, or FAILED. Null for a few seconds while a change is indexed.",
            "currentStepId": "ID of the sequence step the contact is on, matching the step ids in the sequence definition.",
            "enrolledAt": "Timestamp when the contact was enrolled.",
            "enrolledBy": "Member ID of whoever enrolled the contact, or null for an automatic enrollment or a former member.",
            "lastActivityAt": "Timestamp of the latest activity on the enrollment, or null.",
            "lastActivityKind": "Latest activity on the enrollment: SENT, OPENED, REPLIED, BOUNCED, INVITED, CONNECTED, or SEEN.",
            "nextSendAt": "Estimated time of the next send, or null when it cannot be estimated.",
            "remainingSends": "Number of email and LinkedIn steps not yet sent.",
            "repliedAt": "Timestamp when the contact first replied, or null.",
            "completedAt": "Timestamp when the enrollment completed, or null.",
            "cancelledAt": "Timestamp when the enrollment was cancelled, or null.",
        },
    },
    "list_accounts": {
        "description": "Membership of account lists in Lightfield: one row for each account in each list, with the account record.",
        "docs_url": "https://docs.lightfield.app/api/resources/list/methods/listAccounts/",
        "columns": {
            **_COMMON_COLUMNS,
            "listId": "ID of the list that contains the record.",
            "id": "Unique identifier of the account that is a member of the list.",
        },
    },
    "list_contacts": {
        "description": "Membership of contact lists in Lightfield: one row for each contact in each list, with the contact record.",
        "docs_url": "https://docs.lightfield.app/api/resources/list/methods/listContacts/",
        "columns": {
            **_COMMON_COLUMNS,
            "listId": "ID of the list that contains the record.",
            "id": "Unique identifier of the contact that is a member of the list.",
        },
    },
    "list_opportunities": {
        "description": "Membership of opportunity lists in Lightfield: one row for each opportunity in each list, with the opportunity record.",
        "docs_url": "https://docs.lightfield.app/api/resources/list/methods/listOpportunities/",
        "columns": {
            **_COMMON_COLUMNS,
            "listId": "ID of the list that contains the record.",
            "id": "Unique identifier of the opportunity that is a member of the list.",
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
