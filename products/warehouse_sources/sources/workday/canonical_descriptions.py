"""Canonical, documentation-sourced descriptions for Workday REST endpoints and columns.

Sourced from the Workday REST API reference
(https://community.workday.com/sites/default/files/file-hosting/restapi/index.html). Keyed by the
endpoint names in `settings.py` `WORKDAY_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Workday table. Columns absent here fall back to LLM enrichment.

Every Workday REST collection item carries the same instance envelope — `id` (the Workday ID, a
32-char hex WID), `descriptor` (the human-readable label Workday renders for the instance) and
`href` (the absolute API URL of the instance) — so those three are described on every table.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_DOCS_URL = "https://community.workday.com/sites/default/files/file-hosting/restapi/index.html"

_INSTANCE_COLUMNS = {
    "id": "Workday ID (WID) uniquely identifying the instance.",
    "descriptor": "Human-readable label Workday displays for the instance.",
    "href": "Absolute Workday REST URL of the instance.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workers": {
        "description": "A worker in the tenant — an employee or contingent worker — with their current staffing information.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_INSTANCE_COLUMNS,
            "primaryWorkEmail": "Worker's primary work email address.",
            "isManager": "Whether the worker manages at least one supervisory organization.",
            "businessTitle": "Business title shown on the worker's primary job.",
            "primaryWorkPhone": "Worker's primary work phone number.",
            "person": "Reference to the person record behind the worker.",
            "supervisoryOrganization": "Supervisory organization the worker's primary position belongs to.",
        },
    },
    "jobs": {
        "description": "A job — the instance of a position a worker is assigned to, including its staffing details.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_INSTANCE_COLUMNS,
            "worker": "Worker assigned to the job.",
            "jobProfile": "Job profile the job is based on.",
            "supervisoryOrganization": "Supervisory organization the job reports into.",
            "effectiveDate": "Date the current job details took effect.",
        },
    },
    "job_profiles": {
        "description": "A job profile — the reusable definition of a job's title, level, and pay-rate type that positions are created from.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_INSTANCE_COLUMNS,
            "jobFamily": "Job families the profile belongs to.",
            "managementLevel": "Management level associated with the profile.",
            "inactive": "Whether the profile is inactive and can no longer be assigned.",
        },
    },
    "job_families": {
        "description": "A job family — the grouping of related job profiles used for reporting and compensation.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_INSTANCE_COLUMNS,
            "inactive": "Whether the job family is inactive.",
        },
    },
    "supervisory_organizations": {
        "description": "A supervisory organization — the manager-led org unit that positions and workers are assigned to.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_INSTANCE_COLUMNS,
            "manager": "Worker who manages the organization.",
            "superiorOrganization": "Parent supervisory organization in the hierarchy.",
            "code": "Organization code assigned in the tenant.",
            "availableForHire": "Whether the organization is available for hiring.",
        },
    },
    "job_changes": {
        "description": "A job change event — a Change Job business process recording a worker's move between positions, titles, or organizations.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_INSTANCE_COLUMNS,
            "worker": "Worker whose job changed.",
            "effectiveDate": "Date the job change takes effect.",
            "reason": "Reason selected for the job change.",
        },
    },
    "organization_assignment_changes": {
        "description": "An organization assignment change event — a business process recording a change to the organizations (company, cost center, region) a position is assigned to.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_INSTANCE_COLUMNS,
            "worker": "Worker whose organization assignments changed.",
            "effectiveDate": "Date the organization assignment change takes effect.",
            "reason": "Reason selected for the organization assignment change.",
        },
    },
    "locations": {
        "description": "A location that can be set on a job — a workplace or site, as listed by the Staffing service for job changes. Use it to resolve the location references on other tables.",
        "docs_url": _DOCS_URL,
        "columns": dict(_INSTANCE_COLUMNS),
    },
    "worker_time_blocks": {
        "description": "A reported time block — the hours or units a worker entered for one calendar date, with its approval status and work tags. Incomplete blocks, time off, and overtime requests are not included.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_INSTANCE_COLUMNS,
            "worker": "Worker who reported the time block.",
            "calendarDate": "Date the time block was reported for.",
            "reportedQuantity": "Hours or units entered for the time block.",
            "unit": "Unit the reported quantity is measured in.",
            "status": "Approval status of the time block, such as submitted or approved.",
            "timeEntryCode": "Time entry code the time was reported against.",
            "comment": "Comment entered on the time block.",
            "project": "Project the time was reported against.",
            "projectPlanTask": "Project plan task the time was reported against.",
            "projectPlanPhase": "Project plan phase the time was reported against.",
            "overrideRate": "Override rate entered for the time block.",
            "doNotBill": "Whether the time block is flagged as non-billable.",
            "calculatedTimeDetails": "Calculated time Workday derived from the reported block.",
        },
    },
    "worker_pay_slips": {
        "description": "A pay slip — the payroll result paid to a worker on one payment date, with gross and net pay. One row per worker and pay slip.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_INSTANCE_COLUMNS,
            "id": "Workday ID of the payroll result behind the pay slip.",
            "worker_id": "Workday ID of the worker the pay slip belongs to.",
            "date": "Payment date of the pay slip.",
            "gross": "Gross pay on the pay slip.",
            "net": "Net pay on the pay slip.",
            "status": "Status of the pay slip.",
        },
    },
    "worker_history": {
        "description": "A staffing history event for a worker — a business process such as a hire, job change, or termination. One row per worker and event.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_INSTANCE_COLUMNS,
            "id": "Workday ID of the business process event.",
            "worker_id": "Workday ID of the worker the history belongs to.",
            "initiated": "Date and time the business process was started.",
            "effective": "Date the business process takes effect.",
            "due": "Date the business process needs to be completed.",
            "subject": "Subject of the business process.",
            "initiator": "Worker who started the business process.",
        },
    },
}
