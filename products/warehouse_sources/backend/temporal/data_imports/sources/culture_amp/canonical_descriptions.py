"""Canonical, documentation-sourced descriptions for Culture Amp endpoints and columns.

Sourced from the official Culture Amp Public API reference (https://developer.cultureamp.com/).
Keyed by the endpoint names in `settings.py` `CULTURE_AMP_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Culture Amp table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "employees": {
        "description": "An employee record in the Culture Amp account, with profile and employment details.",
        "docs_url": "https://developer.cultureamp.com/reference/employees",
        "columns": {
            "id": "Unique identifier for the employee.",
            "email": "The employee's email address.",
            "name": "The employee's full name.",
            "employeeId": "The employer-assigned employee identifier.",
            "status": "Employment status of the employee (e.g. active, inactive).",
            "startDate": "Date the employee started employment.",
            "endDate": "Date the employee's employment ended, if applicable.",
            "processedAt": "Time at which the record was processed and made available via the public API.",
        },
    },
    "employee_demographics": {
        "description": "A single demographic attribute (name/value pair) for an employee.",
        "docs_url": "https://developer.cultureamp.com/reference/employee-demographics",
        "columns": {
            "_employee_id": "Identifier of the employee this demographic belongs to.",
            "name": "Name of the demographic attribute (e.g. department, location, gender).",
            "value": "Value of the demographic attribute for the employee.",
        },
    },
    "performance_cycles": {
        "description": "A performance evaluation cycle run for the account over a defined period.",
        "docs_url": "https://developer.cultureamp.com/reference/performance-evaluations",
        "columns": {
            "id": "Unique identifier for the performance cycle.",
            "name": "Name of the performance cycle.",
            "status": "Current status of the cycle (e.g. open, closed).",
            "startDate": "Date the performance cycle starts.",
            "endDate": "Date the performance cycle ends.",
            "processedAt": "Time at which the record was processed and made available via the public API.",
        },
    },
    "manager_reviews": {
        "description": "A manager's review of an employee within a performance evaluation cycle.",
        "docs_url": "https://developer.cultureamp.com/reference/performance-evaluations",
        "columns": {
            "managerReviewId": "Unique identifier for the manager review.",
            "performanceCycleId": "Identifier of the performance cycle this review belongs to.",
            "employeeId": "Identifier of the employee being reviewed.",
            "managerId": "Identifier of the manager who wrote the review.",
            "status": "Completion status of the review.",
            "processedAt": "Time at which the record was processed and made available via the public API.",
        },
    },
}
