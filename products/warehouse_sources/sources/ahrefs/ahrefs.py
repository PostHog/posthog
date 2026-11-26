from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import structlog
from requests import Request, Response

from products.warehouse_sources.sources.ahrefs.settings import (
    API_BASE_URL,
    BRAND_RADAR_DATA_SOURCES,
    BRAND_RADAR_HISTORY_LOOKBACK_DAYS,
    CREDENTIAL_ERRORS,
    ENDPOINTS,
    HISTORY_DAYS,
    MAX_COMPETITORS,
    SITE_METRICS_FIRST_SYNC_DAYS,
    SITE_METRICS_MAX_SYNC_DAYS,
    TOP_DOMAINS_COUNT,
    TOP_DOMAINS_PAGE_ROWS,
    DailyReport,
    EndpointSettings,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    BearerTokenAuth,
    Endpoint,
    ResponseAction,
    RESTAPIConfig,
    RESTClient,
    SinglePagePaginator,
    SourceResponse,
    create_response_hooks,
    reach_safe_point,
    rest_api_resource,
    schema_for_resource,
)

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


def validate_credentials(api_key: str, project_id: str) -> tuple[bool, str | None]:
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
        # A key can pass the probe above and still get 403 on project data. Without this check,
        # the source is created and every project table fails on its first sync.
        list(_lookup(api_key, "site-audit/projects", {"project_id": project_id}, "healthscores", client))
    except ValueError as error:
        message = CREDENTIAL_ERRORS.get(str(error))
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


def _lookup(
    api_key: str, path: str, params: dict[str, str], data_selector: str, client: RESTClient | None = None
) -> Iterator[dict[str, Any]]:
    client = client or RESTClient(base_url=API_BASE_URL, auth=BearerTokenAuth(token=api_key), request_timeout=(10, 60))
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


def _project_target_params(project: dict[str, Any], names: list[str]) -> dict[str, str]:
    values = {
        "target": project["target_url"],
        "mode": project.get("target_mode"),
        "protocol": project.get("target_protocol"),
    }
    return {name: value for name, value in values.items() if name in names and value}


def _target_params(api_key: str, project_id: str, names: list[str]) -> dict[str, str]:
    if not names:
        return {}
    return _project_target_params(_site_audit_target(api_key, project_id), names)


def _brand_radar_reports(api_key: str, project_id: str) -> list[dict[str, Any]]:
    return [
        row
        for row in _lookup(api_key, "management/brand-radar-reports", {}, "reports")
        if row.get("report_id") and str(row.get("project_id")) == project_id
    ]


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
        report_ids = [str(row["report_id"]) for row in _brand_radar_reports(api_key, project_id)]
        if not report_ids:
            logger.info("ahrefs_no_brand_radar_reports", endpoint=endpoint, project_id=project_id)
        for report_id in report_ids:
            yield _post(settings, {"report_id": report_id}), {"report_id": report_id}
    elif kind == "brand_radar_history":
        reports = _brand_radar_reports(api_key, project_id)
        if not reports:
            logger.info("ahrefs_no_brand_radar_reports", endpoint=endpoint, project_id=project_id)
        date_from = _history_start(
            should_use_incremental_field,
            db_incremental_field_last_value,
            datetime.now(UTC).date(),
            lookback_days=BRAND_RADAR_HISTORY_LOOKBACK_DAYS,
        )
        for report in reports:
            report_id = str(report["report_id"])
            # Mentions are matched against brand names, so the API rejects brands that only have URL groups.
            brands = [
                {"names": brand["names"]}
                for brand in (report.get("settings") or {}).get("brands") or []
                if brand.get("names")
            ]
            if not brands:
                logger.info("ahrefs_brand_radar_report_without_brand_names", endpoint=endpoint, report_id=report_id)
                continue
            # The response has no platform column, so each platform is read on its own and its rows are tagged.
            for data_source in BRAND_RADAR_DATA_SOURCES:
                body = {"report_id": report_id, "brands": brands, "data_source": [data_source], "date_from": date_from}
                yield _post(settings, body), {"report_id": report_id, "data_source": data_source}
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


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _history_start(should_use_incremental_field: bool, last_value: Any, today: date, lookback_days: int = 0) -> str:
    if should_use_incremental_field and last_value:
        return (_as_date(last_value) - timedelta(days=lookback_days)).isoformat()
    return (today - timedelta(days=HISTORY_DAYS)).isoformat()


def _site_metrics_dates(should_use_incremental_field: bool, last_value: Any, today: date) -> list[date]:
    # Each day costs API units, so an incremental sync starts after the last synced day.
    if should_use_incremental_field and last_value:
        start = max(_as_date(last_value) + timedelta(days=1), today - timedelta(days=SITE_METRICS_MAX_SYNC_DAYS - 1))
    else:
        start = today - timedelta(days=SITE_METRICS_FIRST_SYNC_DAYS - 1)
    return [start + timedelta(days=offset) for offset in range((today - start).days + 1)]


def _site_metrics_rows(
    api_key: str,
    project_id: str,
    reports: list[DailyReport],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, object]]]:
    dates = _site_metrics_dates(should_use_incremental_field, db_incremental_field_last_value, datetime.now(UTC).date())
    if not dates:
        return
    project = _site_audit_target(api_key, project_id)
    # No row is fetched yet, so the run can stop here before the reports of the first day.
    reach_safe_point()
    for day in dates:
        row: dict[str, object] = {"project_id": project_id, "target": project["target_url"], "date": day.isoformat()}
        for report in reports:
            params = {**_project_target_params(project, report["target_params"]), "date": day.isoformat()}
            values = list(_lookup(api_key, report["path"], params, report["data_selector"]))
            found = values[0] if values else {}
            row.update({column: found.get(field) for field, column in report["columns"].items()})
        yield [row]


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
    daily_reports = settings.get("daily_reports")
    if daily_reports:
        return SourceResponse(
            name=endpoint,
            items=lambda: _site_metrics_rows(
                api_key,
                normalized_project_id,
                daily_reports,
                should_use_incremental_field,
                db_incremental_field_last_value,
            ),
            primary_keys=settings["primary_keys"],
            # Days are read from the oldest to today.
            sort_mode="asc",
            supports_resume=False,
        )
    project_scoped = settings.get("project_scoped", True)
    history = settings.get("history", False)
    kind = settings.get("kind")
    row_limit = settings["params"].get("limit") or settings.get("body", {}).get("limit")

    def items() -> Iterator[list[dict[str, object]]]:
        served = denied = 0
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
            try:
                for page in resource:
                    if row_limit is not None and len(page) >= int(row_limit):
                        logger.info("ahrefs_sample_limit_reached", team_id=team_id, endpoint=endpoint, limit=row_limit)
                        page = page[: int(row_limit)]
                    page = _unique_rows(page, settings["primary_keys"])
                    if history:
                        page = sorted(page, key=lambda row: str(row.get("date") or ""))
                    yield page
            except ValueError as error:
                # Brand Radar sells each AI platform's index on its own, so a platform outside the plan
                # is skipped. The table fails only when no platform is available.
                if kind != "brand_radar_history" or str(error) != "ahrefs_access_denied":
                    raise
                denied += 1
                logger.info("ahrefs_brand_radar_platform_denied", team_id=team_id, endpoint=endpoint, **row_fields)
                continue
            served += 1
        if denied and not served:
            raise ValueError("ahrefs_access_denied")

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=settings["primary_keys"],
        # Reports that read more than one series return dates in order only within each series.
        sort_mode="asc" if history and kind is None else None,
        supports_resume=False,
    )
