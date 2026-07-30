import dataclasses
from collections.abc import Callable, Iterable
from typing import Any, Optional, cast

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceResponse
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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.settings import (
    TEACHABLE_BASE_URL,
    TEACHABLE_ENDPOINTS,
    TeachableEndpointConfig,
)


@dataclasses.dataclass
class TeachableResumeConfig:
    """Paginator checkpoint: `page` for page-numbered endpoints, `search_after` for /users."""

    page: Optional[int] = None
    search_after: Optional[int] = None


def _format_teachable_datetime(value: Any) -> str:
    """Format the incremental watermark for Teachable's `start` filter.

    Truncates to whole seconds, which rounds the lower bound *down* — combined with
    `start` being exclusive, a sync re-fetches at most a few boundary rows (the merge
    dedupes them) rather than skipping any.
    """
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _teachable_incremental_window(cursor_path: str) -> IncrementalConfig:
    # `start` is a server-side time filter on /transactions, exclusive of the given instant.
    return {
        "cursor_path": cursor_path,
        "start_param": "start",
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _format_teachable_datetime,
    }


def _rest_api_client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": TEACHABLE_BASE_URL,
        "auth": {"type": "api_key", "name": "apiKey", "api_key": api_key, "location": "header"},
        "headers": {"Accept": "application/json"},
        # Pin every request (and the apiKey header) to the Teachable host and refuse to follow a
        # 3xx, so a server-side redirect can never replay the credential header off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _page_paginator() -> PageNumberPaginator:
    # Teachable pages are 1-based; `meta.number_of_pages` reports the total page count, so
    # pagination stops after the last page without paying an extra empty-page request.
    return PageNumberPaginator(base_page=1, page_param="page", total_path="meta.number_of_pages")


class TeachableUsersPaginator(BasePaginator):
    """Cursor paginator for `/v1/users` using `search_after`.

    Plain `page` pagination stops working past the 10,000th user, so we walk the id-sorted
    list with `search_after` (the last user id of the previous page) from the start.
    Termination: `meta.has_more_results` when the API returns it, otherwise an empty page.
    A short page alone is only terminal when it's shorter than the server-reported
    `meta.per_page` — the server may clamp our requested `per`.
    """

    def __init__(self, per: int) -> None:
        super().__init__()
        self.per = per
        self._search_after: Optional[int] = None

    def _apply_params(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["per"] = self.per
        if self._search_after is not None:
            request.params["search_after"] = self._search_after

    def init_request(self, request: Request) -> None:
        self._apply_params(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        meta: dict[str, Any] = {}
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("meta"), dict):
                meta = body["meta"]
        except Exception:
            meta = {}

        # Prefer the server-provided next cursor; fall back to the last row's id.
        next_cursor: Optional[int] = None
        meta_search_after = meta.get("search_after")
        if isinstance(meta_search_after, list) and meta_search_after and isinstance(meta_search_after[0], int):
            next_cursor = meta_search_after[0]
        else:
            last_row = data[-1]
            if isinstance(last_row, dict) and isinstance(last_row.get("id"), int):
                next_cursor = last_row["id"]

        if next_cursor is None:
            self._has_next_page = False
            return
        self._search_after = next_cursor

        has_more = meta.get("has_more_results")
        if has_more is False:
            self._has_next_page = False
            return
        if has_more is None:
            per_page = meta.get("per_page")
            effective_per = per_page if isinstance(per_page, int) else self.per
            if len(data) < effective_per:
                self._has_next_page = False
                return

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply_params(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._search_after is not None:
            return {"search_after": self._search_after}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        search_after = state.get("search_after")
        if search_after is not None:
            self._search_after = int(search_after)
            self._has_next_page = True


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
        f"{TEACHABLE_BASE_URL}/v1/courses",
        headers={"apiKey": api_key, "Accept": "application/json"},
        params={"per": 1},
        timeout=10,
    )
    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Teachable API key"
    if response.status_code == 403:
        return (
            False,
            "Teachable rejected the API key. Check that the key is active and that your school "
            "is on the Growth plan or higher (required for API access).",
        )
    return False, f"Teachable API returned an unexpected status code: {response.status_code}"


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field_name: str | None = None,
) -> EndpointResource:
    config = TEACHABLE_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {"per": config.page_size} if endpoint != "users" else {},
        "data_selector": config.data_selector,
        # The wrapper key is documented as required, so a response without it means the API
        # shape changed — fail loud rather than silently syncing 0 rows.
        "data_selector_required": True,
        "paginator": TeachableUsersPaginator(per=config.page_size) if endpoint == "users" else _page_paginator(),
    }

    use_incremental = should_use_incremental_field and bool(config.incremental_fields)
    if use_incremental:
        endpoint_config["incremental"] = _teachable_incremental_window(
            incremental_field_name or config.default_incremental_field or "created_at"
        )

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(
    endpoint_config: TeachableEndpointConfig,
    items_fn: Callable[[], Iterable[Any]],
    sort_mode: SortMode = "asc",
) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key,
        sort_mode=sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def teachable_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: Optional[ResumableSourceManager[TeachableResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = TEACHABLE_ENDPOINTS[endpoint]

    if endpoint_config.fanout:
        # Dependent resources don't currently support resume in the rest_source framework;
        # the manager is intentionally not threaded into this path.
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=TEACHABLE_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_rest_api_client_config(api_key),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                incremental_config_factory=_teachable_incremental_window,
                page_size_param="per",
                parent_endpoint_extra={
                    "paginator": _page_paginator(),
                    "data_selector": TEACHABLE_ENDPOINTS[endpoint_config.fanout.parent_name].data_selector,
                },
                child_endpoint_extra={
                    "paginator": _page_paginator(),
                    "data_selector": endpoint_config.data_selector,
                },
                # Enrollments are sorted by enrolled_at; pin the direction so page boundaries
                # stay stable while rows are inserted mid-sync.
                child_params_extra={"sort_direction": "asc"},
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _rest_api_client_config(api_key),
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None
    if resumable_source_manager is not None:
        if resumable_source_manager.can_resume():
            resume_config = resumable_source_manager.load_state()
            if resume_config is not None:
                if resume_config.search_after is not None:
                    initial_paginator_state = {"search_after": resume_config.search_after}
                elif resume_config.page is not None:
                    initial_paginator_state = {"page": resume_config.page}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only while there is another page to resume to; the Redis TTL cleans up
            # on completion.
            if resumable_source_manager is None or not state:
                return
            if state.get("page") is not None or state.get("search_after") is not None:
                resumable_source_manager.save_state(
                    TeachableResumeConfig(page=state.get("page"), search_after=state.get("search_after"))
                )

        resume_hook = save_checkpoint

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )

    # Teachable doesn't document /transactions ordering, so incremental syncs run with desc
    # semantics: the watermark is committed only once the sync completes, never mid-run.
    sort_mode: SortMode = "desc" if (should_use_incremental_field and endpoint_config.incremental_fields) else "asc"
    return _make_source_response(endpoint_config, lambda: resource, sort_mode=sort_mode)
