import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.settings import FLOWLU_ENDPOINTS

# Flowlu pages are 1-indexed. List endpoints return ~50 records per page by default; a per-page
# size param isn't reliably documented, so we only advance `page` and stop on the first empty page.
BASE_PAGE = 1
# Cheap list endpoint used to confirm an API key is genuine. Tasks are part of Flowlu's core
# module set, so the endpoint exists on every account regardless of which apps are enabled.
DEFAULT_PROBE_PATH = "/task/tasks/list"


@dataclasses.dataclass
class FlowluResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = BASE_PAGE


def base_url(subdomain: str) -> str:
    """Per-account hostname: every Flowlu portal lives on its own subdomain."""
    return f"https://{subdomain}.flowlu.com/api/v1/module"


def flowlu_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FlowluResumeConfig],
) -> SourceResponse:
    config = FLOWLU_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(subdomain),
            "headers": {"Accept": "application/json"},
            # Flowlu authenticates via the `api_key` query param. The framework redacts its value
            # from logged URLs AND from every raised error message (e.g. a 401 raise_for_status
            # whose URL carries the key), so the secret never reaches a user-visible latest_error.
            "auth": {"type": "api_key", "api_key": api_key, "name": "api_key", "location": "query"},
            # 1-indexed page-number pagination with no authoritative has_more flag: stop on the
            # first empty page.
            "paginator": PageNumberPaginator(base_page=BASE_PAGE, page_param="page", total_path=None),
            # Defense-in-depth: a 30x must not replay the credentialed `api_key` query param off-host.
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # Every list endpoint wraps its payload as `{"response": {"items": [...]}}`.
                    "data_selector": "response.items",
                    # A body that doesn't match means a malformed/changed response — fail loud
                    # rather than silently advancing the cursor past lost rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded, pointing at the next page to fetch; a crash re-fetches from
        # there (merge dedupes on `id`). No save once pagination is exhausted (state is None).
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(FlowluResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
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


def validate_credentials(api_key: str, subdomain: str) -> tuple[bool, str | None]:
    """Probe a single list endpoint to validate the API key.

    Returns ``(is_valid, message)``: 200 valid; 401/403 an auth failure; a connection problem or any
    other HTTP status a non-retryable message. The api_key is redacted from logs and the probe
    swallows exceptions, so the secret never leaks.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        f"{base_url(subdomain)}{DEFAULT_PROBE_PATH}?page={BASE_PAGE}",
        auth=APIKeyAuth(api_key=api_key, name="api_key", location="query"),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Flowlu API key"
    if status is None:
        return False, "Could not connect to Flowlu"
    return False, f"Flowlu returned HTTP {status}"
