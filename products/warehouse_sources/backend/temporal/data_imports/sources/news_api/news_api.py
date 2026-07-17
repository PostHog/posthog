import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.settings import NEWS_API_ENDPOINTS

NEWS_API_BASE_URL = "https://newsapi.org"

# NewsAPI caps pageSize at 100 and total reachable results per query window at 100. A page cap is a
# defensive backstop in case a paid plan lets pagination run further than expected.
PAGE_SIZE = 100
MAX_PAGES = 100


@dataclasses.dataclass
class NewsApiResumeConfig:
    # Next page number to request. Pagination is 1-indexed; resume picks up mid-endpoint after a
    # heartbeat timeout without restarting from page 1.
    next_page: int = 1


class NewsApiPaginator(BasePaginator):
    """Page/pageSize walk that stops the moment the reachable window is drained.

    NewsAPI reports the reachable total in the body's ``totalResults``. The walk ends on a short
    page, on paging past that total, on an empty page, or at ``MAX_PAGES`` — matching the original
    hand-rolled loop so no extra request is issued past the reachable set. ``maximumResultsReached``
    (HTTP 426) is handled separately via a ``response_actions`` ignore hook, so it never reaches the
    paginator.
    """

    def __init__(self, page_size: int = PAGE_SIZE, maximum_page: int = MAX_PAGES, base_page: int = 1) -> None:
        super().__init__()
        self.page_size = page_size
        self.maximum_page = maximum_page
        self.page = base_page
        self.page_param = "page"

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = data or []
        if not rows:
            self._has_next_page = False
            return

        try:
            total_results = response.json().get("totalResults") or 0
        except Exception:
            total_results = 0

        # Stop when we've drained the reachable set: a short final page, or (when the API reports a
        # positive total) we've paged past it. Guard on `total_results` so a missing/zero total on a
        # full page doesn't stop us early — the short-page check and MAX_PAGES cap still bound the walk.
        if len(rows) < self.page_size or (total_results and self.page * self.page_size >= total_results):
            self._has_next_page = False
            return

        self.page += 1
        if self.page > self.maximum_page:
            self._has_next_page = False
            return

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


def _get_headers(api_key: str) -> dict[str, str]:
    # Header auth avoids leaking the key into request URLs / logs (the apiKey query param is the
    # documented alternative). `Accept` keeps NewsAPI on its JSON contract.
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def _format_from_value(value: Any) -> str | None:
    """Format an incremental cursor value for NewsAPI's `from` param (ISO 8601)."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def validate_credentials(api_key: str) -> bool:
    # /v2/top-headlines/sources is the cheapest probe: it needs only a valid key (no query params),
    # so it confirms the token without spending a search request.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{NEWS_API_BASE_URL}/v2/top-headlines/sources",
        headers=_get_headers(api_key),
    )
    return ok


def news_api_source(
    api_key: str,
    endpoint: str,
    query: str,
    language: str | None,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NewsApiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NEWS_API_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    response_actions: Optional[list[dict[str, Any]]] = None
    paginator: BasePaginator

    if config.name == "sources":
        # /v2/top-headlines/sources takes no query/pagination — only optional facet filters.
        if language:
            params["language"] = language
        paginator = SinglePagePaginator()
    else:
        if query:
            params["q"] = query
        params["pageSize"] = PAGE_SIZE
        if config.name == "everything":
            # publishedAt is the only sort NewsAPI exposes for /v2/everything; it returns newest-first
            # (descending), which is why the SourceResponse below declares sort_mode="desc".
            params["sortBy"] = "publishedAt"
            # `language` is only a valid filter on /v2/everything (top-headlines uses country/category).
            if language:
                params["language"] = language
            if config.supports_incremental and should_use_incremental_field:
                from_value = _format_from_value(db_incremental_field_last_value)
                if from_value:
                    params["from"] = from_value
        paginator = NewsApiPaginator(page_size=PAGE_SIZE, maximum_page=MAX_PAGES, base_page=1)
        # NewsAPI returns 426 `maximumResultsReached` once pagination hits the reachable cap. That's a
        # normal terminal condition for the query window, not a failure — stop cleanly, keeping the
        # rows already fetched. Any other 426 still falls through to raise_for_status (surfaced as a
        # permanent error via get_non_retryable_errors).
        response_actions = [{"status_code": 426, "content": "maximumResultsReached", "action": "ignore"}]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(NewsApiResumeConfig(next_page=int(state["page"])))

    endpoint_config: dict[str, Any] = {
        "path": config.path,
        "params": params,
        "data_selector": config.data_key,
        "paginator": paginator,
    }
    if response_actions is not None:
        endpoint_config["response_actions"] = response_actions

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": NEWS_API_BASE_URL,
            # Auth (api_key) is supplied via the framework config so its value is redacted from logs
            # and raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Api-Key", "location": "header"},
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint if config.paginated else None,
        initial_paginator_state=initial_paginator_state,
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
        # /v2/everything returns newest-first, so the incremental endpoint must declare desc or the
        # pipeline would corrupt the watermark. The full-refresh endpoints don't track a watermark,
        # so their arrival order is immaterial — leave them on the default.
        sort_mode="desc" if config.supports_incremental else "asc",
        column_hints=resource.column_hints,
    )
