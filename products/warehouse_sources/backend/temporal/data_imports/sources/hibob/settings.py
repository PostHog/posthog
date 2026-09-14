from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class HiBobEndpointConfig:
    name: str
    path: str
    # Key the rows live under in the response body.
    data_key: str
    # HiBob's primary employee read is a POST-for-read with a JSON body.
    method: Literal["GET", "POST"] = "GET"
    body: Optional[dict] = None
    primary_key: str = "id"


# Name of the employee time-off calendars stream. It fans out over employee ids
# (the search endpoint resolves the holiday calendar per employee), so it needs
# bespoke transport rather than the shared single-page path — routed by name in
# hibob.py.
TIME_OFF_CALENDARS = "time_off_calendars"

# HiBob has no updated-at filter on employees (Airbyte is full-refresh only and
# Fivetran re-imports most tables every sync), so every stream is an honest
# full refresh. The time off changes endpoint has a `since` param but its rows
# carry no verifiable per-change timestamp to use as a watermark — deferred.
HIBOB_ENDPOINTS: dict[str, HiBobEndpointConfig] = {
    "employees": HiBobEndpointConfig(
        name="employees",
        path="/v1/people/search",
        data_key="employees",
        method="POST",
        # humanReadable=REPLACE flattens list/reference values into readable
        # strings; showInactive includes offboarded employees.
        body={"showInactive": True, "humanReadable": "REPLACE"},
    ),
    "tasks": HiBobEndpointConfig(
        name="tasks",
        path="/v1/tasks",
        data_key="tasks",
    ),
    TIME_OFF_CALENDARS: HiBobEndpointConfig(
        name=TIME_OFF_CALENDARS,
        path="/v1/timeoff/calendars/employees/search",
        data_key="items",
        method="POST",
        # One resolved calendar per employee, so the employee id is table-wide unique.
        primary_key="employeeId",
    ),
}

ENDPOINTS = tuple(HIBOB_ENDPOINTS.keys())

# No endpoint carries a usable updated-at watermark, so every stream is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
