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
}
