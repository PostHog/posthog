from typing import TypedDict


class SemrushEndpoint(TypedDict):
    path: str
    selector: str
    primary_key: str


API_VERSION = "v1"
BASE_URL = f"https://api.semrush.com/reports/{API_VERSION}/projects/"
API_DOCS_URL = "https://developer.semrush.com/api/v3/projects/site-audit/"
MAX_REQUEST_ATTEMPTS = 3

ENDPOINTS: dict[str, SemrushEndpoint] = {
    "site_audit": {"path": "info", "selector": "$", "primary_key": "id"},
    "site_audit_snapshots": {"path": "snapshots", "selector": "snapshots", "primary_key": "snapshot_id"},
    "site_audit_issue_descriptions": {"path": "meta/issues", "selector": "issues", "primary_key": "id"},
}

AUTH_ERROR = "Semrush authentication failed. Check your v3 API key in your Semrush profile."
ACCESS_ERROR = "Semrush API access is disabled. Check your SEO Business subscription and project access."
QUOTA_ERROR = "Semrush API units or request limits are exhausted. Add API units or contact Semrush support."
PROJECT_ERROR = "Semrush could not find this project. Check the project ID and your access to it."
PROJECT_ID_ERROR = "Enter the numeric project ID from your Semrush project URL."
REQUEST_ERROR = "Semrush rejected the request. Check your project ID, Site Audit setup, and API access."
UNAVAILABLE_ERROR = "Semrush is unavailable or rate-limiting requests. Try again later."

ERROR_MESSAGES = {
    70: AUTH_ERROR,
    120: AUTH_ERROR,
    121: AUTH_ERROR,
    122: AUTH_ERROR,
    130: ACCESS_ERROR,
    131: QUOTA_ERROR,
    132: QUOTA_ERROR,
    134: QUOTA_ERROR,
    512: PROJECT_ERROR,
}
