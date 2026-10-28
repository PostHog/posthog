from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from requests import Response, Session
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen
from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptwatch import (
    PromptWatchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.settings import (
    AUTH_ERROR,
    BASE_URL,
    CAPPED_ENDPOINTS,
    CITATION_WINDOW_DAYS,
    CREATED_AT_SORTED_ENDPOINTS,
    DATA_SELECTORS,
    EXTRA_PARAMS,
    MAX_PAGES,
    PAGE_SIZE,
    PAGINATED_ENDPOINTS,
    PATHS,
    PROJECT_ERROR,
    QUOTA_ERROR,
    VISITOR_WINDOW_DAYS,
)

logger = structlog.get_logger(__name__)


@frozen
class PromptWatchResumeConfig:
    page: int
    from_date: str | None
    until: str


def make_session(api_key: str, *, enforce_row_limit: bool) -> Session:
    session = make_tracked_session(retry=Retry(total=0), redact_values=(api_key,))
    warned_page_cap = False

    def check_response(response: Response, **kwargs: object) -> None:
        nonlocal warned_page_cap
        if response.status_code != 429 and not response.ok:
            return
        try:
            body = response.json()
        except ValueError:
            return
        if not isinstance(body, dict):
            return
        if response.status_code == 429 and "hourly API request limit" in str(body.get("message", "")):
            raise NonReportableError("PROMPTWATCH_HOURLY_QUOTA")
        if response.ok and ("pagination" in body or PAGINATED_ENDPOINTS.intersection(body)):
            pagination = body.get("pagination", body)
            total_pages = pagination.get("totalPages") if isinstance(pagination, dict) else None
            if not isinstance(total_pages, int) or isinstance(total_pages, bool) or total_pages < 0:
                raise ValueError("Promptwatch returned invalid pagination metadata.")
            if total_pages > MAX_PAGES:
                if enforce_row_limit:
                    raise NonReportableError("PROMPTWATCH_ROW_LIMIT")
                if not warned_page_cap:
                    logger.warning("promptwatch.page_cap_reached", maximum_page=MAX_PAGES, total_pages=total_pages)
                    warned_page_cap = True

    session.hooks["response"].append(check_response)
    return session


def validate_credentials(config: PromptWatchSourceConfig, api_version: str) -> tuple[bool, str | None]:
    try:
        date.fromisoformat(config.start_date)
    except ValueError:
        return False, "Enter the response start date in YYYY-MM-DD format."
    with make_session(config.api_key, enforce_row_limit=True) as session:
        try:
            response = session.get(
                f"{BASE_URL}/{api_version}/auth/validate",
                auth=APIKeyAuth(config.api_key, name="X-API-Key"),
                headers={"X-Project-Id": config.project_id} if config.project_id else {},
                timeout=30,
                allow_redirects=False,
            )
        except NonReportableError:
            return False, QUOTA_ERROR
        if response.status_code == 401:
            return False, AUTH_ERROR
        if response.status_code == 403:
            return False, PROJECT_ERROR
        response.raise_for_status()
        body = response.json()
        if not body.get("valid"):
            return False, AUTH_ERROR
        if not body.get("project"):
            return False, "Enter a project ID when you use an organization API key."
        return True, None


def _rest_config(
    config: PromptWatchSourceConfig, session: Session, api_version: str, resource: EndpointResource
) -> RESTAPIConfig:
    return {
        "client": {
            "base_url": f"{BASE_URL}/{api_version}",
            "auth": {"type": "api_key", "name": "X-API-Key", "api_key": config.api_key},
            "headers": {"X-Project-Id": config.project_id} if config.project_id else {},
            "session": session,
            "allow_redirects": False,
            "request_timeout": 30,
        },
        "resources": [resource],
    }


def _citation_row(row: dict[str, Any]) -> dict[str, Any]:
    return {"urlId": row["url"]["id"], **row}


def _visitor_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    dates = body.get("dates") or []
    return [
        {"date": day, "referrer": series["name"], "visitors": visitors}
        for series in body.get("series") or []
        for day, visitors in zip(dates, series["data"], strict=True)
    ]


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _visitor_trend_rows(
    config: PromptWatchSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[PromptWatchResumeConfig],
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=VISITOR_WINDOW_DAYS - 1)
    if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
        # The last synced day can be partial, so read it again.
        start = _as_date(inputs.db_incremental_field_last_value) - timedelta(days=1)
    with make_session(config.api_key, enforce_row_limit=False) as session:
        while start <= end:
            window_end = min(start + timedelta(days=VISITOR_WINDOW_DAYS - 1), end)
            resource: EndpointResource = {
                "name": "visitor_trends",
                "endpoint": {
                    "path": PATHS["visitor_trends"],
                    "params": {"startDate": start.isoformat(), "endDate": window_end.isoformat(), "timezone": "UTC"},
                    "data_selector": "$",
                    "paginator": "single_page",
                },
                "data_map": _visitor_rows,
            }
            yield from rest_api_resource(
                _rest_config(config, session, api_version, resource),
                inputs.team_id,
                inputs.job_id,
                db_incremental_field_last_value=None,
            )
            manager.safe_point()
            start = window_end + timedelta(days=1)


def promptwatch_source(
    config: PromptWatchSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[PromptWatchResumeConfig],
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = inputs.schema_name
    if endpoint == "visitor_trends":
        yield from _visitor_trend_rows(config, inputs, manager, api_version)
        return
    paginated = endpoint in PAGINATED_ENDPOINTS
    resume = manager.load_state() if paginated and manager.can_resume() else None
    if resume and resume.page == 0:
        return
    from_date: str | None = None
    until = datetime.now(UTC).isoformat()
    if endpoint == "responses":
        start = datetime.combine(date.fromisoformat(config.start_date), datetime.min.time(), tzinfo=UTC)
        if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
            watermark = inputs.db_incremental_field_last_value
            last = watermark if isinstance(watermark, datetime) else datetime.fromisoformat(str(watermark))
            last = last.replace(tzinfo=UTC) if last.tzinfo is None else last
            start = max(start, last - timedelta(seconds=1))
        from_date = start.isoformat()
    elif endpoint == "grouped_citations":
        today = datetime.now(UTC).date()
        from_date = (today - timedelta(days=CITATION_WINDOW_DAYS - 1)).isoformat()
        until = today.isoformat()
    if resume:
        from_date, until = resume.from_date, resume.until
    params: dict[str, Any] = dict(EXTRA_PARAMS.get(endpoint, {}))
    if paginated:
        params.update(size=PAGE_SIZE)
    if endpoint in CREATED_AT_SORTED_ENDPOINTS:
        params.update(sortBy="createdAt", sortOrder="asc")
    if from_date is not None:
        if endpoint == "grouped_citations":
            params.update(startDate=from_date, endDate=until)
        else:
            params.update({"from": from_date, "until": until})

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        manager.save_state(
            PromptWatchResumeConfig(page=int(state["page"]) if state else 0, from_date=from_date, until=until)
        )

    enforce_row_limit = endpoint not in CAPPED_ENDPOINTS and not (
        endpoint == "responses" and inputs.should_use_incremental_field
    )
    with make_session(config.api_key, enforce_row_limit=enforce_row_limit) as session:
        endpoint_config: Endpoint = {
            "path": PATHS.get(endpoint, endpoint),
            "params": params,
            "data_selector": DATA_SELECTORS.get(endpoint, endpoint),
            "data_selector_required": True,
            "paginator": PageNumberPaginator(
                base_page=1,
                total_path="pagination.totalPages" if endpoint == "grouped_citations" else "totalPages",
                maximum_page=MAX_PAGES,
            )
            if paginated
            else "single_page",
        }
        resource: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
        if endpoint == "grouped_citations":
            resource["data_map"] = _citation_row
        yield from rest_api_resource(
            _rest_config(config, session, api_version, resource),
            inputs.team_id,
            inputs.job_id,
            db_incremental_field_last_value=None,
            resume_hook=save_checkpoint if paginated else None,
            initial_paginator_state={"page": resume.page} if resume else None,
        )
