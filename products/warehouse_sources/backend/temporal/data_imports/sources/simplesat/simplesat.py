import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.settings import SIMPLESAT_ENDPOINTS

SIMPLESAT_BASE_URL = "https://api.simplesat.io/api/v1"
SIMPLESAT_HOST = "api.simplesat.io"
# The list endpoints return up to 100 records per page; the largest page minimises round trips.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/surveys"


@dataclasses.dataclass
class SimplesatResumeConfig:
    # Absolute URL of the next page to fetch, taken verbatim from the response body's `next`
    # field. Cursor pagination is deterministic, so a crashed full-refresh sync resumes from the
    # page after the last one yielded; merge dedupes on `id`.
    next_url: str | None = None


def _headers() -> dict[str, str]:
    # Only the non-secret Accept header lives here; the API key rides the framework `api_key` auth so
    # its value is redacted from logs and raised error messages.
    return {"Accept": "application/json"}


def simplesat_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SimplesatResumeConfig],
) -> SourceResponse:
    config = SIMPLESAT_ENDPOINTS[endpoint]

    is_post = config.method == "POST"

    endpoint_config: Endpoint = {
        "path": config.path,
        "method": "POST" if is_post else "GET",
        "params": {"page_size": PAGE_SIZE},
        # Simplesat wraps the page under a key named after the resource
        # (e.g. {"surveys": [...], "next": ...}).
        "data_selector": config.list_key,
        # A 200 whose body isn't the expected wrapped list (non-dict, missing key, or a non-list
        # value) is treated as transient and retried, matching the old transport.
        "data_selector_malformed_retryable": True,
    }
    # The search-style collection endpoints are POST; an empty body means "no date filter", i.e.
    # every record — the full refresh we want. GET endpoints send no body at all.
    if is_post:
        endpoint_config["json"] = {}

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SIMPLESAT_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Simplesat-Token", "location": "header"},
            # The `next` cursor comes from the response body and is followed with the same session
            # that carries the API key. Pin every request (including next-page and resume URLs) to the
            # Simplesat host and reject redirects so a malformed/malicious response can't redirect the
            # customer's key to another origin.
            "allowed_hosts": [SIMPLESAT_HOST],
            "allow_redirects": False,
            "paginator": JSONResponsePaginator(next_url_path="next"),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next page (already-yielded pages are persisted) — merge dedupes on the primary key.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(SimplesatResumeConfig(next_url=state["next_url"]))

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


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the account-wide API key.

    Returns ``(is_valid, message)``: a reachable 200 validates every list endpoint, 401/403 is an
    auth failure, any other status (or an unreachable probe) is reported as not-validated.
    """
    ok, status = validate_via_probe(
        # The X-Simplesat-Token header rides on the probe; pin redirects off on the session so one
        # can't replay it to a redirect target off the Simplesat host during validation.
        lambda: make_tracked_session(headers=_headers(), redact_values=(api_key,), allow_redirects=False),
        f"{SIMPLESAT_BASE_URL}{DEFAULT_PROBE_PATH}?page_size=1",
        headers={"X-Simplesat-Token": api_key},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Simplesat API key"
    if status is not None:
        return False, f"Simplesat returned HTTP {status}"
    return False, "Could not validate Simplesat API key"
