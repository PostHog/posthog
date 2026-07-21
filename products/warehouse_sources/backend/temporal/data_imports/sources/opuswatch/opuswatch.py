import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.settings import (
    BASE_URL,
    DEFAULT_START_DATE,
    OPUSWATCH_ENDPOINTS,
    PAGE_SIZE,
)


@dataclasses.dataclass
class OPUSWatchResumeConfig:
    offset: int


def parse_start_date(start_date: Optional[str]) -> date:
    value = (start_date or "").strip() or DEFAULT_START_DATE
    return datetime.strptime(value, "%Y%m%d").date()


def _window_start(last_value: Any) -> Optional[date]:
    if isinstance(last_value, datetime):
        return last_value.date()
    if isinstance(last_value, date):
        return last_value
    if isinstance(last_value, str):
        try:
            return parser.parse(last_value).date()
        except (ValueError, OverflowError):
            return None
    return None


def build_date_window_params(
    start_date: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    today: Optional[date] = None,
) -> dict[str, str]:
    """Server-side date-window filter params for the transactional endpoints.

    The API filters by whole days: `date` (YYYYMMDD) + `days_from_date` select a
    window starting at `date`, while `days_till_date` selects a window of the last
    N days; `filter_date_by` picks which timestamp (CREATED or UPDATED) the window
    applies to. There is no cursor token, so incremental syncs re-read from the
    watermark's day (a `days_till_date` window over UPDATED — the same request
    shape the vendor's own connector uses for recent updates) and rely on the
    merge on `id` to dedupe the overlap.
    """
    if today is None:
        today = datetime.now(UTC).date()

    params = {"return_breaks": "true", "return_leaves": "true", "return_archived": "true"}

    watermark = _window_start(db_incremental_field_last_value) if should_use_incremental_field else None
    if watermark is not None:
        params["filter_date_by"] = "UPDATED"
        params["days_till_date"] = str(max((today - watermark).days + 1, 1))
    else:
        window_start = parse_start_date(start_date)
        params["filter_date_by"] = "CREATED"
        params["date"] = window_start.strftime("%Y%m%d")
        params["days_from_date"] = str(max((today - window_start).days + 1, 1))

    return params


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    start_date: Optional[str],
    db_incremental_field_last_value: Any,
) -> EndpointResource:
    endpoint_config = OPUSWATCH_ENDPOINTS[name]

    endpoint: Endpoint = {"path": endpoint_config.path}

    if endpoint_config.paginated:
        # Transactional responses wrap rows in {"data": [...]}; no total count is
        # returned, so pagination stops on a short or empty page.
        endpoint["data_selector"] = "data"
        endpoint["paginator"] = OffsetPaginator(limit=PAGE_SIZE, total_path=None)
    else:
        endpoint["paginator"] = SinglePagePaginator()

    if endpoint_config.supports_date_window:
        endpoint["params"] = dict(
            build_date_window_params(start_date, should_use_incremental_field, db_incremental_field_last_value)
        )

    return {
        "name": endpoint_config.name,
        "table_name": endpoint_config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def opuswatch_source(
    api_key: str,
    start_date: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OPUSWatchResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> Resource:
    endpoint_config = OPUSWATCH_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            # The API key rides in a bare `key` header, not an Authorization header.
            "auth": {"type": "api_key", "name": "key", "api_key": api_key, "location": "header"},
            # Pin every request to the fixed API host and reject cross-host redirects —
            # `requests` only strips `Authorization` on redirects, so the custom `key`
            # header would otherwise be replayed off-host. `allowed_hosts=[]` means
            # "same host as base_url only".
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [
            get_resource(endpoint, should_use_incremental_field, start_date, db_incremental_field_last_value)
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume_hook = None

    if endpoint_config.paginated:
        if resumable_source_manager.can_resume():
            resume_config = resumable_source_manager.load_state()
            if resume_config is not None:
                initial_paginator_state = {"offset": resume_config.offset}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state and state.get("offset") is not None:
                resumable_source_manager.save_state(OPUSWatchResumeConfig(offset=int(state["offset"])))

        resume_hook = save_checkpoint

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str) -> bool:
    # `allow_redirects=False` keeps the `key` header from being replayed to a redirect target.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    response = session.get(f"{BASE_URL}master/workers", headers={"key": api_key}, timeout=30)
    return response.status_code == 200
