from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)

API_VERSION = "v1"
API_BASE_URL = f"https://api.testdino.com/api/{API_VERSION}/public"
MANUAL_CASE_LIMIT = 1000


@frozen
class TestDinoEndpoint:
    name: str
    path: str
    primary_keys: tuple[str, ...]
    page_size: int = 100
    params: dict[str, Any] = field(default_factory=dict)
    fanout: DependentEndpointConfig | None = None
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: str | None = None


# Start-time filters cannot find later status changes, so runs need a full refresh.
# Manual runs and their cases have no server-side updated-time filter, so they need a full refresh too.
ENDPOINTS = {
    "test_runs": TestDinoEndpoint(
        name="test_runs", path="test-runs", primary_keys=("id",), params={"sort": "counter_asc"}
    ),
    "manual_suites": TestDinoEndpoint(name="manual_suites", path="manual-test-suites", primary_keys=("_id",)),
    "manual_cases": TestDinoEndpoint(name="manual_cases", path="manual-test-cases", primary_keys=("_id",)),
    "manual_runs": TestDinoEndpoint(
        name="manual_runs",
        path="manual-runs",
        primary_keys=("_id",),
        page_size=200,
        params={"sortBy": "createdAt", "sortOrder": "asc"},
    ),
    # TestDino creates the per-case record of an untested case only on its first edit, so `_id` is not stable.
    "manual_run_test_cases": TestDinoEndpoint(
        name="manual_run_test_cases",
        path="manual-runs/{run_id}/test-cases",
        primary_keys=("manual_run_id", "caseKey"),
        page_size=200,
        fanout=DependentEndpointConfig(
            parent_name="manual_runs",
            resolve_param="run_id",
            resolve_field="_id",
            include_from_parent=["_id"],
            parent_field_renames={"_id": "manual_run_id"},
            parent_params={"sortBy": "createdAt", "sortOrder": "asc"},
            child_params={"sortBy": "caseKey", "sortOrder": "asc"},
            # A run deleted after the run list was read returns 404. Skip it and keep the other runs.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

PAGED_ENDPOINTS = {"test_runs", "manual_runs"}

INVALID_TOKEN = "TestDino rejected the token. Create a personal access token in User Settings > Personal Access Tokens."
PROJECT_ACCESS_ERROR = "TestDino could not access this project. Check the project ID and the projects allowed by your personal access token."
INVALID_PROJECT = "Enter a TestDino project ID using only letters, numbers, underscores, and hyphens."
CASE_LIMIT_ERROR = (
    "TestDino returned the 1,000-case API limit. The result can be incomplete. "
    "Disable the manual_cases table for this project."
)
HTTP_ERRORS = {
    400: "TestDino rejected the request. Check the project ID and connection settings.",
    401: INVALID_TOKEN,
    403: PROJECT_ACCESS_ERROR,
    404: PROJECT_ACCESS_ERROR,
}
