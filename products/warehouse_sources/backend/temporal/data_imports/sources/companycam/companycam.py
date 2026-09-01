import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.companycam.settings import (
    COMPANYCAM_ENDPOINTS,
    PER_PAGE,
)


def base_url(api_version: str) -> str:
    return f"https://api.companycam.com/{api_version}"


@dataclasses.dataclass(frozen=True)
class CompanycamResumeConfig:
    # Next 1-indexed page to fetch, for page/per_page-paginated endpoints.
    page: Optional[int] = None
    # Next forward cursor (from `X-Next-Cursor`), for Photos.
    cursor: Optional[str] = None


def _to_iso8601(value: Any) -> Optional[str]:
    """Format an incremental cursor as the ISO8601 string CompanyCam's `modified_since` expects."""
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    return str(value)


def _to_unix_timestamp(value: Any) -> Optional[str]:
    """Format an incremental cursor as the unix timestamp string CompanyCam's `start_date` expects."""
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return str(int(aware.timestamp()))
    if isinstance(value, date):
        return str(int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp()))
    if isinstance(value, int | float):
        return str(int(value))
    return str(value)


_CONVERTERS = {
    "modified_since": _to_iso8601,
    "start_date": _to_unix_timestamp,
}


class CompanycamCursorPaginator(BasePaginator):
    """Forward cursor pagination for `/photos`, driven by the `X-Next-Cursor` response header.

    CompanyCam's cursor is a bare token carried in a response header, not a full next-page URL or
    a body field, so none of the framework's built-in paginators fit: it isn't a `Link` header
    (`HeaderLinkPaginator`), a JSON body cursor (`JSONResponseCursorPaginator`), or a full URL
    (`BaseNextUrlPaginator`). `page` and `after` are mutually exclusive, so this paginator never
    sends `page`.
    """

    def __init__(self, per_page: int) -> None:
        super().__init__()
        self._per_page = per_page
        self._cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["per_page"] = self._per_page
        if self._cursor is not None:
            request.params["after"] = self._cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        has_next = response.headers.get("X-Has-Next")
        next_cursor = response.headers.get("X-Next-Cursor")
        if has_next is not None:
            self._has_next_page = has_next.lower() == "true" and bool(next_cursor)
        else:
            self._has_next_page = bool(next_cursor)
        self._cursor = next_cursor or None

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["per_page"] = self._per_page
        if self._cursor is not None:
            request.params["after"] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = str(cursor)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"CompanycamCursorPaginator(cursor={self._cursor})"


def _paginator_for(endpoint: str) -> BasePaginator:
    config = COMPANYCAM_ENDPOINTS[endpoint]
    if not config.paginated:
        return SinglePagePaginator()
    if config.cursor_paginated:
        return CompanycamCursorPaginator(per_page=PER_PAGE)
    return PageNumberPaginator(base_page=1, page_param="page")


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
) -> EndpointResource:
    config = COMPANYCAM_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.paginated and not config.cursor_paginated:
        params["per_page"] = PER_PAGE
    if config.incremental_query_param and should_use_incremental_field:
        params[config.incremental_query_param] = {
            "type": "incremental",
            "cursor_path": config.incremental_fields[0]["field"],
            "initial_value": None,
            "convert": _CONVERTERS[config.incremental_query_param],
        }

    return {
        "name": endpoint,
        "table_name": endpoint.lower(),
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": "$",
            "path": config.path,
            "params": params,
        },
        "table_format": "delta",
    }


def companycam_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CompanycamResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    api_version: str,
) -> SourceResponse:
    endpoint_config = COMPANYCAM_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(api_version),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": _paginator_for(endpoint),
            # capture=False: project notes, photo/video metadata, and other free-text fields
            # can carry customer-authored (potentially sensitive) content the name-based HTTP
            # sample scrubbers aren't guaranteed to catch, same as the other PII-heavy sources.
            "capture": False,
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            if endpoint_config.cursor_paginated and resume_config.cursor is not None:
                initial_paginator_state = {"cursor": resume_config.cursor}
            elif resume_config.page is not None:
                initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page/cursor to resume to. Save AFTER a page is
        # yielded so a crash re-yields the last page (merge dedupes) rather than skipping it.
        if not state:
            return
        if endpoint_config.cursor_paginated and state.get("cursor"):
            resumable_source_manager.save_state(CompanycamResumeConfig(cursor=str(state["cursor"])))
        elif state.get("page") is not None:
            resumable_source_manager.save_state(CompanycamResumeConfig(page=int(state["page"])))

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
        primary_keys=endpoint_config.primary_keys,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode=endpoint_config.sort_mode if should_use_incremental_field else "asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, api_version: str) -> bool:
    # capture=False: `/company` returns the customer's company record, which can carry
    # free-text fields the name-based HTTP sample scrubbers aren't guaranteed to catch.
    is_valid, _status_code = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), capture=False),
        f"{base_url(api_version)}/company",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return is_valid
