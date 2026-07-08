from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Organizations",
    "Accounts",
    "Users",
    "Conversations",
    "Notes",
    "Projects",
    "Tasks",
    "NPS_Responses",
    "Custom_Objects",
    "Messages",
)

# Prefix used for schemas that sync the *instances* of a Vitally custom object.
# The `Custom_Objects` static endpoint syncs the definitions; one schema per object
# (named `Custom_Object_<machineName>`) syncs each object's actual records.
CUSTOM_OBJECT_SCHEMA_PREFIX = "Custom_Object_"

# Standard updated_at incremental field shared across all Vitally endpoints that
# expose an `updatedAt` server-side filter (which includes custom-object instances).
UPDATED_AT_INCREMENTAL_FIELD: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "updated_at",
    "field_type": IncrementalFieldType.DateTime,
}

INCREMENTAL_ENDPOINTS = (
    "Organizations",
    "Accounts",
    "Users",
    "Conversations",
    "Notes",
    "Projects",
    "Tasks",
    "NPS_Responses",
    "Custom_Objects",
    "Messages",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Organizations": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Accounts": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Users": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Conversations": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Notes": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Projects": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Tasks": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "NPS_Responses": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Custom_Fields": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Custom_Objects": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Messages": [
        {
            "label": "conversation_updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "conversation_updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
