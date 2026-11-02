"""Canonical, documentation-sourced descriptions for Personio endpoints and columns.

Sourced from the official Personio v2 API reference (https://developer.personio.de/reference). Keyed
by the endpoint names in `settings.py` `PERSONIO_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Personio table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "persons": {
        "description": "An employee record in Personio, with profile attributes and employment details.",
        "docs_url": "https://developer.personio.de/reference/get_v2-persons",
        "columns": {
            "id": "Unique identifier for the person.",
            "first_name": "The employee's first name.",
            "last_name": "The employee's last name.",
            "email": "The employee's email address.",
            "status": "Employment status of the person (e.g. active, inactive, onboarding, leave).",
            "created_at": "Time at which the person record was created.",
            "updated_at": "Time at which the person record was last updated.",
            "attributes": "Whitelisted custom and standard employee attributes.",
        },
    },
    "employments": {
        "description": "An employment record of a Personio person, with its position, contract type and dates.",
        "docs_url": "https://developer.personio.de/reference/get_v2-persons-person-id-employments",
        "columns": {
            "id": "Unique identifier for the employment.",
            "person_id": "The person the employment belongs to.",
            "position": "The position of the employment, carrying its title.",
            "status": "Status of the employment (ACTIVE, INACTIVE, ONBOARDING, LEAVE or UNSPECIFIED).",
            "type": "Employment type (INTERNAL, EXTERNAL or UNSPECIFIED).",
            "weekly_working_hours": "Total weekly working hours of the employment.",
            "full_time_weekly_working_hours": "Weekly working hours considered full time for the employment.",
            "probation_end_date": "Date that marks the end of the probation period.",
            "employment_start_date": "Date that marks the start of the employment.",
            "employment_end_date": "Date that marks the end of the employment.",
            "contract_end_date": "Date the contract ends for this employment.",
            "supervisor": "The supervisor of the employment, carrying a person id.",
            "office": "The office of the employment, carrying an office id.",
            "org_units": "Org units (departments and teams) the employment belongs to.",
            "cost_centers": "Cost centers the employment is allocated to.",
            "legal_entity": "The legal entity of the employment, carrying a legal entity id.",
            "job": "The job of the employment, carrying a job id.",
            "created_at": "Time at which the employment was created.",
            "updated_at": "Time at which the employment was last updated.",
        },
    },
    "compensations": {
        "description": "A payroll compensation (base salary, hourly, one-time, recurring or bonus) that applies to a person in a calendar month.",
        "docs_url": "https://developer.personio.de/reference/get_v2-compensations",
        "columns": {
            "id": "Identifier of the compensation.",
            "period_start": "First day of the calendar month the compensation was listed for.",
            "person": "The person the compensation belongs to, carrying a person id.",
            "legal_entity": "The legal entity of the compensation, carrying a legal entity id.",
            "type": "The compensation type, with its name and category (e.g. FIXED_SALARY, ONE_TIME).",
            "amount": "The compensation amount, with its value and currency.",
            "interval": "Payout interval of the compensation (MONTHLY, ONE_TIME or YEARLY).",
            "effective_from": "Effective start date of the compensation.",
            "weekly_working_hours": "Hours the person is expected to work per week. Only set for fixed salaries.",
            "full_time_weekly_working_hours": "Hours per week considered full time. Only set for fixed salaries.",
        },
    },
    "absence_periods": {
        "description": "A period of employee absence such as vacation or sick leave, including its dates and type.",
        "docs_url": "https://developer.personio.de/reference/get_v2-absence-periods",
        "columns": {
            "id": "Unique identifier for the absence period.",
            "person": "The employee the absence belongs to.",
            "absence_type": "The type of absence (e.g. paid vacation, sick leave).",
            "start_date": "First day of the absence period.",
            "end_date": "Last day of the absence period.",
            "status": "Approval status of the absence (e.g. pending, approved, rejected).",
            "created_at": "Time at which the absence period was created.",
            "updated_at": "Time at which the absence period was last updated.",
        },
    },
    "attendance_periods": {
        "description": "A recorded period of employee working time (a shift or break), with start and end times.",
        "docs_url": "https://developer.personio.de/reference/get_v2-attendance-periods",
        "columns": {
            "id": "Unique identifier for the attendance period.",
            "person": "The employee the attendance belongs to.",
            "type": "The type of attendance period (e.g. work, break).",
            "start": "Start time of the attendance period.",
            "end": "End time of the attendance period.",
            "created_at": "Time at which the attendance period was created.",
            "updated_at": "Time at which the attendance period was last updated.",
        },
    },
    "salary_bands": {
        "description": "A salary band with its compensation range and the workplaces it applies to.",
        "docs_url": "https://developer.personio.de/reference/listsalarybands",
        "columns": {
            "id": "Unique identifier for the salary band.",
            "min": "Minimum salary of the band, in major currency units.",
            "max": "Maximum salary of the band, in major currency units.",
            "middle": "Midpoint of the band, in major currency units. Null when no midpoint is defined.",
            "currency": "ISO 4217 three-letter currency code of the band.",
            "workplaces": "Workplaces the salary band applies to, each carrying a workplace id.",
        },
    },
    "cost_centers": {
        "description": "A cost center defined in Personio, used to allocate people and time to finance dimensions.",
        "docs_url": "https://developer.personio.de/reference/listcostcenters",
        "columns": {
            "id": "Unique identifier for the cost center.",
            "name": "The name of the cost center.",
        },
    },
    "absence_types": {
        "description": "An absence type defined in Personio, such as vacation or sick leave, referenced by absence periods.",
        "docs_url": "https://developer.personio.de/reference/get_v2-absence-types",
        "columns": {
            "id": "Unique identifier for the absence type.",
            "name": "The name of the absence type.",
            "category": "The category of the absence type (e.g. PAID_VACATION, SICK_LEAVE).",
            "unit": "Unit absence periods of this type are measured in (DAY or HOUR).",
        },
    },
    "org_units": {
        "description": "An org unit (department or team) in Personio, with its place in the org unit hierarchy.",
        "docs_url": "https://developer.personio.de/reference/listorgunits",
        "columns": {
            "id": "Unique identifier for the org unit.",
            "type": "Type of the org unit (department or team).",
            "name": "The name of the org unit.",
            "abbreviation": "Short name of the org unit.",
            "description": "Description of the org unit.",
            "parent_id": "Identifier of the parent org unit. Null for a root org unit.",
            "parent_chain": "Ordered ancestor org unit ids, from the immediate parent up to the root.",
            "create_time": "Time at which the org unit was created.",
        },
    },
    "recruiting_jobs": {
        "description": "A recruiting job (open position) in Personio, with its category, department and hiring team.",
        "docs_url": "https://developer.personio.de/reference/get_v2-recruiting-jobs",
        "columns": {
            "id": "Unique identifier for the job.",
            "name": "The job title.",
            "company": "The company the job belongs to, carrying a company id.",
            "department": "The department the job belongs to, with its id and name.",
            "category": "The recruiting category of the job, with its id and name.",
            "hiring_team": "Hiring team members assigned to the job, each with a person reference and a role name.",
            "created_at": "Creation time of the job, as a date-time with UTC offset and an IANA time zone.",
            "updated_at": "Last modification time of the job, as a date-time with UTC offset and an IANA time zone.",
        },
    },
    "recruiting_categories": {
        "description": "A recruiting job category in Personio, with the ordered pipeline stages applications move through.",
        "docs_url": "https://developer.personio.de/reference/get_v2-recruiting-categories",
        "columns": {
            "id": "Unique identifier for the category.",
            "name": "The name of the category.",
            "company": "The company the category belongs to, carrying a company id.",
            "stages": "Ordered list of recruiting stages for this category, each with a kind (custom or system) and a type.",
        },
    },
}
