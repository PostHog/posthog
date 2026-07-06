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
}
