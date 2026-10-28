from posthog.dataclasses import frozen

API_VERSION = "v1"
API_BASE_URL = f"https://api.testdino.com/api/{API_VERSION}/public"
MANUAL_CASE_LIMIT = 1000


@frozen
class TestDinoEndpoint:
    path: str
    primary_key: str


# Start-time filters cannot find later status changes, so runs need a full refresh.
ENDPOINTS = {
    "test_runs": TestDinoEndpoint(path="test-runs", primary_key="id"),
    "manual_suites": TestDinoEndpoint(path="manual-test-suites", primary_key="_id"),
    "manual_cases": TestDinoEndpoint(path="manual-test-cases", primary_key="_id"),
}

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
