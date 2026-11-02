from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests import Request, Response
from requests.auth import HTTPBasicAuth

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.settings import (
    CHARTMOGUL_ENDPOINTS,
    METRICS_START_DATE,
    ChartMogulEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CHARTMOGUL_BASE_URL = "https://api.chartmogul.com"
# (connect, read) seconds. Without it a stalled ChartMogul response holds an import worker
# until Temporal cancels the activity, rather than raising a retryable request timeout.
REQUEST_TIMEOUT_SECONDS: tuple[float, float] = (10.0, 60.0)


@frozen
class ChartMogulResumeConfig:
    # Top-level endpoints resume from the opaque `cursor` of the last fully-yielded page. The
    # static query params (page size, incremental start-date) are deterministically rebuilt
    # from the config and the job inputs on resume.
    cursor: Optional[str] = None
    # Fan-out endpoints resume by parent: the customer paths already fully synced, the customer
    # in progress, and that customer's paginator state. See
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: Optional[list[str]] = None
    current: Optional[str] = None
    child_state: Optional[dict[str, Any]] = None


class ChartMogulPaginator(BasePaginator):
    """Cursor pagination gated on ChartMogul's `has_more` flag.

    ChartMogul returns both `cursor` and `has_more` on every page; a next page
    exists only when `has_more` is true AND a cursor is present, so the
    built-in cursor paginator (cursor presence alone) can't be used.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["cursor"] = self._cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None

        if not isinstance(body, dict):
            self._has_next_page = False
            return

        cursor = body.get("cursor")
        if body.get("has_more", False) and cursor:
            self._cursor = cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["cursor"] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = str(cursor)
            self._has_next_page = True


def _format_start_date(value: Any) -> str:
    """Format an incremental cursor value for ChartMogul's `start-date` filter (ISO 8601)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def validate_credentials(api_key: str) -> bool:
    # ChartMogul uses HTTP Basic auth with the API key as the username and an
    # empty password.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CHARTMOGUL_BASE_URL}/v1/data_sources",
        auth=HTTPBasicAuth(api_key, ""),
        timeout=60.0,
    )
    return ok


def _client_config(api_key: str, paginated: bool) -> ClientConfig:
    return {
        "base_url": CHARTMOGUL_BASE_URL,
        "auth": {"type": "http_basic", "username": api_key, "password": ""},
        # Some endpoints (data_sources, metrics) return the full list without pagination.
        "paginator": ChartMogulPaginator() if paginated else SinglePagePaginator(),
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }


def _request_params(
    config: ChartMogulEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    params: dict[str, Any] = {**config.extra_params}
    if config.paginated:
        params["per_page"] = config.page_size
    if config.requires_date_range:
        params["start-date"] = METRICS_START_DATE
        params["end-date"] = datetime.now(UTC).strftime("%Y-%m-%d")
    if config.incremental_param and should_use_incremental_field and db_incremental_field_last_value:
        params[config.incremental_param] = _format_start_date(db_incremental_field_last_value)
    return params


def _top_level_resource(
    config: ChartMogulEndpointConfig,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ChartMogulResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Iterable[Any]:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, config.paginated),
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _request_params(config, should_use_incremental_field, db_incremental_field_last_value),
                    # ChartMogul wraps results per resource (customers/activities
                    # use "entries", plans use "plans", etc.); a missing key is
                    # treated as an empty page, matching the historical behavior.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.cursor:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the checkpoint is saved AFTER
        # the page is yielded so a crash re-yields the last page (merge dedupes
        # on primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(ChartMogulResumeConfig(cursor=str(state["cursor"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_resource(
    config: ChartMogulEndpointConfig,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ChartMogulResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Iterable[Any]:
    assert config.fanout is not None
    parent_config = CHARTMOGUL_ENDPOINTS[config.fanout.parent_name]

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                ChartMogulResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    return cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=CHARTMOGUL_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(api_key, config.paginated),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            # No fan-out endpoint has a server-side time filter today, so this never selects
            # merge. Passing it anyway makes a future incremental child fail loudly for its
            # missing incremental_config_factory instead of quietly full-refreshing.
            should_use_incremental_field=should_use_incremental_field,
            parent_endpoint_extra={"data_selector": parent_config.data_key},
            child_endpoint_extra={"data_selector": config.data_key},
            page_size_param="per_page",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )


def chartmogul_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ChartMogulResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CHARTMOGUL_ENDPOINTS[endpoint]

    resource: Iterable[Any]
    if config.fanout is not None:
        resource = _fanout_resource(
            config,
            api_key,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        resource = _top_level_resource(
            config,
            api_key,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # ChartMogul activities are returned in chronological (ascending) order
        # within the start-date window, so the incremental watermark advances
        # correctly. Non-incremental endpoints default to asc as well.
        sort_mode="asc",
    )
