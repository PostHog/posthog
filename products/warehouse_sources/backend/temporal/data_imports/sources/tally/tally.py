import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
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
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.settings import (
    SUBMISSION_FILTER_COMPLETED,
    TALLY_API_VERSION,
    TALLY_BASE_URL,
    TALLY_ENDPOINTS,
    TALLY_VERSION_HEADER,
    TallyEndpointConfig,
)


@dataclasses.dataclass
class TallyResumeConfig:
    # Page bookmark for a top-level endpoint. None means "start at page one".
    next_page: Optional[int] = None
    # Framework fan-out resume state for the per-form endpoints, opaque to this source and passed
    # straight back to the fan-out helper:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {"page": n} | None}.
    fanout_state: Optional[dict[str, Any]] = None


class TallyPaginator(PageNumberPaginator):
    """Page-number paginator that terminates on Tally's `hasMore` flag.

    Every Tally list endpoint returns `page`, `limit` and a `hasMore` boolean alongside its rows,
    and the docs name `hasMore` as the end-of-pages signal. Stopping on it avoids both the extra
    empty-page round trip the default paginator pays and the off-by-one risk of deriving a page
    count from `total`, which shifts while a sync is running.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        payload = response.json()
        has_more = isinstance(payload, dict) and payload.get("hasMore") is True
        # An empty page that still claims `hasMore` would loop forever; treat it as the end.
        if not has_more or not data:
            self._has_next_page = False
            return

        self.page += 1
        self._has_next_page = True


def _paginator_for(config: TallyEndpointConfig) -> BasePaginator:
    return TallyPaginator() if config.paginated else SinglePagePaginator()


def _client_config(api_key: str, api_version: str, capture: bool = True) -> ClientConfig:
    config: ClientConfig = {
        "base_url": TALLY_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json", TALLY_VERSION_HEADER: api_version},
    }
    if not capture:
        # This endpoint's body carries secrets the name-based sample scrubbers can't spot, so keep
        # its responses out of HTTP sample capture (they're still metered and logged). RESTClient
        # applies the auth and headers above on top of this session.
        config["session"] = make_tracked_session(redact_values=(api_key,), capture=False)
    return config


def _redact_row_fields(fields: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Return a `data_map` that nulls out the named fields on every row, keeping the columns (as
    null) so the table shape stays stable while the secret values never reach the warehouse.
    """

    def _redact(row: dict[str, Any]) -> dict[str, Any]:
        for name in fields:
            if name in row:
                row[name] = None
        return row

    return _redact


def _to_iso8601(value: Any) -> str:
    """Format an incremental watermark the way Tally's `startDate` filter expects (ISO 8601, UTC)."""
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)

    # A watermark ahead of now (clock skew, a restated row) would filter out every submission.
    return min(normalized, datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _submissions_incremental(cursor_path: str) -> IncrementalConfig:
    # `startDate` filters server-side on submission time, and page-number pagination keeps every
    # query param on later pages — so an incremental run never walks past the watermark.
    return {
        "cursor_path": cursor_path,
        "start_param": "startDate",
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _to_iso8601,
    }


def _supports_incremental(config: TallyEndpointConfig, submission_filter: str) -> bool:
    if not config.incremental_fields:
        return False
    # Partial submissions are still being filled in, so we can't rely on `submittedAt` being a
    # settled cursor for them. Including partials therefore drops to full refresh (see get_schemas).
    return submission_filter == SUBMISSION_FILTER_COMPLETED


def _source_response(config: TallyEndpointConfig, items: Any) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=lambda: items,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _top_level_source(
    api_key: str,
    api_version: str,
    config: TallyEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TallyResumeConfig],
) -> SourceResponse:
    params: dict[str, Any] = {}
    if config.page_size_param is not None:
        params[config.page_size_param] = config.page_size

    endpoint: Endpoint = {
        "path": config.path,
        "params": params,
        "paginator": _paginator_for(config),
        "data_selector": config.data_selector,
    }
    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        # No top-level endpoint exposes a server-side updated-since filter, so they full refresh.
        "write_disposition": "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }
    if config.redact_fields:
        resource["data_map"] = _redact_row_fields(config.redact_fields)
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, api_version, capture=config.capture_samples),
        "resource_defaults": {},
        "resources": [resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Saved after a page is yielded, so a crash re-yields the last page rather than skipping it.
        if state and state.get("page"):
            resumable_source_manager.save_state(TallyResumeConfig(next_page=int(state["page"])))

    return _source_response(
        config,
        rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        ),
    )


def _fanout_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    config: TallyEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TallyResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str],
    submission_filter: str,
) -> SourceResponse:
    """Fan out one paginated request per form, tagging every child row with its owning form id."""
    assert config.fanout is not None

    child_params_extra: Optional[dict[str, Any]] = None
    if endpoint == "submissions":
        child_params_extra = {"filter": submission_filter}

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(TallyResumeConfig(fanout_state=state))

    resource = build_dependent_resource(
        endpoint_configs=TALLY_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=config.fanout,
        client_config=_client_config(api_key, api_version),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
        should_use_incremental_field=should_use_incremental_field and _supports_incremental(config, submission_filter),
        incremental_field=incremental_field,
        incremental_config_factory=_submissions_incremental,
        page_size_param=config.page_size_param,
        parent_endpoint_extra={
            "paginator": TallyPaginator(),
            "data_selector": TALLY_ENDPOINTS[config.fanout.parent_name].data_selector,
        },
        child_endpoint_extra={
            "paginator": _paginator_for(config),
            "data_selector": config.data_selector,
            # A form trashed between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync — the form's data is gone either way.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        child_params_extra=child_params_extra,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _source_response(config, resource)


def tally_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TallyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
    submission_filter: str = SUBMISSION_FILTER_COMPLETED,
) -> SourceResponse:
    config = TALLY_ENDPOINTS[endpoint]
    if config.fanout is not None:
        return _fanout_source(
            api_key=api_key,
            api_version=api_version,
            endpoint=endpoint,
            config=config,
            team_id=team_id,
            job_id=job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
            submission_filter=submission_filter,
        )

    return _top_level_source(
        api_key=api_key,
        api_version=api_version,
        config=config,
        team_id=team_id,
        job_id=job_id,
        resumable_source_manager=resumable_source_manager,
    )


def validate_credentials(api_key: str, api_version: str = TALLY_API_VERSION) -> tuple[bool, Optional[int]]:
    """Probe the cheapest authenticated endpoint and report `(is_valid, status_code)`.

    `/forms?limit=1` needs no extra grant beyond a working key, so it validates the key itself
    rather than access to any one table.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{TALLY_BASE_URL}/forms?limit=1",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            TALLY_VERSION_HEADER: api_version,
        },
    )


__all__ = ["TallyPaginator", "TallyResumeConfig", "tally_source", "validate_credentials"]
