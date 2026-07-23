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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.settings import (
    PEXELS_ENDPOINTS,
    PexelsEndpointConfig,
)

PEXELS_BASE_URL = "https://api.pexels.com"
# Pexels caps `per_page` at 80; request the max to minimise round trips.
PER_PAGE = 80
REQUEST_TIMEOUT = 30


@dataclasses.dataclass
class PexelsResumeConfig:
    # 1-based page number to (re-)start from. Pexels uses page-number pagination.
    page: int = 1


def _get_headers(api_key: str) -> dict[str, str]:
    # Pexels sends the API key as the raw Authorization header value — no "Bearer " prefix.
    return {"Authorization": api_key, "Accept": "application/json"}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    return f"{base_url}?{urlencode(params)}" if params else base_url


def validate_credentials(api_key: str) -> bool:
    # The curated endpoint needs no query params and a single row is the cheapest authenticated probe.
    # Pexels sends the key as a raw Authorization value the sampler's name-based scrubber can't
    # recognise, so register it for redaction to keep it out of captured HTTP samples.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        _build_url(f"{PEXELS_BASE_URL}/v1/curated", {"per_page": 1}),
        headers=_get_headers(api_key),
        timeout=REQUEST_TIMEOUT,
    )
    return ok


def pexels_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PexelsResumeConfig],
    search_query: str | None = None,
) -> SourceResponse:
    config: PexelsEndpointConfig = PEXELS_ENDPOINTS[endpoint]
    # `get_schemas` only offers the search tables when a query is set, but fail loudly here rather
    # than let a missing query become a literal `?query=None` if that guard ever regresses.
    if config.requires_query and not search_query:
        raise ValueError(f"Endpoint '{endpoint}' requires a search query but none was provided.")

    params: dict[str, Any] = {"per_page": PER_PAGE}
    if config.requires_query:
        params["query"] = search_query

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PEXELS_BASE_URL,
            # Only the non-secret Accept header goes here; the raw-key Authorization is supplied via
            # the framework auth config (api_key in the Authorization header, no "Bearer " prefix) so
            # its value is redacted from logs and captured samples automatically.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
            # Pexels exposes no total-pages field; termination is the first empty page (the paginator
            # requests one page past the last populated one, whose rows dedupe on `id` if re-run).
            "paginator": PageNumberPaginator(base_page=1, page=1, total_path=None),
        },
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # "photos", "videos" or "collections" depending on the endpoint; a 200 body
                    # missing the key yields an empty page and stops (Pexels never omits it mid-run).
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash resumes at
        # the next unfetched page (any re-fetched rows dedupe on the `id` primary key when merged).
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(PexelsResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Pexels endpoint is full refresh — no incremental last value
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Full refresh only — Pexels resources carry no stable datetime to partition on.
        partition_count=1,
        partition_size=1,
    )
