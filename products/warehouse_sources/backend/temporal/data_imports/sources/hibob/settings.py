from dataclasses import dataclass
from typing import Literal, Optional


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
}

ENDPOINTS = tuple(HIBOB_ENDPOINTS.keys())
