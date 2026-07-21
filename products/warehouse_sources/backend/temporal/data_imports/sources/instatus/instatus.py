import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.settings import INSTATUS_ENDPOINTS

# Single global host — Instatus has no per-account subdomains (unlike Statuspage).
INSTATUS_BASE_URL = "https://api.instatus.com"
PAGES_ENDPOINT_PATH = "/v2/pages"

# per_page defaults to 50 and is capped at 100; we always request the maximum to minimise round-trips.
PAGE_SIZE = 100

# The framework binds the resolved parent id into the child path via `str.format`, so the parent
# status page id rides in the URL path (`/v1/{page_id}/...`) rather than the query string.
_PARENT_PAGE_ID_KEY = "_pages_id"


@dataclasses.dataclass
class InstatusResumeConfig:
    # Next page to fetch for a non-fan-out resource (1-based page-number pagination). Kept with a
    # default so previously saved fan-out state (which never set it) still parses.
    page: int = 1
    # Pre-framework fan-out bookkeeping: the parent status page whose children were being read.
    # Retained (with a default) so old saved state still parses; translated into fanout_state on load.
    parent_page_id: Optional[str] = None
    # Framework fan-out resume state for page-scoped endpoints:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: Optional[dict] = None


def _headers() -> dict[str, str]:
    # Instatus requires the JSON content type on every request, including GETs. The credential
    # travels via framework bearer auth (not a hand-built header) so its value is registered for
    # redaction wherever it surfaces in logs and raised errors.
    return {"Content-Type": "application/json"}


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": INSTATUS_BASE_URL,
        "headers": _headers(),
        "auth": {"type": "bearer", "token": api_key},
        # A credentialed request stays pinned to the validated Instatus host — a 3xx can't replay
        # it (and its Authorization header) to another origin.
        "allow_redirects": False,
    }


def _paginator() -> PageNumberPaginator:
    # 1-based `page` with `per_page` (capped at 100). Termination is on an empty array only: we
    # deliberately do NOT stop on a short page, because if the API ignores the size param and
    # defaults below 100, a short-but-non-empty page is still not the last one.
    return PageNumberPaginator(base_page=1, page_param="page", stop_after_empty_page=True)


def _stamp_page_id(row: dict[str, Any]) -> dict[str, Any]:
    # include_from_parent lands the parent status page id as `_pages_id`; rename it to the plain
    # `page_id` column child rows carry (part of the composite primary key — see settings.py) so a
    # sync that aggregates rows from every page keeps the key unique table-wide.
    value = row.pop(_PARENT_PAGE_ID_KEY, None)
    if value is not None:
        row["page_id"] = value
    return row


def _standard_resource(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[InstatusResumeConfig],
) -> Resource:
    config = INSTATUS_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": PAGE_SIZE},
                    "paginator": _paginator(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.page and resume.page > 1:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the checkpoint is saved AFTER a page is yielded so
        # a crash re-fetches the in-flight page (merge dedupes re-pulled rows) rather than skipping it.
        if state and state.get("page") is not None:
            manager.save_state(InstatusResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _child_path(endpoint: str, page_id: str) -> str:
    return INSTATUS_ENDPOINTS[endpoint].path.format(page_id=page_id)


def _translate_legacy_fanout_state(resume: InstatusResumeConfig, endpoint: str) -> Optional[dict[str, Any]]:
    """Translate a pre-framework fan-out bookmark into the framework's resume shape.

    The old bookkeeping only recorded the parent page currently being read plus its next page; it
    relied on parent-listing order to skip already-finished parents. The framework keys resume by
    resolved child path, so we resume the in-progress parent precisely and let already-finished
    parents be re-fetched (merge dedupes on the composite primary key) rather than skipping them.
    """
    if resume.parent_page_id is None:
        return None
    return {
        "completed": [],
        "current": _child_path(endpoint, resume.parent_page_id),
        "child_state": {"page": resume.page},
    }


def _fanout_resource(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[InstatusResumeConfig],
) -> Resource:
    """Fan out over every status page, listing the page-scoped resource and stamping the parent id.

    Page-scoped resources live under `/v1/{page_id}/...`, so they can only be pulled per status
    page. Full refresh — re-pulled rows on resume are deduped by the (page_id, id) primary key.
    """
    pages_config = INSTATUS_ENDPOINTS["pages"]
    child_config = INSTATUS_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": "pages",
                "endpoint": {
                    "path": pages_config.path,
                    "params": {"per_page": PAGE_SIZE},
                    "paginator": _paginator(),
                },
            },
            {
                "name": endpoint,
                "endpoint": {
                    "path": child_config.path,
                    "params": {
                        "page_id": {"type": "resolve", "resource": "pages", "field": "id"},
                        "per_page": PAGE_SIZE,
                    },
                    "paginator": _paginator(),
                },
                "include_from_parent": ["id"],
                "data_map": _stamp_page_id,
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None:
            if resume.fanout_state is not None:
                initial_paginator_state = resume.fanout_state
            else:
                initial_paginator_state = _translate_legacy_fanout_state(resume, endpoint)

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            manager.save_state(InstatusResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(r for r in resources if r.name == endpoint)


def instatus_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[InstatusResumeConfig],
) -> SourceResponse:
    config = INSTATUS_ENDPOINTS[endpoint]

    if config.page_scoped:
        resource = _fanout_resource(api_key, endpoint, team_id, job_id, resumable_source_manager)
    else:
        resource = _standard_resource(api_key, endpoint, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_key,
        # Full refresh only — Instatus exposes no server-side timestamp filter — but rows still
        # arrive in a stable page order, so asc is correct.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Confirm the API key is genuine with one cheap probe against the status-page listing."""
    url = f"{INSTATUS_BASE_URL}{PAGES_ENDPOINT_PATH}?per_page=1&page=1"
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        url,
        headers={"Authorization": f"Bearer {api_key}", **_headers()},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Instatus API key. Please check your API key and try again."
    if status == 403:
        return False, "Your Instatus API key does not have permission to list status pages."
    if status is None:
        return False, "Could not connect to Instatus. Please try again."
    return False, f"Instatus returned HTTP {status}"
