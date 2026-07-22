import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser
from requests import Response, Session
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.settings import (
    CALLS_INCREMENTAL_FIELD_NAMES,
    INCREMENTAL_FIELDS,
    LEEXI_BASE_URL,
    LEEXI_ENDPOINTS,
    PAGE_SIZE,
    PRIMARY_KEY,
)


@dataclasses.dataclass
class LeexiResumeConfig:
    # Framework paginator / fan-out resume snapshot for the current endpoint.
    paginator_state: Optional[dict[str, Any]] = None


class LeexiPaginator(PageNumberPaginator):
    """Page-number paginator for Leexi's 1-based `page` param.

    Responses report `pagination.count` (total items, not pages), which
    ``PageNumberPaginator.total_path`` can't consume, so stop as soon as a page comes back
    shorter than the requested size instead of paying an extra empty-page request.
    """

    def __init__(self, page_size: int = PAGE_SIZE) -> None:
        super().__init__(base_page=1, page_param="page")
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self._page_size:
            self._has_next_page = False


def _make_session(api_key_secret: str) -> Session:
    """Session for all Leexi traffic. The key secret is registered for value-based redaction so it
    can't leak into logged URLs or samples, and response capture is disabled: `calls` responses
    carry `simple_transcript`, and call notes and meeting data are arbitrary customer-authored text
    that can hold proprietary content or secrets the name-based sample scrubbers can't recognise —
    so nothing lands in the shared HTTP sample store outside the warehouse table's access controls."""
    return make_tracked_session(redact_values=(api_key_secret,), capture=False)


def _to_leexi_timestamp(value: Any) -> str:
    """Format an incremental cursor value as Leexi's required `YYYY-MM-DDTHH:MM:SS.000Z`."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    else:
        parsed = parser.parse(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _resource(
    name: str,
    path: str,
    params: dict[str, Any],
    write_disposition: Any = "replace",
) -> EndpointResource:
    return {
        "name": name,
        "table_name": name,
        "write_disposition": write_disposition,
        "endpoint": {
            "path": path,
            "params": params,
            "data_selector": "data",
            "paginator": LeexiPaginator(),
        },
        "table_format": "delta",
    }


def _build_resources(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
) -> list[str | EndpointResource]:
    config = LEEXI_ENDPOINTS[endpoint]
    params: dict[str, Any] = {"items": PAGE_SIZE, **config.extra_params}

    if config.fan_out_parent:
        parent = LEEXI_ENDPOINTS[config.fan_out_parent]
        # Parent rows only resolve uuids, so skip its extra params (e.g. transcripts).
        parent_params: dict[str, Any] = {"items": PAGE_SIZE}
        if parent.order:
            parent_params["order"] = parent.order
        params["call_uuid"] = {"type": "resolve", "resource": parent.name, "field": PRIMARY_KEY}
        child = _resource(endpoint, config.path, params)
        child["include_from_parent"] = [PRIMARY_KEY]
        return [_resource(parent.name, parent.path, parent_params), child]

    if should_use_incremental_field and endpoint in INCREMENTAL_FIELDS:
        cursor_field = incremental_field or "updated_at"
        if cursor_field not in CALLS_INCREMENTAL_FIELD_NAMES:
            raise ValueError(f"Leexi does not support incremental syncs on field: {cursor_field}")
        # `date_filter` picks which timestamp `from` filters on; ordering ascending on the
        # same field keeps the pipeline's watermark checkpointing correct (sort_mode="asc").
        params["date_filter"] = cursor_field
        params["order"] = f"{cursor_field} asc"
        params["from"] = {
            "type": "incremental",
            "cursor_path": cursor_field,
            "initial_value": "1970-01-01T00:00:00.000Z",
            "convert": _to_leexi_timestamp,
        }
        return [_resource(endpoint, config.path, params, {"disposition": "merge", "strategy": "upsert"})]

    if config.order:
        params["order"] = config.order
    return [_resource(endpoint, config.path, params)]


def leexi_source(
    api_key_id: str,
    api_key_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LeexiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = LEEXI_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": LEEXI_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Framework Basic auth redacts the key secret from logs and captured samples.
            "auth": {"type": "http_basic", "username": api_key_id, "password": api_key_secret},
            "session": _make_session(api_key_secret),
        },
        "resources": _build_resources(endpoint, should_use_incremental_field, incremental_field),
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.paginator_state is not None:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework calls this AFTER a page is yielded, so a crash re-yields the last
        # page (merge dedupes on uuid) rather than skipping it. Persist only while there's
        # more to fetch; the Redis TTL handles cleanup on completion.
        if state:
            resumable_source_manager.save_state(LeexiResumeConfig(paginator_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    target = next(resource for resource in resources if getattr(resource, "name", None) == endpoint)

    if config.fan_out_parent:
        # Child rows carry the parent id as `_calls_uuid`; expose it as a flat `call_uuid`.
        target = target.add_map(rename_parent_fields(config.fan_out_parent, {PRIMARY_KEY: "call_uuid"}))
        primary_keys = ["call_uuid", PRIMARY_KEY]
    else:
        primary_keys = [PRIMARY_KEY]

    return SourceResponse(
        name=endpoint,
        items=lambda: target,
        primary_keys=primary_keys,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        sort_mode="asc",
        # Call rows can carry full transcripts, so keep buffered chunks smaller than the
        # pipeline defaults to bound worker memory.
        chunk_size=1000 if endpoint == "calls" else None,
        chunk_size_bytes=100 * 1024 * 1024 if endpoint == "calls" else None,
        column_hints=target.column_hints,
    )


def probe_endpoint(api_key_id: str, api_key_secret: str, path: str) -> Optional[int]:
    """Probe a Leexi list endpoint with the cheapest possible request; returns the HTTP
    status, or None when the request itself failed."""
    _ok, status = validate_via_probe(
        lambda: _make_session(api_key_secret),
        f"{LEEXI_BASE_URL}{path}?items=1",
        auth=HTTPBasicAuth(api_key_id, api_key_secret),
    )
    return status
