from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "locations": {
        "description": "Company locations with addresses, time zones, and opening hours.",
        "docs_url": "https://developers.7shifts.com/reference/getlocationlistbycompany",
        "columns": {
            "id": "The location ID.",
            "company_id": "The company ID.",
            "name": "The location name.",
            "timezone": "The location's time zone.",
            "created": "The time when the location was created.",
            "modified": "The time when the location was last modified.",
        },
    },
    "departments": {
        "description": "Company departments and their locations.",
        "docs_url": "https://developers.7shifts.com/reference/listdepartments",
        "columns": {
            "id": "The department ID.",
            "location_id": "The location ID.",
            "name": "The department name.",
            "modified": "The time when the department was last modified.",
        },
    },
    "roles": {
        "description": "Work roles with department assignments and job codes.",
        "docs_url": "https://developers.7shifts.com/reference/listroles",
        "columns": {
            "id": "The role ID.",
            "department_id": "The department ID.",
            "job_code": "The job code for this role.",
            "modified": "The time when the role was last modified, in UTC.",
        },
    },
    "users": {
        "description": "Company employees with contact details, status, and wage settings.",
        "docs_url": "https://developers.7shifts.com/reference/listuserslist",
        "columns": {
            "id": "The user ID.",
            "employee_id": "The employee ID.",
            "active": "Whether the user can log in.",
            "hourly_wage": "The user's current hourly wage, in cents.",
            "modified": "The time when the user was last modified.",
        },
    },
    "shifts": {
        "description": "Published shifts with assignments, scheduled times, and deletion status.",
        "docs_url": "https://developers.7shifts.com/reference/listshift",
        "columns": {
            "id": "The shift ID.",
            "user_id": "The assigned user ID.",
            "start": "The scheduled start time, in UTC.",
            "end": "The scheduled end time, in UTC.",
            "hourly_wage": "The hourly wage for the shift, in cents.",
            "deleted": "Whether the shift was deleted.",
            "modified": "The time when the shift was last modified, in UTC.",
        },
    },
    "time_punches": {
        "description": "Employee time punches with breaks, approval status, and declared tips.",
        "docs_url": "https://developers.7shifts.com/reference/gettimepunches",
        "columns": {
            "id": "The time punch ID.",
            "user_id": "The user who clocked in.",
            "clocked_in": "The time when the user clocked in, in UTC.",
            "clocked_out": "The time when the user clocked out, in UTC.",
            "tips": "The tips declared for the shift, in cents.",
            "modified": "The time when the time punch was last modified, in UTC.",
        },
    },
}
