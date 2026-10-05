from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class HiBobEndpointConfig:
    name: str
    path: str
    # Key the rows live under in the response body.
    data_key: str
    # HiBob's primary employee read is a POST-for-read with a JSON body.
    method: Literal["GET", "POST"] = "GET"
    body: Optional[dict] = None
    params: Optional[dict] = None
    primary_keys: tuple[str, ...] = ("id",)
    # Where the cursor goes on the next request. None means the endpoint returns everything in one response.
    cursor_location: Optional[Literal["query", "json"]] = None
    # "employee_history": rows are nested per employee under `values` and need flattening.
    # "pointer_keys": rows are keyed by JSON pointers (e.g. `/candidate/id`) and need leaf keys.
    row_shape: Literal["flat", "employee_history", "pointer_keys"] = "flat"


# Max page size the cursor-paginated bulk tables and hiring searches accept.
BULK_PAGE_LIMIT = 200

# History entry ids are only documented as unique within one employee's table.
HISTORY_PRIMARY_KEYS = ("employeeId", "id")

CANDIDATE_FIELDS = (
    "/candidate/id",
    "/candidate/firstName",
    "/candidate/lastName",
    "/candidate/email",
    "/candidate/phone",
    "/candidate/title",
    "/candidate/address",
    "/candidate/photo",
    "/candidate/languages",
    "/candidate/skills",
    "/candidate/socialMedia",
    "/candidate/socialMediaLinkedIn",
    "/candidate/socialMediaFacebook",
    "/candidate/socialMediaInstagram",
    "/candidate/socialMediaThreads",
    "/candidate/socialMediaTwitter",
    "/candidate/socialMediaYouTube",
    "/candidate/socialMediaMedium",
    "/candidate/socialMediaGitHub",
    "/candidate/socialMediaReddit",
    "/candidate/socialMediaXing",
    "/candidate/socialMediaPersonalWebsite",
    "/candidate/country",
    "/candidate/city",
    "/candidate/region",
    "/candidate/education",
    "/candidate/experience",
    "/candidate/employeeId",
    "/candidate/externalUserId",
    "/candidate/importExternalId",
    "/candidate/sourceId",
    "/candidate/sourceEffectiveDate",
    "/candidate/extendConsentDueDate",
    "/candidate/extendedConsentRequestedAt",
    "/candidate/anonymizedAt",
    "/candidate/jobOpeningsToApplicationIds",
    "/candidate/dataDownloadFileId",
    "/candidate/dataDownloadRequestedAt",
    "/candidate/dataDeletionRequestedAt",
    "/candidate/dataDownloadedAt",
    "/candidate/sourceType",
    "/candidate/sourceApplicationId",
    "/candidate/sourceInstanceId",
    "/candidate/meetingBotEnabled",
    "/candidate/modificationDate",
)

# Name of the employee time-off calendars stream. It fans out over employee ids
# (the search endpoint resolves the holiday calendar per employee), so it needs
# bespoke transport rather than the shared single-page path — routed by name in
# hibob.py.
TIME_OFF_CALENDARS = "time_off_calendars"

# HiBob has no updated-at filter on employees (Airbyte is full-refresh only and
# Fivetran re-imports most tables every sync), so every stream is an honest
# full refresh. The time off changes endpoint has a `since` param but its rows
# carry no verifiable per-change timestamp to use as a watermark — deferred.
# Candidates search accepts a `modificationDate` filter, but neither its value
# format nor the result order is documented — deferred.
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
        primary_keys=("employeeId",),
    ),
    "employee_lifecycle": HiBobEndpointConfig(
        name="employee_lifecycle",
        path="/v1/bulk/people/lifecycle",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "employee_employment": HiBobEndpointConfig(
        name="employee_employment",
        path="/v1/bulk/people/employment",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "employee_salaries": HiBobEndpointConfig(
        name="employee_salaries",
        path="/v1/bulk/people/salaries",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "candidates": HiBobEndpointConfig(
        name="candidates",
        path="/v1/hiring/candidates/search",
        data_key="items",
        method="POST",
        # The search returns only the fields requested, so ask for every documented candidate field.
        body={"fields": list(CANDIDATE_FIELDS), "filters": [], "limit": BULK_PAGE_LIMIT},
        cursor_location="json",
        row_shape="pointer_keys",
    ),
}

ENDPOINTS = tuple(HIBOB_ENDPOINTS.keys())

# No endpoint carries a usable updated-at watermark, so every stream is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
