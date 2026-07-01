"""Canonical, documentation-sourced descriptions for Factorial endpoints and columns.

Sourced from the official Factorial API reference (https://apidoc.factorialhr.com/). Keyed by the
endpoint names in `settings.py` `FACTORIAL_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Factorial table. Columns absent here fall back to LLM enrichment, so partial coverage is fine.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://apidoc.factorialhr.com/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "employees": {
        "description": "People employed at the company, with their personal and employment details.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the employee.",
            "first_name": "Employee's first name.",
            "last_name": "Employee's last name.",
            "full_name": "Employee's full name.",
            "email": "Employee's work email address.",
            "birthday_on": "Employee's date of birth.",
            "gender": "Employee's gender.",
            "manager_id": "Identifier of the employee's manager.",
            "legal_entity_id": "Identifier of the legal entity the employee belongs to.",
            "location_id": "Identifier of the employee's primary workplace/location.",
            "team_ids": "Identifiers of the teams the employee belongs to.",
            "company_id": "Identifier of the company the employee belongs to.",
            "terminated_on": "Date the employee was terminated, if applicable.",
            "created_at": "Time at which the employee record was created.",
            "updated_at": "Time at which the employee record was last updated.",
        },
    },
    "teams": {
        "description": "Teams used to group employees within the company.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "Name of the team.",
            "description": "Description of the team.",
            "employee_ids": "Identifiers of the employees in the team.",
            "lead_ids": "Identifiers of the team leads.",
        },
    },
    "team_memberships": {
        "description": "Join records mapping employees to the teams they belong to.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the membership.",
            "employee_id": "Identifier of the employee.",
            "team_id": "Identifier of the team.",
            "lead": "Whether the employee is a lead of the team.",
        },
    },
    "locations": {
        "description": "Workplaces/locations the company operates from, including their time zones.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the location.",
            "name": "Name of the location.",
            "country": "Country of the location.",
            "timezone": "Time zone of the location.",
            "company_id": "Identifier of the company the location belongs to.",
        },
    },
    "legal_entities": {
        "description": "Legal entities (companies) configured in the account.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the legal entity.",
            "legal_name": "Registered legal name of the entity.",
            "country": "Country the legal entity is registered in.",
            "currency": "Default currency used by the legal entity.",
        },
    },
    "contract_versions": {
        "description": "Versions of an employee's contract; the latest holds the current job title, salary, and working hours.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the contract version.",
            "employee_id": "Identifier of the employee the contract belongs to.",
            "job_title": "Job title on this contract version.",
            "salary_amount": "Salary amount on this contract version, in cents.",
            "salary_frequency": "Frequency the salary is paid at.",
            "starts_on": "Date this contract version starts.",
            "ends_on": "Date this contract version ends, if applicable.",
            "working_hours": "Contracted working hours.",
            "created_at": "Time at which the contract version was created.",
            "updated_at": "Time at which the contract version was last updated.",
        },
    },
    "leaves": {
        "description": "Individual time-off / absence records for employees.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the leave.",
            "employee_id": "Identifier of the employee taking the leave.",
            "company_id": "Identifier of the company.",
            "leave_type_id": "Identifier of the leave type.",
            "start_on": "First day of the leave.",
            "finish_on": "Last day of the leave.",
            "approved": "Whether the leave has been approved.",
            "created_at": "Time at which the leave was created.",
            "updated_at": "Time at which the leave was last updated.",
            "deleted_at": "Time at which the leave was deleted, if applicable.",
        },
    },
    "leave_types": {
        "description": "Types of time off / absence configured for the company (e.g. holiday, sick leave).",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the leave type.",
            "name": "Name of the leave type.",
            "color": "Display color for the leave type.",
            "approval_required": "Whether leaves of this type require approval.",
        },
    },
    "allowances": {
        "description": "Time-off allowance counters (the buckets of days/hours employees can take).",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the allowance.",
            "name": "Name of the allowance.",
        },
    },
    "attendance_shifts": {
        "description": "Attendance shifts: clock-in/clock-out records for employees.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the shift.",
            "employee_id": "Identifier of the employee.",
            "clock_in": "Clock-in timestamp.",
            "clock_out": "Clock-out timestamp.",
            "day": "Calendar day the shift belongs to.",
            "created_at": "Time at which the shift was created.",
            "updated_at": "Time at which the shift was last updated.",
        },
    },
    "expenses": {
        "description": "Employee expenses submitted for reimbursement.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the expense.",
            "employee_id": "Identifier of the employee who submitted the expense.",
            "amount_cents": "Expense amount in cents.",
            "currency": "Currency of the expense amount.",
            "status": "Current status of the expense.",
            "created_at": "Time at which the expense was created.",
            "updated_at": "Time at which the expense was last updated.",
        },
    },
    "payroll_supplements": {
        "description": "Payroll supplements (one-off additions or deductions applied to payroll).",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the supplement.",
            "employee_id": "Identifier of the employee.",
            "amount_in_cents": "Supplement amount in cents.",
            "description": "Description of the supplement.",
            "created_at": "Time at which the supplement was created.",
            "updated_at": "Time at which the supplement was last updated.",
        },
    },
    "flexible_time_records": {
        "description": "Flexible time records logged against projects (project time tracking).",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the time record.",
            "employee_id": "Identifier of the employee.",
            "date": "Date the time was recorded for.",
            "imputed_minutes": "Minutes imputed to the record.",
            "created_at": "Time at which the record was created.",
            "updated_at": "Time at which the record was last updated.",
        },
    },
    "projects": {
        "description": "Projects used for time tracking.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "Name of the project.",
            "status": "Current status of the project.",
        },
    },
    "candidates": {
        "description": "Candidates in the applicant tracking system (ATS).",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the candidate.",
            "first_name": "Candidate's first name.",
            "last_name": "Candidate's last name.",
            "email": "Candidate's email address.",
            "created_at": "Time at which the candidate was created.",
            "updated_at": "Time at which the candidate was last updated.",
        },
    },
    "job_postings": {
        "description": "Job postings published in the applicant tracking system (ATS).",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the job posting.",
            "title": "Title of the job posting.",
            "status": "Current status of the job posting.",
            "team_id": "Identifier of the team the posting belongs to.",
            "location_id": "Identifier of the location for the posting.",
        },
    },
    "applications": {
        "description": "Applications linking candidates to job postings in the ATS.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the application.",
            "candidate_id": "Identifier of the candidate.",
            "ats_job_posting_id": "Identifier of the job posting applied to.",
            "phase_id": "Identifier of the current hiring phase.",
            "created_at": "Time at which the application was created.",
            "updated_at": "Time at which the application was last updated.",
        },
    },
}
