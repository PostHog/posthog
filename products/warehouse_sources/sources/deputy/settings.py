from dataclasses import dataclass

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

# The Resource API lives under /api/v1. Deputy also serves some endpoints under /api/v2, but v2 has no
# list call with a modified-since filter for timesheets, rosters or most other tables.
API_VERSION = "v1"

# Deputy returns at most 500 records per QUERY call.
PAGE_SIZE = 500

PRIMARY_KEY = "Id"
MODIFIED_FIELD = "Modified"
CREATED_FIELD = "Created"


@dataclass(frozen=True)
class DeputyEndpointConfig:
    # The Resource API object name, as in /api/v1/resource/{resource}/QUERY.
    resource: str


# Every Resource API object carries `Created` and `Modified`, and QUERY can filter and sort on
# `Modified`, so every table supports incremental sync.
DEPUTY_ENDPOINTS: dict[str, DeputyEndpointConfig] = {
    "companies": DeputyEndpointConfig(resource="Company"),
    "contacts": DeputyEndpointConfig(resource="Contact"),
    "employee_agreements": DeputyEndpointConfig(resource="EmployeeAgreement"),
    "employee_availability": DeputyEndpointConfig(resource="EmployeeAvailability"),
    "employee_roles": DeputyEndpointConfig(resource="EmployeeRole"),
    "employees": DeputyEndpointConfig(resource="Employee"),
    "events": DeputyEndpointConfig(resource="Event"),
    "journals": DeputyEndpointConfig(resource="Journal"),
    "leave": DeputyEndpointConfig(resource="Leave"),
    "memos": DeputyEndpointConfig(resource="Memo"),
    "operational_units": DeputyEndpointConfig(resource="OperationalUnit"),
    "rosters": DeputyEndpointConfig(resource="Roster"),
    "tasks": DeputyEndpointConfig(resource="Task"),
    "timesheet_pay_returns": DeputyEndpointConfig(resource="TimesheetPayReturn"),
    "timesheets": DeputyEndpointConfig(resource="Timesheet"),
}

ENDPOINTS = tuple(DEPUTY_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": MODIFIED_FIELD,
            "type": IncrementalFieldType.DateTime,
            "field": MODIFIED_FIELD,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name in ENDPOINTS
}
