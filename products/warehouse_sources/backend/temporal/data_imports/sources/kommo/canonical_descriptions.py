"""Canonical, documentation-sourced descriptions for Kommo API v4 endpoints and columns.

Sourced from the official Kommo developer reference (https://developers.kommo.com/reference).
Keyed by the endpoint names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Kommo table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields Kommo repeats across most entities, merged into each entry rather than restated.
_COMMON_COLUMNS = {
    "id": "Unique identifier of the entity within the Kommo account.",
    "account_id": "Identifier of the Kommo account the entity belongs to.",
    "created_at": "When the entity was created, as a Unix timestamp.",
    "updated_at": "When the entity was last changed, as a Unix timestamp.",
    "created_by": "Identifier of the user who created the entity. 0 when it was created by an integration.",
    "updated_by": "Identifier of the user who last changed the entity. 0 when it was changed by an integration.",
    "responsible_user_id": "Identifier of the user the entity is assigned to.",
    "group_id": "Identifier of the team the responsible user belongs to.",
    "custom_fields_values": "Custom field values as a list of {field_id, field_name, field_code, field_type, values}.",
    "_embedded": "Related records returned because of the `with` request parameter, such as linked contacts or tags.",
    "_links": "HAL links for the record, including its own API URL.",
}

_NOTE_COLUMNS = {
    **_COMMON_COLUMNS,
    "entity_id": "Identifier of the lead, contact, or company the note is attached to.",
    "note_type": "Kind of note, for example common, call_in, call_out, or attachment.",
    "params": "Note payload, whose keys depend on `note_type` (text, call duration, file metadata, and so on).",
    "is_pinned": "Whether the note is pinned to the top of the entity's feed.",
}

_TAG_COLUMNS = {
    "id": "Unique identifier of the tag.",
    "name": "Tag name as shown in the interface.",
    "color": "Tag color as a hex value, or null when the tag has no color set.",
}

_CUSTOM_FIELD_COLUMNS = {
    "id": "Unique identifier of the custom field.",
    "name": "Custom field name as shown in the interface.",
    "code": "Field code, used to address predefined fields through the API.",
    "sort": "Position of the field in the entity card.",
    "type": "Field type, for example text, numeric, select, multiselect, date, or price.",
    "entity_type": "Entity the field belongs to (leads, contacts, or companies).",
    "is_predefined": "Whether the field is one of Kommo's built-in fields.",
    "is_deletable": "Whether the field can be deleted.",
    "is_api_only": "Whether the field can only be changed through the API.",
    "group_id": "Identifier of the field group the field is shown in.",
    "enums": "Available values for select-style fields, each with an id, value, and sort order.",
    "required_statuses": "Pipeline stages that require this field to be filled in.",
    "hidden_statuses": "Pipeline stages that hide this field.",
    "currency": "Currency of the field, for monetary field types.",
    "account_id": "Identifier of the Kommo account the field belongs to.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Leads": {
        "description": "A sales opportunity moving through a Kommo pipeline, with its stage, price, and owner.",
        "docs_url": "https://developers.kommo.com/reference/leads-list",
        "columns": {
            **_COMMON_COLUMNS,
            "name": "Lead name.",
            "price": "Lead value in the account's currency.",
            "status_id": "Identifier of the pipeline stage the lead currently sits in.",
            "pipeline_id": "Identifier of the pipeline the lead belongs to.",
            "loss_reason_id": "Identifier of the loss reason, set when the lead was marked as lost.",
            "closed_at": "When the lead was closed as won or lost, as a Unix timestamp.",
            "closest_task_at": "Due date of the lead's nearest open task, as a Unix timestamp.",
            "is_deleted": "Whether the lead is in the recycle bin.",
            "score": "Lead score, when scoring is enabled for the account.",
            "labor_cost": "Time logged against the lead, in seconds.",
            "is_price_modified_by_robot": "Whether the lead price was last changed by a Salesbot.",
        },
    },
    "Contacts": {
        "description": "A person in the Kommo account, linked to the leads and companies they belong to.",
        "docs_url": "https://developers.kommo.com/reference/contacts-list",
        "columns": {
            **_COMMON_COLUMNS,
            "name": "Full contact name.",
            "first_name": "Contact's first name.",
            "last_name": "Contact's last name.",
            "closest_task_at": "Due date of the contact's nearest open task, as a Unix timestamp.",
            "is_deleted": "Whether the contact is in the recycle bin.",
        },
    },
    "Companies": {
        "description": "An organization in the Kommo account, linked to its contacts and leads.",
        "docs_url": "https://developers.kommo.com/reference/companies-list",
        "columns": {
            **_COMMON_COLUMNS,
            "name": "Company name.",
            "closest_task_at": "Due date of the company's nearest open task, as a Unix timestamp.",
            "is_deleted": "Whether the company is in the recycle bin.",
        },
    },
    "LeadNotes": {
        "description": "Notes and logged interactions attached to leads, including calls and system messages.",
        "docs_url": "https://developers.kommo.com/reference/notes-list-entity",
        "columns": _NOTE_COLUMNS,
    },
    "ContactNotes": {
        "description": "Notes and logged interactions attached to contacts.",
        "docs_url": "https://developers.kommo.com/reference/notes-list-entity",
        "columns": _NOTE_COLUMNS,
    },
    "CompanyNotes": {
        "description": "Notes and logged interactions attached to companies.",
        "docs_url": "https://developers.kommo.com/reference/notes-list-entity",
        "columns": _NOTE_COLUMNS,
    },
    "Tasks": {
        "description": "A to-do assigned to a user against a lead, contact, or company.",
        "docs_url": "https://developers.kommo.com/reference/tasks-list",
        "columns": {
            **_COMMON_COLUMNS,
            "entity_id": "Identifier of the lead, contact, or company the task is attached to.",
            "entity_type": "Type of entity the task is attached to (leads, contacts, or companies).",
            "task_type_id": "Identifier of the task type, for example call or meeting.",
            "text": "Task description.",
            "duration": "Planned duration of the task, in seconds.",
            "is_completed": "Whether the task has been completed.",
            "result": "Result recorded when the task was completed.",
            "complete_till": "Deadline for the task, as a Unix timestamp.",
        },
    },
    "Events": {
        "description": "The account's change feed: stage moves, field edits, and other recorded actions.",
        "docs_url": "https://developers.kommo.com/reference/events-list",
        "columns": {
            "id": "Unique identifier of the event.",
            "type": "Event type, for example lead_status_changed or sale_field_changed.",
            "entity_id": "Identifier of the entity the event happened to.",
            "entity_type": "Type of the entity the event happened to (lead, contact, company, task, or a catalog).",
            "created_by": "Identifier of the user who triggered the event. 0 when it was an integration.",
            "created_at": "When the event happened, as a Unix timestamp.",
            "value_before": "The changed values as they were before the event.",
            "value_after": "The changed values as they were after the event.",
            "account_id": "Identifier of the Kommo account the event belongs to.",
        },
    },
    "Pipelines": {
        "description": "A lead pipeline, with its stages returned under `_embedded.statuses`.",
        "docs_url": "https://developers.kommo.com/reference/pipelines-list",
        "columns": {
            "id": "Unique identifier of the pipeline.",
            "name": "Pipeline name.",
            "sort": "Position of the pipeline in the interface.",
            "is_main": "Whether this is the account's main pipeline.",
            "is_unsorted_on": "Whether the Incoming leads stage is enabled for this pipeline.",
            "is_archive": "Whether the pipeline is archived.",
            "account_id": "Identifier of the Kommo account the pipeline belongs to.",
            "_embedded": "Pipeline stages, each with id, name, sort, color, and type.",
        },
    },
    "Users": {
        "description": "A user of the Kommo account, with their access rights. Requires an admin token.",
        "docs_url": "https://developers.kommo.com/reference/users-list",
        "columns": {
            "id": "Unique identifier of the user.",
            "name": "User's full name.",
            "email": "User's email address, which is also their login.",
            "lang": "Interface language of the user.",
            "rights": "Per-entity access rights plus admin, active, and free-seat flags.",
            "_embedded": "Role and team returned because of the `with` request parameter.",
        },
    },
    "Catalogs": {
        "description": "A Kommo list (catalog), such as a product or supplier list.",
        "docs_url": "https://developers.kommo.com/reference/get-lists",
        "columns": {
            "id": "Unique identifier of the list.",
            "name": "List name.",
            "created_by": "Identifier of the user who created the list.",
            "updated_by": "Identifier of the user who last changed the list.",
            "created_at": "When the list was created, as a Unix timestamp.",
            "updated_at": "When the list was last changed, as a Unix timestamp.",
            "sort": "Position of the list in the interface.",
            "type": "List type, for example regular, products, or invoices.",
            "can_add_elements": "Whether elements can be added to the list.",
            "can_show_in_cards": "Whether the list can be shown in entity cards.",
            "can_link_multiple": "Whether several elements of the list can be linked to one entity.",
            "can_be_deleted": "Whether the list can be deleted.",
            "account_id": "Identifier of the Kommo account the list belongs to.",
        },
    },
    "LeadCustomFields": {
        "description": "Custom field definitions available on leads.",
        "docs_url": "https://developers.kommo.com/reference/custom-field-by-entity",
        "columns": _CUSTOM_FIELD_COLUMNS,
    },
    "ContactCustomFields": {
        "description": "Custom field definitions available on contacts.",
        "docs_url": "https://developers.kommo.com/reference/custom-field-by-entity",
        "columns": _CUSTOM_FIELD_COLUMNS,
    },
    "CompanyCustomFields": {
        "description": "Custom field definitions available on companies.",
        "docs_url": "https://developers.kommo.com/reference/custom-field-by-entity",
        "columns": _CUSTOM_FIELD_COLUMNS,
    },
    "LeadTags": {
        "description": "Tags that can be applied to leads.",
        "docs_url": "https://developers.kommo.com/reference/list-of-entity-tags",
        "columns": _TAG_COLUMNS,
    },
    "ContactTags": {
        "description": "Tags that can be applied to contacts.",
        "docs_url": "https://developers.kommo.com/reference/list-of-entity-tags",
        "columns": _TAG_COLUMNS,
    },
    "CompanyTags": {
        "description": "Tags that can be applied to companies.",
        "docs_url": "https://developers.kommo.com/reference/list-of-entity-tags",
        "columns": _TAG_COLUMNS,
    },
}
