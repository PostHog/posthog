"""Canonical, documentation-sourced descriptions for Copper CRM endpoints and columns.

Sourced from the official Copper Developer API reference (https://developer.copper.com/). Keyed by
the endpoint names in `settings.py` `COPPER_ENDPOINTS`, which match the `ExternalDataSchema.name` of
a synced Copper table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Copper records; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the record.",
    "name": "Name of the record.",
    "date_created": "Unix timestamp (seconds) of when the record was created.",
    "date_modified": "Unix timestamp (seconds) of when the record was last modified.",
    "assignee_id": "Unique identifier of the user the record is assigned to.",
    "tags": "List of tags applied to the record.",
    "custom_fields": "Values of custom fields defined for the record.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "people": {
        "description": "A person contact stored in Copper CRM.",
        "docs_url": "https://developer.copper.com/people/list-people-search.html",
        "columns": _columns(
            prefix="Honorific prefix of the person (e.g. Mr., Ms.).",
            first_name="First name of the person.",
            last_name="Last name of the person.",
            title="Job title of the person.",
            company_id="Unique identifier of the company the person belongs to.",
            company_name="Name of the company the person belongs to.",
            emails="List of email addresses for the person.",
            phone_numbers="List of phone numbers for the person.",
            socials="List of social media profiles for the person.",
            websites="List of websites associated with the person.",
            address="Postal address of the person.",
            contact_type_id="Unique identifier of the contact type.",
        ),
    },
    "companies": {
        "description": "A company (organization) stored in Copper CRM.",
        "docs_url": "https://developer.copper.com/companies/list-companies-search.html",
        "columns": _columns(
            email_domain="Primary email domain of the company.",
            details="Free-text details about the company.",
            phone_numbers="List of phone numbers for the company.",
            socials="List of social media profiles for the company.",
            websites="List of websites associated with the company.",
            address="Postal address of the company.",
            contact_type_id="Unique identifier of the contact type.",
        ),
    },
    "leads": {
        "description": "An unqualified prospect (lead) stored in Copper CRM.",
        "docs_url": "https://developer.copper.com/leads/list-leads-search.html",
        "columns": _columns(
            first_name="First name of the lead.",
            last_name="Last name of the lead.",
            title="Job title of the lead.",
            company_name="Name of the company the lead is associated with.",
            email="Primary email address of the lead.",
            phone_numbers="List of phone numbers for the lead.",
            socials="List of social media profiles for the lead.",
            websites="List of websites associated with the lead.",
            address="Postal address of the lead.",
            status="Status of the lead (e.g. New, Open, Junk).",
            status_id="Unique identifier of the lead's status.",
            customer_source_id="Unique identifier of the source the lead came from.",
            monetary_value="Estimated monetary value of the lead.",
            converted_unix_timestamp="Unix timestamp of when the lead was converted.",
        ),
    },
    "opportunities": {
        "description": "A potential sale (opportunity) tracked through a pipeline in Copper CRM.",
        "docs_url": "https://developer.copper.com/opportunities/list-opportunities-search.html",
        "columns": _columns(
            company_id="Unique identifier of the company the opportunity is for.",
            company_name="Name of the company the opportunity is for.",
            primary_contact_id="Unique identifier of the primary contact for the opportunity.",
            customer_source_id="Unique identifier of the source the opportunity came from.",
            loss_reason_id="Unique identifier of the reason the opportunity was lost.",
            pipeline_id="Unique identifier of the pipeline the opportunity belongs to.",
            pipeline_stage_id="Unique identifier of the current pipeline stage.",
            status="Status of the opportunity (Open, Won, Lost, Abandoned).",
            monetary_value="Monetary value of the opportunity.",
            win_probability="Estimated probability of winning the opportunity, as a percentage.",
            close_date="Expected close date of the opportunity.",
            priority="Priority of the opportunity (None, Low, Medium, High).",
        ),
    },
    "projects": {
        "description": "A project used to organize work after a deal closes in Copper CRM.",
        "docs_url": "https://developer.copper.com/projects/list-projects-search.html",
        "columns": _columns(
            related_resource="The resource (e.g. company, person) the project is related to.",
            status="Status of the project (Open, Completed).",
            details="Free-text details about the project.",
        ),
    },
    "tasks": {
        "description": "A to-do item (task) associated with CRM records in Copper.",
        "docs_url": "https://developer.copper.com/tasks/list-tasks-search.html",
        "columns": _columns(
            related_resource="The resource (e.g. company, person, opportunity) the task is related to.",
            due_date="Unix timestamp of when the task is due.",
            reminder_date="Unix timestamp of when a reminder should fire for the task.",
            completed_date="Unix timestamp of when the task was completed.",
            priority="Priority of the task (None, High).",
            status="Status of the task (Open, Completed).",
            details="Free-text details about the task.",
            activity_type="The activity type associated with the task.",
        ),
    },
    "activities": {
        "description": "An entry in the Copper interaction log: a user-entered note, call or meeting, or a system-generated record of a property or pipeline stage change.",
        "docs_url": "https://developer.copper.com/activities/list-activities-search.html",
        "columns": {
            "id": "Unique identifier for the activity.",
            "type": "The activity type, as an object carrying the type id and its category (user or system).",
            "parent": "The record the activity belongs to, as an object carrying the record id and its type (lead, person, company, opportunity, project or task).",
            "details": "Text body of the activity, when it has one.",
            "user_id": "Unique identifier of the user who performed the activity.",
            "activity_date": "Unix timestamp (seconds) of when the activity took place.",
            "old_value": "Value of the changed property before the activity, for system activities.",
            "new_value": "Value of the changed property after the activity, for system activities.",
            "date_created": "Unix timestamp (seconds) of when the activity was created.",
            "date_modified": "Unix timestamp (seconds) of when the activity was last modified.",
        },
    },
    "users": {
        "description": "A user (team member) in the Copper CRM account.",
        "docs_url": "https://developer.copper.com/users/list-users-search.html",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "Full name of the user.",
            "email": "Email address of the user.",
        },
    },
    "pipelines": {
        "description": "A sales pipeline defining the stages opportunities move through.",
        "docs_url": "https://developer.copper.com/pipelines/list-pipelines.html",
        "columns": {
            "id": "Unique identifier for the pipeline.",
            "name": "Name of the pipeline.",
            "stages": "Ordered list of stages within the pipeline.",
        },
    },
    "customer_sources": {
        "description": "A reference list of customer sources used to attribute where leads and opportunities came from.",
        "docs_url": "https://developer.copper.com/customer-sources/list-customer-sources.html",
        "columns": {
            "id": "Unique identifier for the customer source.",
            "name": "Name of the customer source.",
        },
    },
    "loss_reasons": {
        "description": "A reference list of reasons used to record why an opportunity was lost.",
        "docs_url": "https://developer.copper.com/loss-reasons/list-loss-reasons.html",
        "columns": {
            "id": "Unique identifier for the loss reason.",
            "name": "Name of the loss reason.",
        },
    },
    "contact_types": {
        "description": "A reference list of contact types used to classify people and companies.",
        "docs_url": "https://developer.copper.com/contact-types/list-contact-types.html",
        "columns": {
            "id": "Unique identifier for the contact type.",
            "name": "Name of the contact type.",
        },
    },
    "pipeline_stages": {
        "description": "A stage within a sales pipeline, defining where an opportunity sits in that pipeline.",
        "docs_url": "https://developer.copper.com/opportunities/list-pipeline-stages.html",
        "columns": {
            "id": "Unique identifier for the pipeline stage.",
            "name": "Name of the pipeline stage.",
            "pipeline_id": "Unique identifier of the pipeline this stage belongs to.",
            "win_probability": "Expected probability (0-100) of winning an opportunity in this stage.",
        },
    },
    "lead_statuses": {
        "description": "A reference list of statuses marking where a lead sits in the qualification process.",
        "docs_url": "https://developer.copper.com/leads/list-lead-statuses.html",
        "columns": {
            "id": "Unique identifier for the lead status.",
            "name": "Name of the lead status.",
            "order": "Position of the status in the list as displayed in the app.",
            "is_default": "Whether this status is selected by default on a new lead.",
        },
    },
    "activity_types": {
        "description": "A reference list of the activity types in the account. Types in the user category are user-entered (notes, calls, meetings and any custom types); types in the system category are generated by Copper.",
        "docs_url": "https://developer.copper.com/activities/list-activity-types.html",
        "columns": {
            "id": "Identifier of the activity type. Unique within its category, not across both.",
            "category": "Category of the activity type: user or system.",
            "name": "Name of the activity type.",
            "is_disabled": "For custom activity types, whether the type is disabled.",
            "count_as_interaction": "For user activity types, whether activities of this type count toward interactions data.",
        },
    },
    "custom_activity_types": {
        "description": "An activity type created for the account, with the display settings the app uses for it.",
        "docs_url": "https://developer.copper.com/custom-fields/general/list-all-custom-activity-types.html",
        "columns": {
            "id": "Unique identifier for the custom activity type.",
            "company_id": "Unique identifier of the Copper account the type belongs to.",
            "icon_type": "Icon the app shows for activities of this type.",
            "is_disabled": "Whether the type is disabled.",
            "is_interaction": "Whether activities of this type count as an interaction.",
            "name": "Name of the custom activity type.",
            "is_default_task_type": "Whether this type is the default for newly created tasks.",
        },
    },
    "custom_field_definitions": {
        "description": "A custom field configured for the account, describing what the matching entry in a record's custom_fields holds.",
        "docs_url": "https://developer.copper.com/custom-fields/general/list-custom-field-definitions.html",
        "columns": {
            "id": "Unique identifier for the custom field definition, matching custom_field_definition_id on a record.",
            "name": "Label of the custom field.",
            "data_type": "Type of data the field stores: String, Text, Dropdown, Date, Checkbox, Float, URL, Percentage, Currency, Connect or MultiSelect.",
            "available_on": "Record types the field applies to: lead, person, opportunity, company, project or task.",
            "is_filterable": "Whether the field can be used in filters.",
            "currency": "Currency of the field. Set only when the data type is Currency.",
            "options": "Dropdown options for the field. Set only when the data type is Dropdown.",
        },
    },
    "tags": {
        "description": "A tag used in the account, with how many records of each type carry it. Tags have no id, so the name identifies the row.",
        "docs_url": "https://developer.copper.com/tags/list-tags.html",
        "columns": {
            "name": "The tag text, and the identity of the tag.",
            "count": "Total number of records carrying the tag.",
            "count_people": "Number of people carrying the tag.",
            "count_leads": "Number of leads carrying the tag.",
            "count_companies": "Number of companies carrying the tag.",
            "count_opportunities": "Number of opportunities carrying the tag.",
            "count_projects": "Number of projects carrying the tag.",
            "count_tasks": "Number of tasks carrying the tag.",
        },
    },
    "field_layouts": {
        "description": "One field of one record type's layout, saying which fields apply to that record type and in what order. Configured in Copper under Settings, Manage Fields On Records.",
        "docs_url": "https://developer.copper.com/field-layouts/list-field-layout-by-entity-type.html",
        "columns": {
            "entity_type": "Record type the layout belongs to, in plural form: people, companies, leads, opportunities, projects or tasks.",
            "pipeline_id": "Pipeline the layout applies to. Only opportunity layouts are pipeline-specific; every other row carries 0.",
            "field_id": "Identifier of the field. Standard fields are sequential integers; custom and embedded-app fields carry the id of that entity.",
            "field_label": "Label the app shows for the field.",
            "field_key": "Internal name of the field. Custom fields are prefixed cf_ and embedded-app fields embedded_.",
            "field_type": "Kind of field: static_field, custom_field or embedded_app_field.",
            "enabled": "Whether the field is enabled for this record type in the app.",
            "required": "Whether the field must be set when a record is created.",
            "required_editable": "Whether the field must be set when a record is edited.",
        },
    },
    "related_items": {
        "description": "One link between two Copper records, as shown in the Related Items section of the app. Links are bidirectional, so each link appears twice, once from each end.",
        "docs_url": "https://developer.copper.com/related-items/view-all-records-related-to-an-entity.html",
        "columns": {
            "parent_type": "Record type the link was read from: lead, person, company, opportunity, project or task.",
            "parent_id": "Identifier of the record the link was read from, unique within parent_type.",
            "type": "Record type at the other end of the link.",
            "id": "Identifier of the record at the other end of the link, unique within type.",
        },
    },
}
