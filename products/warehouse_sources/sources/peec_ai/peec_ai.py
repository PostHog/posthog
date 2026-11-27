from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

from requests import Request, Response

from products.warehouse_sources.sources.peec_ai._config import PeecAISourceConfig
from products.warehouse_sources.sources.peec_ai.settings import (
    AUTH_ERRORS,
    BASE_URL,
    DAILY_PAGE_SIZE,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PAGE_SIZE,
)
from products.warehouse_sources.sources.sdk import (
    APIKeyAuth,
    Endpoint,
    EndpointResource,
    OffsetPaginator,
    PaginatorConfig,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    rest_api_resource,
    schema_for_resource,
    set_json_param,
)


@frozen
class PeecAIResumeConfig:
    offset: int
    start_date: str | None = None
    end_date: str | None = None
    window_date: str | None = None


class PeecAIDailyPaginator(OffsetPaginator):
    """Offset pages inside one-day windows, walked from the first day to the last."""

    def __init__(self, first_day: date, last_day: date, total_path: str | None) -> None:
        super().__init__(limit=DAILY_PAGE_SIZE, total_path=total_path, param_location="json")
        self._day = min(first_day, last_day)
        self._last_day = last_day

    def _apply_window(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        set_json_param(request.json, "start_date", self._day.isoformat())
        set_json_param(request.json, "end_date", self._day.isoformat())

    def init_request(self, request: Request) -> None:
        super().init_request(request)
        self._apply_window(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page and self._day < self._last_day:
            self._day += timedelta(days=1)
            self.offset = 0
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        super().update_request(request)
        self._apply_window(request)

    def get_resume_state(self) -> dict[str, Any] | None:
        state = super().get_resume_state()
        return {**state, "window_date": self._day.isoformat()} if state is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        if state.get("window_date"):
            self._day = date.fromisoformat(state["window_date"])

    def __str__(self) -> str:
        return f"PeecAIDailyPaginator(day={self._day}, last_day={self._last_day}, offset={self.offset})"


def _lift_ids(row: dict[str, Any], lifted_ids: dict[str, tuple[str, str]]) -> dict[str, Any]:
    lifted = dict(row)
    for column, (parent, key) in lifted_ids.items():
        nested = row.get(parent)
        lifted[column] = nested.get(key) if isinstance(nested, dict) else None
    return lifted


def validate_credentials(config: PeecAISourceConfig, api_version: str) -> tuple[bool, str | None]:
    try:
        start = date.fromisoformat(config.start_date)
    except ValueError:
        return False, "Enter a valid start date in YYYY-MM-DD format."
    if start.isoformat() != config.start_date:
        return False, "Enter a valid start date in YYYY-MM-DD format."
    if start > datetime.now(UTC).date():
        return False, "The start date must be today or earlier."

    params: dict[str, str | int] = {"limit": 1}
    if config.project_id:
        params["project_id"] = config.project_id

    with make_tracked_session() as session:
        response = session.get(
            f"{BASE_URL}/{api_version}/brands",
            params=params,
            auth=APIKeyAuth(api_key=config.api_key, name="x-api-key", location="header"),
            timeout=30,
        )
        if response.status_code in AUTH_ERRORS:
            return False, AUTH_ERRORS[response.status_code]
        response.raise_for_status()
    return True, None


def peec_ai_source(
    config: PeecAISourceConfig,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PeecAIResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: str | date | datetime | None,
) -> SourceResponse:
    definition = schema_for_resource(ENDPOINTS, endpoint)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    params: dict[str, Any] = dict(definition["params"])
    if config.project_id:
        params["project_id"] = config.project_id

    start_date: str | None = None
    end_date: str | None = None
    if definition.get("date_range", False):
        start_date = config.start_date
        if (
            endpoint in INCREMENTAL_FIELDS
            and should_use_incremental_field
            and db_incremental_field_last_value is not None
        ):
            watermark = db_incremental_field_last_value
            if isinstance(watermark, datetime):
                watermark = watermark.date()
            start_date = max(start_date, str(watermark)[:10])
        end_date = datetime.now(UTC).date().isoformat()
        if resume is not None:
            # Offset pagination must keep the original date range when a retry advances the watermark.
            start_date = resume.start_date or start_date
            end_date = resume.end_date or end_date
        params.update(start_date=start_date, end_date=end_date)

    method = definition.get("method", "GET")
    endpoint_config: Endpoint = {"path": definition["path"], "method": method, "data_selector": "data"}
    if method == "POST":
        endpoint_config["json"] = params
    else:
        endpoint_config["params"] = params

    paginator: PaginatorConfig = "single_page"
    if definition.get("daily", False) and start_date is not None and end_date is not None:
        paginator = PeecAIDailyPaginator(
            date.fromisoformat(start_date), date.fromisoformat(end_date), definition["total_path"]
        )
    elif definition.get("paginated", True):
        paginator = {
            "type": "offset",
            "limit": PAGE_SIZE,
            "total_path": definition["total_path"],
            "param_location": "json" if method == "POST" else "query",
        }

    resource_config: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
    lifted_ids = definition.get("lifted_ids")
    if lifted_ids:
        resource_config["data_map"] = partial(_lift_ids, lifted_ids=lifted_ids)
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{BASE_URL}/{api_version}/",
            "auth": {"type": "api_key", "api_key": config.api_key, "name": "x-api-key", "location": "header"},
            "paginator": paginator,
            "request_timeout": 30,
        },
        "resources": [resource_config],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                PeecAIResumeConfig(
                    offset=int(state["offset"]),
                    start_date=start_date,
                    end_date=end_date,
                    window_date=state.get("window_date"),
                )
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=(
            {"offset": resume.offset, "window_date": resume.window_date} if resume is not None else None
        ),
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=definition.get("primary_keys", ["id"]),
        sort_mode=definition.get("sort_mode"),
        on_complete=resumable_source_manager.clear_state,
    )
