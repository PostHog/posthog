import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from products.warehouse_sources.sources.salesloft.settings import (
    PAGE_SIZE,
    SALESLOFT_ENDPOINTS,
    SALESLOFT_UPDATED_AT_FIELD,
    SalesloftEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    DependentEndpointConfig,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

SALESLOFT_BASE_URL = "https://api.salesloft.com/v2"


@dataclasses.dataclass(frozen=False)
class SalesloftResumeConfig:
    # ``next_url`` is the legacy field: earlier runs saved the full next-page URL. It's kept (with a
    # default) so previously-persisted state still parses; new runs save the page number in
    # ``next_page``. On resume we prefer ``next_page`` and fall back to parsing ``page`` out of a
    # legacy ``next_url``.
    next_url: str = ""
    next_page: Optional[int] = None
    # Fan-out endpoints (cadence_stats) save the framework's per-parent checkpoint here instead.
    fanout_state: Optional[dict[str, Any]] = None


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 string Salesloft expects."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)

    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _build_params(
    config: SalesloftEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}

    if config.incremental:
        # The default sort key is `updated_at` unless the endpoint sets `sort_by`; ascending order
        # lets the pipeline advance its incremental watermark deterministically.
        params["sort_direction"] = "ASC"
        if config.sort_by:
            params["sort_by"] = config.sort_by

        if should_use_incremental_field and db_incremental_field_last_value is not None:
            filter_field = incremental_field or SALESLOFT_UPDATED_AT_FIELD
            params[f"{filter_field}[gte]"] = _format_datetime(db_incremental_field_last_value)

    return params


def _resume_page(resume: SalesloftResumeConfig) -> Optional[int]:
    """Recover the page number to resume from, honoring legacy ``next_url`` state."""
    if resume.next_page is not None:
        return resume.next_page
    if resume.next_url:
        pages = parse_qs(urlparse(resume.next_url).query).get("page")
        if pages:
            try:
                return int(pages[0])
            except (TypeError, ValueError):
                return None
    return None


def validate_credentials(api_key: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SALESLOFT_BASE_URL}/me",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    return ok


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": SALESLOFT_BASE_URL,
        # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
        # logs and raised errors; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
    }


def _page_paginator() -> JSONResponseCursorPaginator:
    # Salesloft returns the next page NUMBER in the body; feed it back as the `page` query param.
    # A null `next_page` stops pagination — matching the API's own end-of-list signal rather than
    # probing one extra empty page.
    return JSONResponseCursorPaginator(cursor_path="metadata.paging.next_page", cursor_param="page")


def _fanout_source(
    api_key: str,
    config: SalesloftEndpointConfig,
    fanout: DependentEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SalesloftResumeConfig],
) -> SourceResponse:
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(SalesloftResumeConfig(fanout_state=state))

    resource = build_dependent_resource(
        endpoint_configs=SALESLOFT_ENDPOINTS,
        child_endpoint=config.name,
        fanout=fanout,
        client_config=_client_config(api_key),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        # The child is a single-object endpoint that takes no page-size param; the parent's rides
        # in `parent_params`.
        page_size_param=None,
        parent_endpoint_extra={"paginator": _page_paginator(), "data_selector": "data"},
        child_endpoint_extra={"paginator": "single_page", "data_selector": "data"},
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_mode=None,
    )


def salesloft_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SalesloftResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SALESLOFT_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(api_key, config, config.fanout, team_id, job_id, resumable_source_manager)

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    "paginator": _page_paginator(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            page = _resume_page(resume)
            if page is not None:
                initial_paginator_state = {"cursor": page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(SalesloftResumeConfig(next_page=int(state["cursor"])))

    # Incremental filtering is expressed as static server-side params above, so the framework's
    # own incremental injection is unused here.
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
