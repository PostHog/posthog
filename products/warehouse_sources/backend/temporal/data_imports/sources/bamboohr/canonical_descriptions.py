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
