"""Canonical, documentation-sourced descriptions for Close endpoints and columns.

Sourced from the official Close API reference (https://developer.close.com/) and the source's
`api_inventory.md`. Keyed by the endpoint names in `settings.py` `CLOSE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Close table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
    CanonicalEndpoint,
)

# Fields shared by most Close objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "date_created": "Time at which the object was created.",
    "date_updated": "Time at which the object was last updated.",
    "organization_id": "ID of the Close organization the object belongs to.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


# Custom field definitions share one shape across every object type they attach to.
def _custom_field_columns(**overrides: str) -> dict[str, str]:
    return _columns(
        name="The custom field's name, as shown in Close.",
        description="Free-form description of the custom field.",
        type="Data type of the field, for example text, number, date or user.",
        choices="Allowed values, for a choices field.",
        accepts_multiple_values="Whether the field can hold more than one value.",
        editable_with_roles="Roles allowed to edit the field. Empty means every role can.",
        created_by="ID of the user who created the custom field.",
        updated_by="ID of the user who last updated the custom field.",
        **overrides,
    )


def _custom_field_table(object_type: str, table: str) -> CanonicalEndpoint:
    return {
        "description": (
            f"A {object_type} custom field definition. Resolves the opaque custom.cf_* keys "
            f"carried on the {table} rows."
        ),
        "docs_url": f"https://developer.close.com/api/resources/custom-fields/custom-fields-{object_type}/",
        "columns": _custom_field_columns(),
    }


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Leads": {
        "description": "A lead — a company or person being sold to, the central CRM record in Close.",
        "docs_url": "https://developer.close.com/resources/leads/",
        "columns": _columns(
            name="The lead's name (usually the company name).",
            description="Free-form description of the lead.",
            status_id="ID of the lead's current status.",
            status_label="Human-readable label of the lead's current status.",
            display_name="Display name of the lead.",
            contacts="List of contacts associated with the lead.",
            url="Website URL of the lead.",
            created_by="ID of the user who created the lead.",
            updated_by="ID of the user who last updated the lead.",
        ),
    },
    "Contacts": {
        "description": "A contact — a person associated with a lead, with their emails and phone numbers.",
        "docs_url": "https://developer.close.com/resources/contacts/",
        "columns": _columns(
            name="The contact's full name.",
            title="The contact's job title.",
            lead_id="ID of the lead this contact belongs to.",
            emails="List of email addresses for the contact.",
            phones="List of phone numbers for the contact.",
            created_by="ID of the user who created the contact.",
        ),
    },
    "Opportunities": {
        "description": "An opportunity — a potential sale tied to a lead, with value and pipeline status.",
        "docs_url": "https://developer.close.com/resources/opportunities/",
        "columns": _columns(
            lead_id="ID of the lead the opportunity belongs to.",
            lead_name="Name of the lead the opportunity belongs to.",
            status_id="ID of the opportunity's current status.",
            status_label="Human-readable label of the opportunity's current status.",
            pipeline_id="ID of the pipeline the opportunity is in.",
            value="Monetary value of the opportunity, in the smallest currency unit.",
            value_formatted="Human-readable formatted value of the opportunity.",
            value_currency="Currency code of the opportunity's value.",
            confidence="Estimated probability (0-100) of winning the opportunity.",
            date_won="Date the opportunity was won, if applicable.",
            user_id="ID of the user who owns the opportunity.",
            user_name="Name of the user who owns the opportunity.",
            note="Free-form note attached to the opportunity.",
        ),
    },
    "Activities": {
        "description": "An activity logged against a lead — a call, email, note, meeting, or status change.",
        "docs_url": "https://developer.close.com/resources/activities/",
        "columns": _columns(
            _type="Type of the activity (e.g. Call, Email, Note, Meeting).",
            lead_id="ID of the lead the activity is associated with.",
            contact_id="ID of the contact the activity is associated with, if any.",
            user_id="ID of the user who performed or logged the activity.",
            user_name="Name of the user who performed or logged the activity.",
        ),
    },
    "Tasks": {
        "description": "A task — a to-do item assigned to a user, usually tied to a lead.",
        "docs_url": "https://developer.close.com/resources/tasks/",
        "columns": _columns(
            _type="Type of the task.",
            lead_id="ID of the lead the task is associated with.",
            lead_name="Name of the lead the task is associated with.",
            text="The task's description text.",
            assigned_to="ID of the user the task is assigned to.",
            assigned_to_name="Name of the user the task is assigned to.",
            date="Due date of the task.",
            is_complete="Whether the task has been completed.",
            is_dateless="Whether the task has no due date.",
        ),
    },
    "Users": {
        "description": "A user (member) of the Close organization.",
        "docs_url": "https://developer.close.com/resources/users/",
        "columns": _columns(
            first_name="The user's first name.",
            last_name="The user's last name.",
            email="The user's email address.",
            image="URL of the user's profile image.",
        ),
    },
    "LeadStatuses": {
        "description": "A configured status that a lead can be in within the organization.",
        "docs_url": "https://developer.close.com/resources/status/",
        "columns": _columns(
            label="Human-readable label of the lead status.",
        ),
    },
    "OpportunityStatuses": {
        "description": "A configured status that an opportunity can be in within a pipeline.",
        "docs_url": "https://developer.close.com/resources/status/",
        "columns": _columns(
            label="Human-readable label of the opportunity status.",
            type="Type of the status (e.g. active, won, lost).",
            pipeline_id="ID of the pipeline this status belongs to.",
        ),
    },
    "Pipelines": {
        "description": "A sales pipeline — an ordered set of opportunity statuses in the organization.",
        "docs_url": "https://developer.close.com/resources/pipelines/",
        "columns": _columns(
            name="The pipeline's name.",
            statuses="The ordered list of statuses in the pipeline.",
        ),
    },
    "EmailTemplates": {
        "description": "A reusable email template used when sending emails from Close.",
        "docs_url": "https://developer.close.com/resources/email-templates/",
        "columns": _columns(
            name="The email template's name.",
            subject="The email template's subject line.",
            body="The email template's body content.",
            is_shared="Whether the template is shared with the whole organization.",
            created_by="ID of the user who created the template.",
        ),
    },
    "Events": {
        "description": (
            "An event log entry — one change to a Close object, with the fields that changed and "
            "their previous values. Close keeps about 30 days of history."
        ),
        "docs_url": "https://developer.close.com/api/resources/events/",
        "columns": _columns(
            date_updated=(
                "Time at which the event was last updated. Close consolidates repeated updates to "
                "the same object into one event, which moves this forward while date_created stays put."
            ),
            object_type="Type of the object the event is about, for example lead or activity.email.",
            object_id="ID of the object the event is about.",
            lead_id="ID of the related lead, or null when the event is not tied to one.",
            action="What happened to the object, for example created, updated or deleted.",
            changed_fields="Names of the fields an update event changed.",
            data="The affected object as the API would return it. Null for delete events.",
            previous_data="Previous values of the changed fields. All attributes for a delete event.",
            user_id="ID of the user whose action generated the event, or null.",
            api_key_id="ID of the API key that generated the event, or null.",
            request_id="Identifier shared by every event from the same request.",
            meta="Extra context for certain event types, such as the bulk action or merge ids.",
        ),
    },
    "Outcomes": {
        "description": "A call or meeting outcome — the standardized result a rep picks when logging one.",
        "docs_url": "https://developer.close.com/api/resources/outcomes/",
        "columns": _columns(
            name="The outcome's name.",
            description="Free-form description of the outcome.",
            type="Whether the outcome is a custom one or the built-in voicemail-dropped outcome.",
            applies_to="Activity types the outcome can be applied to: calls, meetings, or both.",
            created_by="ID of the user who created the outcome.",
            updated_by="ID of the user who last updated the outcome.",
        ),
    },
    "Organizations": {
        "description": "The Close organization — the environment a team works in, with its memberships.",
        "docs_url": "https://developer.close.com/api/resources/organizations/",
        "columns": _columns(
            name="The organization's name.",
            memberships="Active members of the organization, each with their user and role ids.",
            inactive_memberships="Members who no longer have access to the organization.",
            lead_statuses="Lead statuses configured in the organization.",
            created_by="ID of the user who created the organization.",
        ),
    },
    "LeadCustomFields": _custom_field_table("lead", "Leads"),
    "ContactCustomFields": _custom_field_table("contact", "Contacts"),
    "OpportunityCustomFields": _custom_field_table("opportunity", "Opportunities"),
    "ActivityCustomFields": _custom_field_table("activity", "Activities"),
    "SharedCustomFields": {
        "description": (
            "A custom field definition usable on more than one object type. Resolves the "
            "custom.cf_* keys on the objects it is associated with."
        ),
        "docs_url": "https://developer.close.com/api/resources/custom-fields/custom-fields-shared/",
        "columns": _custom_field_columns(
            associations="Object types the field can be used on, and whether it is required on each.",
        ),
    },
}
