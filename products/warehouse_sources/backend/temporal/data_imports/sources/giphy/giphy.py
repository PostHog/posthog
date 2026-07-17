import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.settings import (
    GIPHY_ENDPOINTS,
    GiphyEndpointConfig,
)

GIPHY_BASE_URL = "https://api.giphy.com/v1"
# Beta keys cap search at limit=50; 50 is within every documented endpoint cap
# (trending/search) and works for both beta and production keys.
PAGE_SIZE = 50


@dataclasses.dataclass
class GiphyResumeConfig:
    # GIPHY paginates with a numeric offset. The endpoint and (for search) query
    # are rebuilt deterministically from job inputs on resume, so only the offset
    # needs persisting.
    offset: int = 0


def _explode_search_terms(body: dict[str, Any]) -> list[dict[str, Any]]:
    # `/trending/searches` returns `{"data": ["cats", ...]}` — a flat list of strings. The framework's
    # per-item map only fires on dict rows, so the whole body is selected (data_selector=None) and
    # exploded here into one `search_term` row per string (matching the old primary-key column).
    terms = body.get("data") or []
    return [{"search_term": term} for term in terms]


def _build_endpoint_config(config: GiphyEndpointConfig, search_query: str | None) -> dict[str, Any]:
    if config.is_term_list:
        # No pagination and no offset/limit params; explode the string list into search_term rows.
        return {
            "path": config.path,
            "paginator": SinglePagePaginator(),
        }

    endpoint: dict[str, Any] = {
        "path": config.path,
        # GIPHY caps the offset it serves (trending 499, search 4999); requesting beyond it 400s, so
        # stop at the cap rather than fail the sync. `total_count`/short/empty page also terminate.
        "paginator": OffsetPaginator(
            limit=PAGE_SIZE,
            offset_param="offset",
            limit_param="limit",
            total_path="pagination.total_count",
            maximum_offset=config.max_offset,
        ),
        "data_selector": config.data_key,
    }
    if config.requires_query:
        endpoint["params"] = {"q": search_query}
    return endpoint


def giphy_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GiphyResumeConfig],
    search_query: Optional[str] = None,
) -> SourceResponse:
    config = GIPHY_ENDPOINTS[endpoint]

    if config.requires_query and not (search_query or "").strip():
        raise ValueError(
            f"GIPHY endpoint '{endpoint}' requires a search query. Set the search query on the source and reconnect."
        )

    resource_config: dict[str, Any] = {
        "name": endpoint,
        "endpoint": _build_endpoint_config(config, search_query),
    }
    if config.is_term_list:
        resource_config["data_map"] = _explode_search_terms

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": GIPHY_BASE_URL,
            "headers": {"Accept": "application/json"},
            # The key rides in the query string (GIPHY has no header auth). Supplying it via the
            # framework auth registers it for value-based redaction so it never leaks into tracked
            # request URLs, captured samples, or raised error messages.
            "auth": {"type": "api_key", "api_key": api_key, "name": "api_key", "location": "query"},
        },
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(GiphyResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every GIPHY endpoint is full refresh — the API has no incremental filter
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is genuine with one cheap trending request."""
    config = GIPHY_ENDPOINTS["gifs_trending"]
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(headers={"Accept": "application/json"}, redact_values=(api_key,)),
        f"{GIPHY_BASE_URL}{config.path}?api_key={api_key}&limit={PAGE_SIZE}&offset=0",
    )
    return ok
