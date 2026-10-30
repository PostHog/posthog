import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests import Response

from posthog.dataclasses import frozen

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
    OffsetPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.settings import (
    PAGE_SIZE,
    PANDADOC_ENDPOINTS,
    PandaDocEndpointConfig,
)

# PandaDoc versions its API per endpoint via a URL segment (/public/v1, /public/v2), not
# globally: /public/v2 is a small, growing set of new endpoints (API logs, document audit
# trail, product catalog search), NOT a mirror of v1. Each resource this source reads is
# served under exactly one of the two, so every endpoint path carries its own version segment
# and both pins resolve to the same wire.
API_VERSION_V1 = "v1"
API_VERSION_V2 = "v2"

PANDADOC_BASE_URL = "https://api.pandadoc.com/public"


@frozen
class PandaDocResumeConfig:
    # PandaDoc paginates with a 1-based page number; the static query params
    # (count, incremental filters, sort) are deterministically rebuilt from the
    # endpoint config and job inputs on resume.
    page: Optional[int] = None
    # Per-document child endpoints checkpoint the `build_dependent_resource` state instead
    # (which documents finished, where the current one stopped).
    fanout_state: Optional[dict[str, Any]] = None


class PandaDocPagePaginator(PageNumberPaginator):
    """1-based page paginator that stops as soon as a page returns fewer than PAGE_SIZE rows.

    PandaDoc list responses carry no total, so the hand-rolled source terminated on the first
    short page rather than paying one extra empty-page request. The built-in only stops on an
    empty page, so extend it to also stop on a partial page and keep termination identical.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if data is not None and len(data) < PAGE_SIZE:
            self._has_next_page = False


class PandaDocHasMorePaginator(PageNumberPaginator):
    """1-based page paginator for v2 list endpoints that flag the last page in the body."""

    def __init__(self, has_more_path: str) -> None:
        super().__init__(base_page=1, page_param="page")
        self.has_more_path = has_more_path

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        body = response.json()
        if isinstance(body, dict) and body.get(self.has_more_path) is False:
            self._has_next_page = False


def _paginator_for(config: PandaDocEndpointConfig) -> BasePaginator:
    if config.pagination == "none":
        return SinglePagePaginator()
    if config.pagination == "offset":
        return OffsetPaginator(
            limit=config.page_size, limit_param=config.page_size_param, offset_param="offset", total_path="count"
        )
    if config.has_more_path:
        return PandaDocHasMorePaginator(config.has_more_path)
    return PandaDocPagePaginator()


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": PANDADOC_BASE_URL,
        # Auth is supplied via the framework so the key is redacted from logs and errors;
        # PandaDoc uses an "API-Key <key>" Authorization scheme rather than a bare Bearer.
        "auth": {"type": "api_key", "api_key": f"API-Key {api_key}", "name": "Authorization"},
    }


def _format_date_filter(value: Any) -> str:
    """Format an incremental cursor for PandaDoc's date filters (ISO 8601 UTC, e.g. 2024-01-02T03:04:05.000000Z)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return str(value)


def _build_query_params(
    config: PandaDocEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Static per-run query params — everything except the paginator-managed page number.

    Covers the page size plus, for endpoints that expose server-side date filters (only
    documents), the incremental filter param and the sort order. These are constant across a
    run, so they can be injected as endpoint params while the paginator owns the page number.
    """
    params: dict[str, Any] = {}

    if config.pagination == "page":
        params[config.page_size_param] = config.page_size

    if not config.incremental_params:
        return params

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        cursor_field = incremental_field or config.incremental_fields[0]["field"]
        filter_param = config.incremental_params.get(cursor_field)
        if filter_param is not None:
            params[filter_param] = _format_date_filter(db_incremental_field_last_value)
            # Ascending order on the cursor field so the incremental watermark
            # advances monotonically as pages are consumed.
            params["order_by"] = cursor_field
            return params

    # Full refresh: sort on the stable creation date so rows modified mid-sync
    # don't move across page boundaries.
    params["order_by"] = "date_created"
    return params


def _document_child_resource(
    api_key: str,
    config: PandaDocEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PandaDocResumeConfig],
) -> Resource:
    assert config.fanout is not None
    parent = PANDADOC_ENDPOINTS[config.fanout.parent_name]
    # The parent listing is a full walk sorted on the stable creation date, like a full refresh of
    # the documents table, so documents modified mid-sync don't move across page boundaries.
    fanout = dataclasses.replace(
        config.fanout,
        parent_params=_build_query_params(
            parent, should_use_incremental_field=False, db_incremental_field_last_value=None, incremental_field=None
        ),
    )

    initial_fanout_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_fanout_state = resume.fanout_state

    def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(PandaDocResumeConfig(fanout_state=state))

    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs={config.name: config, parent.name: parent},
            child_endpoint=config.name,
            fanout=fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Parent and child name their page-size params differently, so each sets its own.
            page_size_param=None,
            parent_endpoint_extra={"paginator": _paginator_for(parent), "data_selector": parent.data_key},
            child_endpoint_extra={"paginator": _paginator_for(config), "data_selector": config.data_key},
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=initial_fanout_state,
        ),
    )


def pandadoc_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PandaDocResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PANDADOC_ENDPOINTS[endpoint]
    partition_kwargs: dict[str, Any] = {
        "partition_count": 1,
        "partition_size": 1,
        "partition_mode": "datetime" if config.partition_key else None,
        "partition_format": "month" if config.partition_key else None,
        "partition_keys": [config.partition_key] if config.partition_key else None,
    }

    if config.fanout is not None:
        child = _document_child_resource(api_key, config, team_id, job_id, resumable_source_manager)
        return SourceResponse(
            name=endpoint,
            items=lambda: child,
            primary_keys=config.primary_keys,
            column_hints=child.column_hints,
            **partition_kwargs,
        )

    params = _build_query_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # List endpoints wrap their rows in "results" (or "items" on v2); a missing key is
                    # treated as an empty page (matching the hand-rolled source), so this is not required.
                    "data_selector": config.data_key,
                    "paginator": _paginator_for(config),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(PandaDocResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        column_hints=resource.column_hints,
        **partition_kwargs,
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid with a cheap one-document listing probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{PANDADOC_BASE_URL}/v1/documents?count=1&page=1",
        headers={"Authorization": f"API-Key {api_key}"},
    )
    return ok
