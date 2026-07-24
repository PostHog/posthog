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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.settings import SECODA_ENDPOINTS

# US cloud host. EU (eapi.secoda.co), APAC (aapi.secoda.co) and self-hosted domains are not yet
# selectable — see the region caveat in the source docs.
SECODA_BASE_URL = "https://api.secoda.co"
# Cheap list endpoint used to confirm an API key is genuine. The key inherits its creator's
# workspace permissions, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/api/v1/user"

# Secoda uses DRF-style cursor pagination: the follow link is a full URL nested under ``links.next``,
# though a couple of endpoints expose it top-level under ``next``. Accept either; ``links.next`` wins.
NEXT_URL_PATH = "(links.next) | next"


@dataclasses.dataclass
class SecodaResumeConfig:
    # Full URL of the next page to fetch, taken verbatim from the API's ``links.next``. Secoda uses
    # DRF-style cursor pagination, so a crashed full-refresh sync resumes from the page after the
    # last one yielded; merge dedupes the re-pulled page on ``id``.
    next_url: str | None = None


def secoda_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SecodaResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SECODA_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SECODA_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and raised errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": JSONResponsePaginator(next_url_path=NEXT_URL_PATH),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": "results",
                    # A 200 whose body isn't the expected ``{"results": [...]}`` shape (bare list,
                    # dict without ``results``, or ``results`` not a list) is treated as transient
                    # and reissued — mirrors the old client raising a retryable error on it.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next cursor remains; save AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes on ``id``) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(SecodaResumeConfig(next_url=state["next_url"]))

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
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a single list endpoint to validate the workspace API key.

    The key inherits its creator's workspace permissions, so one probe validates access to every
    list endpoint. Returns ``(is_valid, message)`` with a distinct message for an auth failure.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SECODA_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Secoda API key"
    if status is not None:
        return False, f"Secoda returned HTTP {status}"
    return False, "Could not validate Secoda API key"
