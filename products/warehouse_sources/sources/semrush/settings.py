from typing import Literal, TypedDict

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


class SemrushEndpoint(TypedDict):
    path: str
    selector: str
    primary_key: str


class DomainReportColumn(TypedDict):
    code: str
    name: str
    kind: Literal["str", "int", "float"]


class DomainReport(TypedDict):
    type: str
    sort: str
    columns: list[DomainReportColumn]
    primary_keys: list[str]


API_VERSION = "v1"
API_HOST = "https://api.semrush.com/"
BASE_URL = f"{API_HOST}reports/{API_VERSION}/projects/"
API_DOCS_URL = "https://developer.semrush.com/api/v3/projects/site-audit/"
DOMAIN_REPORTS_DOCS_URL = "https://developer.semrush.com/api/v3/analytics/domain-reports/"
MAX_REQUEST_ATTEMPTS = 3
REQUEST_TIMEOUT = (10, 30)
DOMAIN_REPORT_TIMEOUT = (10, 120)

ENDPOINTS: dict[str, SemrushEndpoint] = {
    "site_audit": {"path": "info", "selector": "$", "primary_key": "id"},
    "site_audit_snapshots": {"path": "snapshots", "selector": "snapshots", "primary_key": "snapshot_id"},
    "site_audit_issue_descriptions": {"path": "meta/issues", "selector": "issues", "primary_key": "id"},
}

SITE_AUDIT_HISTORY = "site_audit_history"
SITE_AUDIT_ISSUE_DETAILS = "site_audit_issue_details"
ISSUE_DETAILS_PAGE_SIZE = 100

DOMAIN_ORGANIC_KEYWORDS = "domain_organic_keywords"
DOMAIN_ORGANIC_COMPETITORS = "domain_organic_competitors"
DEFAULT_DATABASE = "us"
# Domain reports cost API units per returned line, so a sync reads the top rows only.
DOMAIN_REPORT_ROW_LIMIT = 10_000

DOMAIN_REPORTS: dict[str, DomainReport] = {
    DOMAIN_ORGANIC_KEYWORDS: {
        "type": "domain_organic",
        "sort": "tr_desc",
        "columns": [
            {"code": "Ph", "name": "keyword", "kind": "str"},
            {"code": "Po", "name": "position", "kind": "int"},
            {"code": "Pp", "name": "previous_position", "kind": "int"},
            {"code": "Pd", "name": "position_difference", "kind": "int"},
            {"code": "Nq", "name": "search_volume", "kind": "int"},
            {"code": "Cp", "name": "cpc", "kind": "float"},
            {"code": "Ur", "name": "url", "kind": "str"},
            {"code": "Tr", "name": "traffic_percent", "kind": "float"},
            {"code": "Tc", "name": "traffic_cost_percent", "kind": "float"},
            {"code": "Co", "name": "competition", "kind": "float"},
            {"code": "Nr", "name": "number_of_results", "kind": "int"},
            {"code": "Td", "name": "trends", "kind": "str"},
            {"code": "Kd", "name": "keyword_difficulty", "kind": "float"},
            {"code": "Ts", "name": "timestamp", "kind": "int"},
        ],
        "primary_keys": ["domain", "database", "keyword", "url"],
    },
    DOMAIN_ORGANIC_COMPETITORS: {
        "type": "domain_organic_organic",
        "sort": "np_desc",
        "columns": [
            {"code": "Dn", "name": "competitor_domain", "kind": "str"},
            {"code": "Cr", "name": "competitor_relevance", "kind": "float"},
            {"code": "Np", "name": "common_keywords", "kind": "int"},
            {"code": "Or", "name": "organic_keywords", "kind": "int"},
            {"code": "Ot", "name": "organic_traffic", "kind": "int"},
            {"code": "Oc", "name": "organic_cost", "kind": "float"},
            {"code": "Ad", "name": "adwords_keywords", "kind": "int"},
        ],
        "primary_keys": ["domain", "database", "competitor_domain"],
    },
}

TABLES = [*ENDPOINTS, SITE_AUDIT_HISTORY, SITE_AUDIT_ISSUE_DETAILS, *DOMAIN_REPORTS]

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    SITE_AUDIT_HISTORY: [
        {
            "label": "Audit finish date",
            "type": IncrementalFieldType.Integer,
            "field": "finish_date",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
}

AUTH_ERROR = "Semrush authentication failed. Check your v3 API key in your Semrush profile."
ACCESS_ERROR = "Semrush API access is disabled. Check your SEO Business subscription and project access."
QUOTA_ERROR = "Semrush API units or request limits are exhausted. Add API units or contact Semrush support."
PROJECT_ERROR = "Semrush could not find this project. Check the project ID and your access to it."
PROJECT_ID_ERROR = "Enter the numeric project ID from your Semrush project URL."
REQUEST_ERROR = "Semrush rejected the request. Check your project ID, Site Audit setup, and API access."
UNAVAILABLE_ERROR = "Semrush is unavailable or rate-limiting requests. Try again later."
DATABASE_ACCESS_ERROR = "Your Semrush plan can't access this regional database. Choose another database."
DOMAIN_REPORT_ERROR = "Semrush rejected the domain report request. Check the domain and regional database settings."
DOMAIN_ERROR = "Semrush returned no URL for this project. Enter a domain in the source settings."

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

DOMAIN_REPORT_ERROR_MESSAGES = {
    110: AUTH_ERROR,
    120: AUTH_ERROR,
    130: ACCESS_ERROR,
    131: QUOTA_ERROR,
    132: QUOTA_ERROR,
    133: DATABASE_ACCESS_ERROR,
    134: QUOTA_ERROR,
    135: ACCESS_ERROR,
}
# "ERROR 50 :: NOTHING FOUND" means the domain has no rows in this database.
DOMAIN_REPORT_NOTHING_FOUND = 50
