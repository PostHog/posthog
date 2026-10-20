from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import structlog
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.settings import (
    API_BASE_URL,
    ENDPOINTS,
    HISTORY_DAYS,
    MAX_COMPETITORS,
    NON_RETRYABLE_ERRORS,
    TOP_DOMAINS_COUNT,
    TOP_DOMAINS_PAGE_ROWS,
    EndpointSettings,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

logger = structlog.get_logger(__name__)

RESPONSE_ACTIONS: list[ResponseAction] = [
    cast(
        ResponseAction,
        {"status_code": status, "content": content, "action": "raise", "message": "ahrefs_quota_exceeded"},
    )
    for status in (400, 403)
    for content in ("units", "Units", "quota", "Quota")
]
RESPONSE_ACTIONS.extend(
    [
        {"status_code": 402, "action": "raise", "message": "ahrefs_quota_exceeded"},
        {"status_code": 401, "action": "raise", "message": "ahrefs_invalid_api_key"},
        {"status_code": 403, "action": "raise", "message": "ahrefs_access_denied"},
    ]
)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=API_BASE_URL,
        auth=BearerTokenAuth(token=api_key),
        max_retry_attempts=1,
        request_timeout=(10, 60),
    )
    try:
        list(
            client.paginate(
                path="subscription-info/limits-and-usage",
                params={"output": "json"},
                data_selector="limits_and_usage",
                data_selector_required=True,
                paginator=SinglePagePaginator(),
                hooks=create_response_hooks(RESPONSE_ACTIONS),
            )
        )
    except ValueError as error:
        message = NON_RETRYABLE_ERRORS.get(str(error))
        if message is None:
            raise
        return False, message
    return True, None


class RankRangePaginator(BasePaginator):
    def __init__(self, page_rows: int, max_rank: int) -> None:
        super().__init__()
        self.page_rows = page_rows
        self.max_rank = max_rank
        self.start = 1

    def init_request(self, request: Request) -> None:
        self._set_range(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        self.start += self.page_rows
        self._has_next_page = len(data or []) >= self.page_rows and self.start <= self.max_rank

    def update_request(self, request: Request) -> None:
        self._set_range(request)

    def _set_range(self, request: Request) -> None:
        end = min(self.start + self.page_rows - 1, self.max_rank)
        request.params = {**(request.params or {}), "from": self.start, "to": end}


def _lookup(api_key: str, path: str, params: dict[str, str], data_selector: str) -> Iterator[dict[str, Any]]:
    client = RESTClient(base_url=API_BASE_URL, auth=BearerTokenAuth(token=api_key), request_timeout=(10, 60))
    for page in client.paginate(
        path=path,
        params={"output": "json", **params},
        data_selector=data_selector,
        data_selector_required=True,
        paginator=SinglePagePaginator(),
        hooks=create_response_hooks(RESPONSE_ACTIONS),
    ):
        yield from page


def _site_audit_target(api_key: str, project_id: str) -> dict[str, Any]:
    for row in _lookup(api_key, "site-audit/projects", {"project_id": project_id}, "healthscores"):
        if row.get("target_url"):
            return row
    raise ValueError("ahrefs_project_not_found")


def _target_params(api_key: str, project_id: str, names: list[str]) -> dict[str, str]:
    if not names:
        return {}
    project = _site_audit_target(api_key, project_id)
    values = {
        "target": project["target_url"],
        "mode": project.get("target_mode"),
        "protocol": project.get("target_protocol"),
    }
    return {name: value for name, value in values.items() if name in names and value}


def _post(settings: EndpointSettings, body: dict[str, Any]) -> Endpoint:
    return {"path": settings["path"], "method": "POST", "json": {"output": "json", **settings.get("body", {}), **body}}


def _endpoint_requests(
    api_key: str,
    project_id: str,
    endpoint: str,
    settings: EndpointSettings,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[tuple[Endpoint, dict[str, object]]]:
    kind = settings.get("kind")
    if kind == "link_intersect":
        competitors = [
            {"url": row["url"], "mode": row.get("mode") or "subdomains", "protocol": "both"}
            for row in _lookup(api_key, "management/project-competitors", {"project_id": project_id}, "competitors")
            if row.get("url")
        ][:MAX_COMPETITORS]
        if not competitors:
            logger.info("ahrefs_no_project_competitors", endpoint=endpoint, project_id=project_id)
            return
        project = _site_audit_target(api_key, project_id)
        select = [*settings.get("body", {})["select"]]
        select.extend(f"links_to_competitor_{position}" for position in range(1, len(competitors) + 1))
        target = {
            "url": project["target_url"],
            "mode": project.get("target_mode") or "subdomains",
            "protocol": project.get("target_protocol") or "both",
        }
        # links_to_competitor_N columns follow the order of this list.
        competitor_urls: list[str] = [competitor["url"] for competitor in competitors]
        yield (
            _post(settings, {"select": select, "target": target, "competitors": competitors}),
            {"competitors": competitor_urls},
        )
    elif kind == "brand_radar":
        report_ids = [
            str(row["report_id"])
            for row in _lookup(api_key, "management/brand-radar-reports", {}, "reports")
            if row.get("report_id") and str(row.get("project_id")) == project_id
        ]
        if not report_ids:
            logger.info("ahrefs_no_brand_radar_reports", endpoint=endpoint, project_id=project_id)
        for report_id in report_ids:
            yield _post(settings, {"report_id": report_id}), {"report_id": report_id}
    elif kind == "top_domains":
        yield (
            {
                "path": settings["path"],
                "params": {"output": "json"},
                "paginator": RankRangePaginator(TOP_DOMAINS_PAGE_ROWS, TOP_DOMAINS_COUNT),
            },
            {},
        )
    else:
        params: dict[str, Any] = {
            "output": "json",
            **settings["params"],
            **_target_params(api_key, project_id, settings.get("target_params", [])),
        }
        if settings.get("project_scoped", True) and not settings.get("target_params"):
            params["project_id"] = project_id
        if settings.get("history", False):
            params["date_from"] = _history_start(
                should_use_incremental_field, db_incremental_field_last_value, datetime.now(UTC).date()
            )
        if settings.get("snapshot_date"):
            params["date"] = datetime.now(UTC).date().isoformat()
        # Rank Tracker reports one device per request, so each device is read and its rows are tagged with it.
        for device in settings.get("devices", []):
            yield {"path": settings["path"], "params": {**params, "device": device}}, {"device": device}
        if not settings.get("devices"):
            yield {"path": settings["path"], "params": params}, {}


def _history_start(should_use_incremental_field: bool, last_value: Any, today: date) -> str:
    if should_use_incremental_field and last_value:
        if isinstance(last_value, datetime):
            return last_value.date().isoformat()
        if isinstance(last_value, date):
            return last_value.isoformat()
        return date.fromisoformat(str(last_value)[:10]).isoformat()
    return (today - timedelta(days=HISTORY_DAYS)).isoformat()


def _unique_rows(page: list[dict[str, object]], primary_keys: list[str]) -> list[dict[str, object]]:
    seen: set[tuple[object, ...]] = set()
    rows = []
    for row in page:
        key = tuple(row.get(field) for field in primary_keys)
        if key not in seen:
            seen.add(key)
            rows.append(row)
    return rows


def ahrefs_source(
    api_key: str,
    project_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    normalized_project_id = str(int(project_id))
    project_scoped = settings.get("project_scoped", True)
    history = settings.get("history", False)
    row_limit = settings["params"].get("limit") or settings.get("body", {}).get("limit")

    def items() -> Iterator[list[dict[str, object]]]:
        for request, row_fields in _endpoint_requests(
            api_key,
            normalized_project_id,
            endpoint,
            settings,
            should_use_incremental_field,
            db_incremental_field_last_value,
        ):

            def add_project_fields(
                row: dict[str, object], row_fields: dict[str, object] = row_fields
            ) -> dict[str, object]:
                return {**row, "project_id": normalized_project_id, **row_fields}

            config: RESTAPIConfig = {
                "client": {
                    "base_url": API_BASE_URL,
                    "auth": {"type": "bearer", "token": api_key},
                    "paginator": "single_page",
                    "request_timeout": (10, 60),
                },
                "resources": [
                    {
                        "name": endpoint,
                        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
                        if history and should_use_incremental_field
                        else "replace",
                        "endpoint": {
                            **request,
                            "data_selector": settings["data_selector"],
                            "data_selector_required": True,
                            "response_actions": RESPONSE_ACTIONS,
                        },
                        "data_map": add_project_fields if project_scoped else None,
                    }
                ],
            }
            resource = rest_api_resource(config, team_id, job_id, None)
            for page in resource:
                if row_limit is not None and len(page) >= int(row_limit):
                    logger.info("ahrefs_sample_limit_reached", team_id=team_id, endpoint=endpoint, limit=row_limit)
                    page = page[: int(row_limit)]
                page = _unique_rows(page, settings["primary_keys"])
                if history:
                    page = sorted(page, key=lambda row: str(row.get("date") or ""))
                yield page

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=settings["primary_keys"],
        sort_mode="asc" if history else None,
        supports_resume=False,
    )
