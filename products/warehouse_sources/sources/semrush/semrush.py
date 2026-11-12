import io
import re
import csv
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Optional
from urllib.parse import urlparse

from requests import RequestException, Response

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    EndpointResource,
    PageNumberPaginator,
    Resource,
    ResponseAction,
    RESTAPIConfig,
    RESTClientRetryableError,
    SourceResponse,
    build_chained_resource,
    make_tracked_session,
    rest_api_resource,
    schema_for_resource,
)
from products.warehouse_sources.sources.semrush.settings import (
    ACCESS_ERROR,
    API_HOST,
    AUTH_ERROR,
    BASE_URL,
    DEFAULT_DATABASE,
    DOMAIN_ERROR,
    DOMAIN_REPORT_ERROR,
    DOMAIN_REPORT_ERROR_MESSAGES,
    DOMAIN_REPORT_NOTHING_FOUND,
    DOMAIN_REPORT_ROW_LIMIT,
    DOMAIN_REPORT_TIMEOUT,
    DOMAIN_REPORTS,
    ENDPOINTS,
    ERROR_MESSAGES,
    ISSUE_DETAILS_PAGE_SIZE,
    MAX_REQUEST_ATTEMPTS,
    PROJECT_ID_ERROR,
    REQUEST_ERROR,
    REQUEST_TIMEOUT,
    SITE_AUDIT_HISTORY,
    SITE_AUDIT_ISSUE_DETAILS,
    UNAVAILABLE_ERROR,
    DomainReportColumn,
)

MISSING_ID_ERROR = "Semrush returned a record without its ID."
DOMAIN_REPORT_ROW_ERROR = "Semrush returned a domain report row with an unexpected number of columns."
DOMAIN_REPORT_TRANSIENT_CODES = {429, 500}


def validate_project_id(project_id: str) -> None:
    if re.fullmatch(r"[0-9]+", project_id) is None:
        raise ValueError(PROJECT_ID_ERROR)


def normalize_row(row: dict[str, object], project_id: str, primary_key: str) -> dict[str, object]:
    if row.get(primary_key) is None:
        raise ValueError(MISSING_ID_ERROR)
    return {**row, "project_id": project_id}


def _response_actions(ignore_not_found: bool = False) -> list[ResponseAction]:
    error_actions: list[ResponseAction] = [
        {"json_field": "code", "json_values": [code, str(code)], "action": "raise", "message": message}
        for code, message in ERROR_MESSAGES.items()
    ]
    client_error_actions: list[ResponseAction] = [
        {"status_code": status, "action": "raise", "message": REQUEST_ERROR}
        for status in range(400, 500)
        if status != 429
    ]
    # An issue the latest audit no longer reports can 404 between the info and detail requests.
    not_found: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}] if ignore_not_found else []
    return [
        {"status_code": 401, "action": "raise", "message": AUTH_ERROR},
        {"status_code": 403, "action": "raise", "message": ACCESS_ERROR},
        *not_found,
        *error_actions,
        {"json_field": "code", "json_values": [511, "511"], "action": "retry", "message": "Semrush temporary error."},
        *client_error_actions,
    ]


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "api_key", "name": "key", "api_key": api_key, "location": "query"},
        "paginator": "single_page",
        "max_retries": MAX_REQUEST_ATTEMPTS,
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT,
    }


def semrush_resource(api_key: str, project_id: str, endpoint: str, team_id: int, job_id: str) -> Resource:
    validate_project_id(project_id)
    settings = schema_for_resource(ENDPOINTS, endpoint)
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": endpoint,
                "write_disposition": "replace",
                "endpoint": {
                    "path": f"{project_id}/siteaudit/{settings['path']}",
                    "data_selector": settings["selector"],
                    "data_selector_required": True,
                    "response_actions": _response_actions(),
                },
                "data_map": lambda row: normalize_row(row, project_id, settings["primary_key"]),
            }
        ],
    }
    return rest_api_resource(config, team_id, job_id, None)


def _first_row(resource: Iterable[Any]) -> dict[str, Any] | None:
    for page in resource:
        for row in page:
            return row
    return None


def _snapshot_id(row: dict[str, Any]) -> str:
    snapshot_id = row.get("snapshot_id")
    if not isinstance(snapshot_id, str) or re.fullmatch(r"[0-9A-Za-z_-]+", snapshot_id) is None:
        raise ValueError(MISSING_ID_ERROR)
    return snapshot_id


class IssueRowsPaginator(PageNumberPaginator):
    """Stops once the rows read reach `total`, which Semrush reports as a row count, not a page count."""

    def __init__(self) -> None:
        super().__init__(base_page=1)
        self.rows_read = 0

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = len(data or [])
        self.rows_read += rows
        try:
            body = response.json()
        except ValueError:
            body = None
        total = body.get("total") if isinstance(body, dict) else None
        if rows == 0 or (isinstance(total, int) and self.rows_read >= total):
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True


def _history_resource(
    api_key: str, project_id: str, team_id: int, job_id: str, last_finish_date: Any, incremental: bool
) -> Iterable[Any]:
    def new_snapshots(row: dict[str, Any]) -> list[dict[str, Any]]:
        _snapshot_id(row)
        finish_date = row.get("finish_date")
        if last_finish_date is not None and isinstance(finish_date, int) and finish_date <= last_finish_date:
            return []
        return [row]

    parent: EndpointResource = {
        "name": "site_audit_snapshots",
        "write_disposition": "replace",
        "endpoint": {
            "path": f"{project_id}/siteaudit/snapshots",
            "data_selector": "snapshots",
            "data_selector_required": True,
            "paginator": "single_page",
            "response_actions": _response_actions(),
        },
        # The snapshot list costs 100 API units; each snapshot's details cost 10,000. An
        # incremental sync reads the list and fetches details only for snapshots it has not loaded.
        "data_map": new_snapshots,
    }
    child: EndpointResource = {
        "name": SITE_AUDIT_HISTORY,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        "include_from_parent": ["snapshot_id", "finish_date"],
        "endpoint": {
            "path": f"{project_id}/siteaudit/snapshot?snapshot_id={{snapshot_id}}",
            "params": {"snapshot_id": {"type": "resolve", "resource": "site_audit_snapshots", "field": "snapshot_id"}},
            "data_selector": "$",
            "data_selector_required": True,
            "paginator": "single_page",
            "response_actions": _response_actions(),
        },
        "data_map": lambda row: {**row, "project_id": project_id},
    }
    return build_chained_resource(
        resources=[parent, child],
        child_name=SITE_AUDIT_HISTORY,
        parent_name="site_audit_snapshots",
        parent_field_renames={"snapshot_id": "snapshot_id", "finish_date": "finish_date"},
        client_config=_client_config(api_key),
        team_id=team_id,
        job_id=job_id,
    )


def _detected_issues(info: dict[str, Any]) -> list[dict[str, Any]]:
    defects = info.get("defects")
    if not isinstance(defects, dict):
        return []
    return [{"issue_id": int(issue_id)} for issue_id, count in defects.items() if str(issue_id).isdigit() and count]


def _issue_details_resource(api_key: str, project_id: str, team_id: int, job_id: str) -> Iterable[Any]:
    snapshots = [
        row for page in semrush_resource(api_key, project_id, "site_audit_snapshots", team_id, job_id) for row in page
    ]
    if not snapshots:
        return []
    latest = max(snapshots, key=lambda row: row.get("finish_date") or 0)
    snapshot_id = _snapshot_id(latest)

    parent: EndpointResource = {
        "name": "site_audit",
        "write_disposition": "replace",
        "endpoint": {
            "path": f"{project_id}/siteaudit/info",
            "data_selector": "$",
            "data_selector_required": True,
            "paginator": "single_page",
            "response_actions": _response_actions(),
        },
        # Only issues the latest audit found have affected URLs, so each one costs a request.
        "data_map": _detected_issues,
    }
    child: EndpointResource = {
        "name": SITE_AUDIT_ISSUE_DETAILS,
        "write_disposition": "replace",
        "include_from_parent": ["issue_id"],
        "endpoint": {
            "path": f"{project_id}/siteaudit/snapshot/{snapshot_id}/issue/{{issue_id}}",
            "params": {
                "issue_id": {"type": "resolve", "resource": "site_audit", "field": "issue_id"},
                "limit": ISSUE_DETAILS_PAGE_SIZE,
            },
            "data_selector": "data",
            "paginator": IssueRowsPaginator(),
            "response_actions": _response_actions(ignore_not_found=True),
        },
        "data_map": lambda row: {**row, "project_id": project_id, "snapshot_id": snapshot_id},
    }
    return build_chained_resource(
        resources=[parent, child],
        child_name=SITE_AUDIT_ISSUE_DETAILS,
        parent_name="site_audit",
        parent_field_renames={"issue_id": "issue_id"},
        client_config=_client_config(api_key),
        team_id=team_id,
        job_id=job_id,
    )


def _report_domain(api_key: str, project_id: str, domain: str | None, team_id: int, job_id: str) -> str:
    value = (domain or "").strip()
    if not value:
        info = _first_row(semrush_resource(api_key, project_id, "site_audit", team_id, job_id)) or {}
        value = str(info.get("url") or "").strip()
    host = urlparse(value if "//" in value else f"//{value}").hostname
    if not host:
        raise ValueError(DOMAIN_ERROR)
    return host


def _parse_value(column: DomainReportColumn, value: str) -> object:
    if column["kind"] == "str":
        return value
    if value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return int(number) if column["kind"] == "int" else number


def _domain_report_rows(
    api_key: str, endpoint: str, domain: Callable[[], str], database: str
) -> Iterator[list[dict[str, Any]]]:
    report = DOMAIN_REPORTS[endpoint]
    columns = report["columns"]
    report_domain = domain()
    params: dict[str, str | int] = {
        "type": report["type"],
        "key": api_key,
        "domain": report_domain,
        "database": database,
        "display_limit": DOMAIN_REPORT_ROW_LIMIT,
        "display_sort": report["sort"],
        "export_columns": ",".join(column["code"] for column in columns),
        "export_escape": 1,
    }
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    response = session.get(
        API_HOST,
        params=params,
        timeout=DOMAIN_REPORT_TIMEOUT,
    )
    text = response.text.strip()
    error = re.match(r"ERROR\s+(\d+)\s*::", text)
    if error:
        code = int(error.group(1))
        if code == DOMAIN_REPORT_NOTHING_FOUND:
            return
        if code in DOMAIN_REPORT_TRANSIENT_CODES:
            raise RESTClientRetryableError(UNAVAILABLE_ERROR)
        raise ValueError(DOMAIN_REPORT_ERROR_MESSAGES.get(code, DOMAIN_REPORT_ERROR))
    if response.status_code == 401:
        raise ValueError(AUTH_ERROR)
    if response.status_code == 403:
        raise ValueError(ACCESS_ERROR)
    response.raise_for_status()

    reader = csv.reader(io.StringIO(text), delimiter=";")
    next(reader, None)
    rows: list[dict[str, Any]] = []
    for line in reader:
        if not line:
            continue
        if len(line) != len(columns):
            raise ValueError(DOMAIN_REPORT_ROW_ERROR)
        row: dict[str, Any] = {column["name"]: _parse_value(column, value) for column, value in zip(columns, line)}
        rows.append({"domain": report_domain, "database": database, **row})
    if rows:
        yield rows


def validate_credentials(api_key: str, project_id: str, team_id: int) -> tuple[bool, str | None]:
    try:
        list(semrush_resource(api_key, project_id, "site_audit", team_id, ""))
    except ValueError as error:
        message = str(error)
        if message in {*ERROR_MESSAGES.values(), PROJECT_ID_ERROR, REQUEST_ERROR}:
            return False, message
        raise
    except (RequestException, RESTClientRetryableError):
        return False, UNAVAILABLE_ERROR
    return True, None


def semrush_source(
    api_key: str,
    project_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    domain: str | None = None,
    database: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    validate_project_id(project_id)

    if endpoint == SITE_AUDIT_HISTORY:
        last_value = db_incremental_field_last_value if should_use_incremental_field else None
        return SourceResponse(
            name=endpoint,
            items=lambda: _history_resource(
                api_key, project_id, team_id, job_id, last_value, should_use_incremental_field
            ),
            primary_keys=["project_id", "snapshot_id"],
        )

    if endpoint == SITE_AUDIT_ISSUE_DETAILS:
        return SourceResponse(
            name=endpoint,
            items=lambda: _issue_details_resource(api_key, project_id, team_id, job_id),
            primary_keys=["project_id", "snapshot_id", "issue_id", "source_url", "target_url"],
        )

    if endpoint in DOMAIN_REPORTS:
        report_database = (database or "").strip().lower() or DEFAULT_DATABASE
        return SourceResponse(
            name=endpoint,
            items=lambda: _domain_report_rows(
                api_key,
                endpoint,
                lambda: _report_domain(api_key, project_id, domain, team_id, job_id),
                report_database,
            ),
            primary_keys=DOMAIN_REPORTS[endpoint]["primary_keys"],
        )

    resource = semrush_resource(api_key, project_id, endpoint, team_id, job_id)
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["project_id", ENDPOINTS[endpoint]["primary_key"]],
    )
