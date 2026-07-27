import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.settings import TMDB_ENDPOINTS

TMDB_BASE_URL = "https://api.themoviedb.org/3"

# TMDB list endpoints (popular/top_rated/...) and /discover are hard-capped at 500 pages server-side,
# so there's no point requesting beyond that — it 422s.
MAX_PAGES = 500


@dataclasses.dataclass
class TMDbResumeConfig:
    # Next page number to fetch. Page-number pagination means a single integer is enough to resume.
    next_page: int


def tmdb_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TMDbResumeConfig],
) -> SourceResponse:
    config = TMDB_ENDPOINTS[endpoint]

    if config.paginated:
        # TMDB list/trending endpoints paginate with `page` / `total_pages`; stop after the last page
        # and never request past the server-side 500-page ceiling.
        paginator: PageNumberPaginator | SinglePagePaginator = PageNumberPaginator(
            base_page=1,
            page_param="page",
            total_path="total_pages",
            maximum_page=MAX_PAGES,
        )
        # Only paginated requests carry `language`; the reference endpoints omit it, matching the
        # previous hand-rolled URL builder exactly.
        params: dict[str, Any] = {"language": "en-US"}
    else:
        paginator = SinglePagePaginator()
        params = {}

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TMDB_BASE_URL,
            "headers": {"Accept": "application/json"},
            # The api_key rides in the query string; framework auth redacts it from every raised error
            # message (raise_for_status, HTTP {status} for {url}) so it can't leak into job errors.
            "auth": {"type": "api_key", "api_key": api_key, "name": "api_key", "location": "query"},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # None for the bare-list configuration endpoints (languages/countries); "results"
                    # or "genres" otherwise. Not marked required: a malformed body degrades to empty
                    # rows rather than failing loud, matching the previous behavior.
                    "data_selector": config.data_key,
                    "paginator": paginator,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(TMDbResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every TMDB endpoint is full refresh — no server-side updated-after filter
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Full refresh (replace) on small, bounded ranking/reference datasets whose date fields can be
        # empty, so datetime partitioning isn't worthwhile here.
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # /configuration is a cheap call that 200s for any valid key and 401s for an invalid one. Only a
    # 401 means the key is wrong — a transient failure (5xx, network error, timeout) must not be
    # reported as an invalid key, or a user with a perfectly valid key during a brief TMDB outage
    # would be told to regenerate it.
    url = f"{TMDB_BASE_URL}/configuration?{urlencode({'api_key': api_key})}"
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Accept": "application/json"},
    )
    if ok:
        return True, None
    if status is None:
        return False, "Could not reach TMDB to validate your API key. Check your connection and try again."
    if status == 401:
        return False, "Invalid TMDB API key"
    return (
        False,
        f"TMDB returned an unexpected response (status {status}) while validating your API key. Please try again.",
    )
