import dataclasses
from collections.abc import Callable, Iterable
from typing import Any, Optional, cast

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
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
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.settings import (
    HIGHTOUCH_BASE_URL,
    HIGHTOUCH_ENDPOINTS,
    HightouchEndpointConfig,
)


@dataclasses.dataclass
class HightouchResumeConfig:
    # Opaque framework checkpoint (offset state for top-level endpoints, per-parent fan-out
    # state for sync_runs), round-tripped into `initial_paginator_state` on resume.
    paginator_state: dict[str, Any]


class HightouchPaginator(OffsetPaginator):
    """Limit/offset paginator that also honors Hightouch's `hasMore` response flag.

    Every Hightouch list response is `{"data": [...], "hasMore": bool}`, so a full page
    with `hasMore: false` stops immediately instead of paying one extra empty-page request.
    The inherited empty/short-page checks still terminate if `hasMore` is ever absent.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(limit=limit, total_path=None)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        try:
            res = response.json()
        except Exception:
            return
        if isinstance(res, dict) and res.get("hasMore") is False:
            self._has_next_page = False


def _format_hightouch_datetime(value: Any) -> str:
    """Format the incremental watermark for Hightouch's ISO `after` filter.

    Truncates to whole seconds, which rounds the lower bound *down* — so a sync re-fetches
    at most a few boundary rows (the merge dedupes them) rather than skipping any run whose
    startedAt equals the watermark.
    """
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hightouch_incremental_window(cursor_path: str) -> IncrementalConfig:
    # `after` is a server-side filter on startedAt that persists across offset pages, so
    # pagination is bounded by the filtered set and terminates at the watermark.
    return {
        "cursor_path": cursor_path,
        "start_param": "after",
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _format_hightouch_datetime,
    }


def _drop_fields(fields: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        for field in fields:
            row.pop(field, None)
        return row

    return _mapper


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": HIGHTOUCH_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        # `capture=False`: sync/source/destination responses carry `configuration` objects with
        # third-party credentials the name-based sample scrubbers can't recognise, so keep the
        # raw bodies out of HTTP sample capture (still metered and logged).
        "session": make_tracked_session(capture=False, redact_values=(api_key,)),
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # `capture=False` for the same reason as in `_client_config`: the probe response can carry
    # credential-bearing sync `configuration` objects.
    res = make_tracked_session(capture=False, redact_values=(api_key,)).get(
        f"{HIGHTOUCH_BASE_URL}/syncs",
        headers=_auth_headers(api_key),
        params={"limit": 1},
        timeout=10,
    )
    if res.status_code == 200:
        return True, None
    if res.status_code == 401:
        return False, "Invalid Hightouch API key"
    if res.status_code == 403:
        return False, "Hightouch API key is missing the required permissions"
    return False, f"Hightouch API returned an unexpected status: {res.status_code}"


def get_resource(endpoint: str) -> EndpointResource:
    config = HIGHTOUCH_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        # `orderBy=id` pins a strictly monotonic, unique sort so offset pages don't skip or
        # duplicate rows if the API's implicit ordering shifts as rows are inserted mid-walk.
        "params": {"orderBy": "id"},
        "data_selector": "data",
        "paginator": HightouchPaginator(limit=config.page_size),
    }

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }
    if config.strip_fields:
        resource["data_map"] = _drop_fields(config.strip_fields)
    return resource


def _make_source_response(endpoint_config: HightouchEndpointConfig, items_fn: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def hightouch_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HightouchResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = HIGHTOUCH_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's somewhere to resume to; the Redis TTL handles cleanup.
        if state:
            resumable_source_manager.save_state(HightouchResumeConfig(paginator_state=dict(state)))

    if endpoint_config.fanout:
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=HIGHTOUCH_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_client_config(api_key),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                incremental_config_factory=_hightouch_incremental_window,
                page_size_param="limit",
                parent_endpoint_extra={
                    "paginator": HightouchPaginator(
                        limit=HIGHTOUCH_ENDPOINTS[endpoint_config.fanout.parent_name].page_size
                    ),
                    "data_selector": "data",
                },
                child_endpoint_extra={
                    "paginator": HightouchPaginator(limit=endpoint_config.page_size),
                    "data_selector": "data",
                },
                child_params_extra={"orderBy": "id"},
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_paginator_state,
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint=endpoint)],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)
