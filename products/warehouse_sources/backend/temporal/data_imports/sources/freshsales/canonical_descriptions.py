"""Canonical, documentation-sourced descriptions for Freshsales endpoints and columns.

Sourced from the official Freshsales (Freshworks CRM) API reference
(https://developers.freshworks.com/crm/api/). Keyed by the endpoint names in `settings.py`
`FRESHSALES_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Freshsales table.
Some endpoints share an underlying resource but differ by filter (e.g. open_tasks vs completed_tasks).
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Freshsales objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


_TASK_COLUMNS = _columns(
    title="Title of the task.",
    description="Description of the task.",
    due_date="Date and time the task is due.",
    status="Status of the task (0=open, 1=completed).",
    owner_id="ID of the user who owns the task.",
    targetable_id="ID of the record the task is associated with.",
    targetable_type="Type of the record the task is associated with (e.g. Contact, Deal).",
    outcome_id="ID of the recorded outcome of the task.",
)

_APPOINTMENT_COLUMNS = _columns(
    title="Title of the appointment.",
    description="Description of the appointment.",
    location="Location of the appointment.",
    from_date="Start date and time of the appointment.",
    end_date="End date and time of the appointment.",
    creater_id="ID of the user who created the appointment.",
    targetable_id="ID of the record the appointment is associated with.",
    targetable_type="Type of the record the appointment is associated with.",
    is_allday="Whether the appointment lasts all day.",
    time_zone="Time zone of the appointment.",
)


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "A person tracked in the CRM as a potential or existing customer.",
        "docs_url": "https://developers.freshworks.com/crm/api/#contacts",
        "columns": _columns(
            first_name="The contact's first name.",
            last_name="The contact's last name.",
            display_name="The contact's display name.",
            email="The contact's primary email address.",
            mobile_number="The contact's mobile number.",
            work_number="The contact's work phone number.",
            job_title="The contact's job title.",
            owner_id="ID of the user who owns the contact.",
            sales_account_id="ID of the account the contact belongs to.",
            lead_score="Lead score assigned to the contact.",
            last_contacted="Time the contact was last contacted.",
            city="City of the contact.",
            country="Country of the contact.",
        ),
    },
    "sales_accounts": {
        "description": "A company or organization tracked in the CRM.",
        "docs_url": "https://developers.freshworks.com/crm/api/#accounts",
        "columns": _columns(
            name="The account's name.",
            website="The account's website URL.",
            phone="The account's phone number.",
            industry_type_id="ID of the account's industry type.",
            owner_id="ID of the user who owns the account.",
            number_of_employees="Number of employees at the account.",
            annual_revenue="Annual revenue of the account.",
            city="City of the account.",
            country="Country of the account.",
        ),
    },
    "deals": {
        "description": "A sales opportunity tracked through the CRM's pipeline stages.",
        "docs_url": "https://developers.freshworks.com/crm/api/#deals",
        "columns": _columns(
            name="The deal's name.",
            amount="Monetary value of the deal.",
            currency_id="ID of the currency the deal amount is in.",
            deal_stage_id="ID of the pipeline stage the deal is in.",
            deal_pipeline_id="ID of the pipeline the deal belongs to.",
            owner_id="ID of the user who owns the deal.",
            sales_account_id="ID of the account the deal is associated with.",
            probability="Probability the deal will be won, as a percentage.",
            expected_close="Expected close date of the deal.",
            closed_date="Date the deal was closed.",
            stage_updated_time="Time the deal's stage was last updated.",
        ),
    },
    "leads": {
        "description": "An unqualified prospect not yet converted to a contact (legacy lead-based accounts).",
        "docs_url": "https://developers.freshworks.com/crm/api/#leads",
        "columns": _columns(
            first_name="The lead's first name.",
            last_name="The lead's last name.",
            display_name="The lead's display name.",
            email="The lead's email address.",
            mobile_number="The lead's mobile number.",
            company="Company details associated with the lead.",
            owner_id="ID of the user who owns the lead.",
            lead_score="Lead score assigned to the lead.",
            job_title="The lead's job title.",
        ),
    },
    "sales_activities": {
        "description": "A logged sales activity (call, email, meeting) recorded against a record.",
        "docs_url": "https://developers.freshworks.com/crm/api/#sales-activities",
        "columns": _columns(
            title="Title of the sales activity.",
            notes="Notes recorded for the activity.",
            sales_activity_type_id="ID of the activity type.",
            owner_id="ID of the user who owns the activity.",
            targetable_id="ID of the record the activity is associated with.",
            targetable_type="Type of the record the activity is associated with.",
            start_date="Start date and time of the activity.",
            end_date="End date and time of the activity.",
            location="Location of the activity.",
        ),
    },
    "open_tasks": {
        "description": "A task that is still open (incomplete).",
        "docs_url": "https://developers.freshworks.com/crm/api/#tasks",
        "columns": _TASK_COLUMNS,
    },
    "completed_tasks": {
        "description": "A task that has been completed.",
        "docs_url": "https://developers.freshworks.com/crm/api/#tasks",
        "columns": _TASK_COLUMNS,
    },
    "past_appointments": {
        "description": "An appointment whose scheduled time is in the past.",
        "docs_url": "https://developers.freshworks.com/crm/api/#appointments",
        "columns": _APPOINTMENT_COLUMNS,
    },
    "upcoming_appointments": {
        "description": "An appointment scheduled for the future.",
        "docs_url": "https://developers.freshworks.com/crm/api/#appointments",
        "columns": _APPOINTMENT_COLUMNS,
    },
}
