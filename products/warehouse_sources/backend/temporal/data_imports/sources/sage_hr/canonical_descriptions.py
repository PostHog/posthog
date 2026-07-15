from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Sage HR API docs (https://sagehr.docs.apiary.io). Partial coverage
# is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "employees": {
        "description": "An active employee, with their contact details, position, team, and employment dates.",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the employee.",
            "email": "The employee's email address.",
            "first_name": "The employee's first name.",
            "last_name": "The employee's last name.",
            "picture_url": "URL of the employee's profile photo.",
            "employment_start_date": "The date the employee's employment began.",
            "date_of_birth": "The employee's date of birth.",
            "team": "The name of the employee's team.",
            "team_id": "The ID of the employee's team.",
            "position": "The employee's job title.",
            "position_id": "The ID of the employee's position.",
            "reports_to_employee_id": "The employee ID of the person this employee reports to.",
            "employee_number": "The employee's internal staff number.",
            "employment_status": "The employee's employment status (e.g. Full-time).",
            "nationality": "The employee's nationality.",
            "country": "Two-letter ISO country code of the employee's address.",
        },
    },
    "terminated_employees": {
        "description": "A terminated (former) employee, with their identity fields and termination date.",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the employee.",
            "email": "The employee's email address.",
            "first_name": "The employee's first name.",
            "last_name": "The employee's last name.",
            "termination_date": "The employee's last working day.",
            "employment_start_date": "The date the employee's employment began.",
            "employee_number": "The employee's internal staff number.",
            "position": "The employee's job title at termination.",
        },
    },
    "termination_reasons": {
        "description": "A termination reason configured for the company (e.g. New job).",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the termination reason.",
            "name": "The termination reason label.",
            "code": "Optional short code for the reason.",
            "type": "Whether the reason is voluntary or involuntary.",
        },
    },
    "teams": {
        "description": "A team in the company, with its managers and members.",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the team.",
            "name": "The team name.",
            "manager_ids": "Employee IDs of the team's managers.",
            "employee_ids": "Employee IDs of the team's members.",
        },
    },
    "positions": {
        "description": "A job position defined in the company.",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the position.",
            "title": "The position title.",
            "description": "Free-text description of the position.",
            "code": "Optional position code.",
        },
    },
    "documents": {
        "description": "A document stored in Sage HR, with its file metadata and sharing settings.",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the document.",
            "document_category_id": "The ID of the category the document belongs to.",
            "description": "Free-text description of the document.",
            "file_name": "The uploaded file's name.",
            "file_content_type": "The uploaded file's MIME type.",
            "file_size": "The uploaded file's size in bytes.",
            "shared_with_everyone": "Whether the document is shared with everyone.",
            "created_at": "When the document was created.",
            "updated_at": "When the document was last updated.",
        },
    },
    "document_categories": {
        "description": "A document category, with the number of documents it contains.",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the document category.",
            "name": "The category name.",
            "documents_count": "Number of documents in the category.",
        },
    },
    "leave_requests": {
        "description": "A time off request, with its policy, requester, dates, and approval state.",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the time off request.",
            "status": "Human-readable request status (e.g. Approved).",
            "status_code": "Machine-readable request status (e.g. approved).",
            "policy_id": "The ID of the time off policy the request is made under.",
            "employee_id": "The ID of the requesting employee.",
            "details": "Free-text reason or notes on the request.",
            "is_multi_date": "Whether the request spans multiple days.",
            "is_single_day": "Whether the request is for a single day.",
            "is_part_of_day": "Whether the request covers only part of a day.",
            "start_date": "The first day of the requested leave.",
            "end_date": "The last day of the requested leave.",
            "request_date": "When the request was submitted.",
            "approval_date": "When the request was approved, if it has been.",
            "hours": "Number of hours requested.",
        },
    },
    "leave_policies": {
        "description": "A time off policy (e.g. Vacation), with its accrual and allowance settings.",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the time off policy.",
            "name": "The policy name.",
            "color": "Hex display color of the policy.",
            "do_not_accrue": "Whether accrual is disabled for the policy.",
            "unit": "Measurement unit of the policy (e.g. days).",
            "default_allowance": "Default entitlement under the policy.",
            "max_carryover": "Maximum amount that can be carried over.",
            "accrue_type": "How the allowance accrues (e.g. yearly, no_tracking).",
        },
    },
    "individual_allowances": {
        "description": "Per-employee time off allowances: each employee's entitlement under each policy.",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the employee the allowances belong to.",
            "full_name": "The employee's full name.",
            "eligibilities": "The employee's per-policy allowances (policy, quantity, unit, carryover).",
        },
    },
    "onboarding_categories": {
        "description": "An onboarding task category (e.g. General).",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the onboarding category.",
            "title": "The category title.",
        },
    },
    "offboarding_categories": {
        "description": "An offboarding task category.",
        "docs_url": "https://sagehr.docs.apiary.io",
        "columns": {
            "id": "The unique ID of the offboarding category.",
            "title": "The category title.",
        },
    },
}
