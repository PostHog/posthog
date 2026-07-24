from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "object_types": {
        "description": "A legacy custom object type: a user-defined data model (key plus JSON schema) that legacy object records are validated against.",
        "docs_url": "https://developer.zendesk.com/api-reference/custom-data/custom-objects-api/resource_types/",
        "columns": {
            "key": "Unique, user-defined identifier for the object type.",
            "schema": "JSON schema describing the object type's properties and which of them are required.",
            "created_at": "When the object type was created.",
            "updated_at": "When the object type was last updated.",
        },
    },
    "object_records": {
        "description": "A legacy custom object record: an instance of a legacy object type holding the record's data in its attributes.",
        "docs_url": "https://developer.zendesk.com/api-reference/custom-data/custom-objects-api/resources/",
        "columns": {
            "id": "Unique identifier of the record, assigned automatically on creation.",
            "type": "Key of the legacy object type this record belongs to.",
            "external_id": "Unique, case-insensitive identifier from another system, if one was supplied on creation.",
            "attributes": "The record's data, validated against the object type's schema (up to 32 KB).",
            "type_version": "Version of the record's object type the record was validated against.",
            "created_at": "When the record was created.",
            "updated_at": "When the record was last updated.",
        },
    },
    "object_type_policies": {
        "description": "Role-based access permissions for one legacy object type: what admins, agents, and end users may create, read, update, or delete.",
        "docs_url": "https://developer.zendesk.com/api-reference/custom-data/custom-objects-api/permissions/",
        "columns": {
            "object_type": "Key of the legacy object type the policy applies to.",
            "rbac": "Role-based access control rules per role (admin, agent, end_user) and operation (create, read, update, delete).",
        },
    },
    "relationship_types": {
        "description": "A legacy relationship type: defines how records of one object type relate to records of another object type or to standard Zendesk objects.",
        "docs_url": "https://developer.zendesk.com/api-reference/custom-data/custom-objects-api/relationship_types/",
        "columns": {
            "key": "Unique, user-defined identifier for the relationship type.",
            "source": "Object type (or standard Zendesk object) allowed as the relationship's source.",
            "target": "Object type (or standard Zendesk object) allowed as the relationship's target.",
            "created_at": "When the relationship type was created.",
            "updated_at": "When the relationship type was last updated.",
        },
    },
    "relationship_records": {
        "description": "A legacy relationship record: an association between a source record and a target record of a given relationship type. Immutable after creation.",
        "docs_url": "https://developer.zendesk.com/api-reference/custom-data/custom-objects-api/relationships/",
        "columns": {
            "id": "Unique identifier of the relationship record, assigned automatically on creation.",
            "relationship_type": "Key of the legacy relationship type this record belongs to.",
            "source": "Id of the source object record.",
            "target": "Id of the target object record.",
            "created_at": "When the relationship record was created.",
        },
    },
    "limits": {
        "description": "Account-level usage limits for legacy custom objects, with the current count against each limit.",
        "docs_url": "https://developer.zendesk.com/api-reference/custom-data/custom-objects-api/limits/",
        "columns": {
            "key": "Identifier of the limit (for example the record limit).",
            "count": "Current usage counted against the limit.",
            "limit": "Maximum allowed by the account's plan.",
        },
    },
}
