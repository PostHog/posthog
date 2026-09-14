"""Canonical, documentation-sourced descriptions for BambooHR endpoints and columns.

Sourced from the official BambooHR API reference (https://documentation.bamboohr.com/reference).
Keyed by the endpoint names in `settings.py` `BAMBOOHR_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced BambooHR table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "employees": {
        "description": "An employee in the company directory.",
        "docs_url": "https://documentation.bamboohr.com/reference/get-employees-directory-1",
        "columns": {
            "id": "Unique identifier for the employee.",
            "displayName": "The employee's display name.",
            "firstName": "The employee's first name.",
            "lastName": "The employee's last name.",
            "preferredName": "The employee's preferred name, if set.",
            "jobTitle": "The employee's job title.",
            "workEmail": "The employee's work email address.",
            "department": "The department the employee belongs to.",
            "division": "The division the employee belongs to.",
            "location": "The employee's work location.",
            "supervisor": "The employee's supervisor.",
            "workPhone": "The employee's work phone number.",
            "mobilePhone": "The employee's mobile phone number.",
            "photoUrl": "URL of the employee's profile photo.",
        },
    },
    "time_off_requests": {
        "description": "A time-off request submitted by an employee.",
        "docs_url": "https://documentation.bamboohr.com/reference/time-off-1",
        "columns": {
            "id": "Unique identifier for the time-off request.",
            "employeeId": "ID of the employee who made the request.",
            "name": "Name of the employee who made the request.",
            "status": "Status of the request, including approval state.",
            "start": "Start date of the requested time off.",
            "end": "End date of the requested time off.",
            "created": "Date the request was created.",
            "type": "The type of time off requested (e.g. vacation, sick).",
            "amount": "The amount of time off requested, with its unit.",
            "notes": "Notes attached to the request.",
        },
    },
    "time_off_types": {
        "description": "A category of time off configured for the company (e.g. vacation, sick).",
        "docs_url": "https://documentation.bamboohr.com/reference/get-time-off-types",
        "columns": {
            "id": "Unique identifier for the time-off type.",
            "name": "Name of the time-off type.",
            "units": "The unit the time-off type is measured in (hours or days).",
            "color": "Display color of the time-off type.",
            "icon": "Icon associated with the time-off type.",
        },
    },
    "employee_job_info": {
        "description": "A dated row from an employee's job information history table. A row records the job title, department, division, location and reporting line an employee held from a given effective date. The columns depend on how the company has configured the table.",
        "docs_url": "https://documentation.bamboohr.com/reference/get-changed-employee-table-data",
        "columns": {
            "id": "Unique identifier for the row within the jobInfo table.",
            "employeeId": "ID of the employee the row belongs to.",
            "lastChanged": "Time at which any field on this employee's record last changed.",
            "date": "The effective date of the row.",
        },
    },
    "employee_compensation": {
        "description": "A dated row from an employee's compensation history table. A row records the pay rate, pay type, pay schedule and overtime status an employee held from a given effective date. The columns depend on how the company has configured the table.",
        "docs_url": "https://documentation.bamboohr.com/reference/get-changed-employee-table-data",
        "columns": {
            "id": "Unique identifier for the row within the compensation table.",
            "employeeId": "ID of the employee the row belongs to.",
            "lastChanged": "Time at which any field on this employee's record last changed.",
            "date": "The effective date of the row.",
        },
    },
    "employee_employment_status": {
        "description": "A dated row from an employee's employment status history table. A row records the employment status and status change an employee held from a given effective date, including terminations. The columns depend on how the company has configured the table.",
        "docs_url": "https://documentation.bamboohr.com/reference/get-changed-employee-table-data",
        "columns": {
            "id": "Unique identifier for the row within the employmentStatus table.",
            "employeeId": "ID of the employee the row belongs to.",
            "lastChanged": "Time at which any field on this employee's record last changed.",
            "date": "The effective date of the row.",
        },
    },
    "time_off_policies": {
        "description": "A time-off policy configured for the company, governing how a time-off type accrues.",
        "docs_url": "https://documentation.bamboohr.com/reference/list-time-off-policies",
        "columns": {
            "id": "Unique identifier for the policy.",
            "timeOffTypeId": "ID of the time-off type the policy belongs to.",
            "name": "Name of the policy.",
            "type": "The policy type: accruing, discretionary or manual.",
            "effectiveDate": "Deprecated by BambooHR and always empty.",
        },
    },
    "employee_time_off_policies": {
        "description": "The assignment of a time-off policy to an employee.",
        "docs_url": "https://documentation.bamboohr.com/reference/list-employee-time-off-policies-v1_1",
        "columns": {
            "employeeId": "ID of the employee the policy is assigned to.",
            "timeOffPolicyId": "ID of the assigned time-off policy.",
            "timeOffTypeId": "ID of the time-off type the policy covers.",
            "accrualStartDate": "Date accruals started, empty for manual and unlimited policies.",
        },
    },
    "employee_time_off_balances": {
        "description": "An employee's current time-off balance for one time-off type, as of the day the table was synced.",
        "docs_url": "https://documentation.bamboohr.com/reference/get-time-off-balance",
        "columns": {
            "employeeId": "ID of the employee the balance belongs to.",
            "timeOffType": "ID of the time-off type the balance covers.",
            "name": "Name of the time-off type.",
            "units": "The unit the balance is measured in (hours or days).",
            "balance": "Balance available as of the calculation date.",
            "end": "The date the balance was calculated as of.",
            "policyType": "The policy type behind the balance: accruing, discretionary or manual.",
            "usedYearToDate": "Amount of this time-off type used so far this year.",
        },
    },
    "timesheet_entries": {
        "description": "A single tracked block of time worked by an employee, either clocked or entered as hours.",
        "docs_url": "https://documentation.bamboohr.com/reference/list-timesheet-entries",
        "columns": {
            "id": "Unique identifier for the timesheet entry.",
            "employeeId": "ID of the employee who worked the time.",
            "type": "Whether the entry was clocked or entered as hours.",
            "date": "The date the time was worked.",
            "start": "Time the employee clocked in.",
            "end": "Time the employee clocked out.",
            "timezone": "Timezone the entry was recorded in.",
            "hours": "Hours worked.",
            "note": "Note attached to the entry.",
            "projectInfo": "The project and task the time was booked to.",
            "approved": "Whether the entry has been approved.",
            "approvedAt": "Time at which the entry was approved.",
            "createdAt": "Time at which the entry was created.",
            "updatedAt": "Time at which the entry was last updated.",
        },
    },
    "meta_fields": {
        "description": "A field definition available in the company's BambooHR account.",
        "docs_url": "https://documentation.bamboohr.com/reference/metadata-get-a-list-of-fields",
        "columns": {
            "id": "Unique identifier for the field.",
            "name": "Display name of the field.",
            "type": "Data type of the field.",
            "alias": "API alias used to reference the field.",
        },
    },
    "meta_lists": {
        "description": "A list field and its available option values configured in BambooHR.",
        "docs_url": "https://documentation.bamboohr.com/reference/metadata-get-details-for-list-fields",
        "columns": {
            "fieldId": "ID of the field this list of options applies to.",
            "name": "Name of the list field.",
            "alias": "API alias used to reference the field.",
            "options": "The available option values for the list field.",
        },
    },
    "meta_users": {
        "description": "A user account with access to the company's BambooHR.",
        "docs_url": "https://documentation.bamboohr.com/reference/get-a-list-of-users",
        "columns": {
            "id": "Unique identifier for the user.",
            "employeeId": "ID of the employee the user is linked to, if any.",
            "firstName": "The user's first name.",
            "lastName": "The user's last name.",
            "email": "The user's email address.",
            "status": "Status of the user account (enabled or disabled).",
            "lastLogin": "Time at which the user last logged in.",
        },
    },
}
