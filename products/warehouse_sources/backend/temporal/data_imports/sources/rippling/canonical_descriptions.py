"""Canonical, documentation-sourced descriptions for Rippling endpoints and columns.

Sourced from the official Rippling REST API reference (https://developer.rippling.com/documentation/rest-api).
Keyed by the endpoint names in `settings.py` `RIPPLING_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Rippling table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by every Rippling REST object.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workers": {
        "description": "A worker (employee or contractor) in the company, with employment details.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-workers",
        "columns": _columns(
            user_id="ID of the user record associated with the worker.",
            company_id="ID of the company the worker belongs to.",
            employment_type_id="ID of the worker's employment type.",
            department_id="ID of the department the worker belongs to.",
            team_id="ID of the team the worker belongs to.",
            level_id="ID of the worker's job level.",
            work_location_id="ID of the worker's work location.",
            title="The worker's job title.",
            status="Employment status of the worker (e.g. ACTIVE, TERMINATED).",
            start_date="The worker's employment start date.",
            end_date="The worker's employment end date, if applicable.",
            employment_type="The worker's employment type (e.g. FULL_TIME, CONTRACTOR).",
        ),
    },
    "users": {
        "description": "A user account in the company directory, with contact and identity details.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-users",
        "columns": _columns(
            company_id="ID of the company the user belongs to.",
            name="The user's full name structured into given and family names.",
            preferred_first_name="The user's preferred first name.",
            emails="The user's email addresses.",
            phone_numbers="The user's phone numbers.",
            status="Status of the user account (e.g. ACTIVE, INACTIVE).",
            username="The user's username.",
        ),
    },
    "companies": {
        "description": "A company (legal entity) in the Rippling account.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-companies",
        "columns": _columns(
            name="The company's legal name.",
            display_name="The company's display name.",
            legal_name="The company's registered legal name.",
            phone_number="The company's phone number.",
            primary_email="The company's primary contact email.",
            ein="The company's Employer Identification Number.",
            address="The company's address.",
        ),
    },
    "departments": {
        "description": "A department within the company used to organize workers.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-departments",
        "columns": _columns(
            company_id="ID of the company the department belongs to.",
            name="The department's name.",
            parent_id="ID of the parent department, if nested.",
        ),
    },
    "teams": {
        "description": "A team within the company used to group workers.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-teams",
        "columns": _columns(
            company_id="ID of the company the team belongs to.",
            name="The team's name.",
            parent_id="ID of the parent team, if nested.",
        ),
    },
    "levels": {
        "description": "A job level (seniority tier) used to classify workers.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-levels",
        "columns": _columns(
            company_id="ID of the company the level belongs to.",
            name="The level's name.",
            rank="Numeric rank ordering the level relative to others.",
            track_id="ID of the career track the level belongs to.",
        ),
    },
    "work_locations": {
        "description": "A physical work location (office or site) for the company.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-work-locations",
        "columns": _columns(
            company_id="ID of the company the work location belongs to.",
            name="The work location's name.",
            address="The work location's address.",
        ),
    },
    "employment_types": {
        "description": "An employment type classifying how workers are employed (e.g. full-time, contractor).",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-employment-types",
        "columns": _columns(
            company_id="ID of the company the employment type belongs to.",
            name="The employment type's name.",
            label="Display label for the employment type.",
            type="The category of employment (e.g. SALARIED, HOURLY, CONTRACTOR).",
            compensation_time_period="The time period over which compensation is measured.",
        ),
    },
    "compensations": {
        "description": "A worker's compensation record, including pay rate and structure.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-compensations",
        "columns": _columns(
            worker_id="ID of the worker this compensation applies to.",
            currency="Three-letter ISO currency code of the compensation.",
            payment_rate="The worker's pay rate.",
            payment_time_period="The time period the pay rate is measured over (e.g. HOUR, YEAR).",
            payment_type="The type of payment (e.g. SALARY, HOURLY).",
            annual_compensation="The worker's annualized compensation.",
            effective_date="Date the compensation took effect.",
        ),
    },
}
