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
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.settings import TEAMTAILOR_ENDPOINTS

TEAMTAILOR_BASE_URL = "https://api.teamtailor.com/v1"
# JSON:API caps `page[size]` at 30; the largest page minimises round trips.
PAGE_SIZE = 30
# Every request must pin an API version; this dated value is a documented, stable release.
API_VERSION = "20240404"
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/users"


@dataclasses.dataclass
class TeamtailorResumeConfig:
    # Absolute URL of the next page to fetch, taken verbatim from the JSON:API `links.next`.
    # `None` starts from the first page. Cursor pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_url: Optional[str] = None


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token token={api_key}",
        "X-Api-Version": API_VERSION,
        "Accept": "application/vnd.api+json",
    }


def _version_headers() -> dict[str, str]:
    # Auth (the `Token token=` header) is supplied via the framework auth config so its value is
    # redacted from logs and errors; only the non-secret version/accept headers are set here.
    return {"X-Api-Version": API_VERSION, "Accept": "application/vnd.api+json"}


def teamtailor_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TeamtailorResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TEAMTAILOR_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TEAMTAILOR_BASE_URL,
            "headers": _version_headers(),
            # Teamtailor's scheme is `Authorization: Token token=<key>`; carry the whole credential
            # string via api_key auth so the key is scrubbed from error messages and logged URLs.
            "auth": {
                "type": "api_key",
                "api_key": f"Token token={api_key}",
                "name": "Authorization",
                "location": "header",
            },
            # JSON:API returns the next-page URL in `links.next`; an absent/null link ends the sync.
            # The link is self-contained, so the paginator drops the first-page params when following it.
            "paginator": JSONResponsePaginator(next_url_path="links.next"),
        },
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"page[size]": PAGE_SIZE},
                    "data_selector": "data",
                    # JSON:API always returns an object with a top-level `data` list; a 200 whose
                    # body is any other shape is malformed, so retry rather than silently ending
                    # the sync (the old client raised a retryable error for a non-object payload).
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `id`) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(TeamtailorResumeConfig(next_url=state["next_url"]))

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
        column_hints=resource.column_hints,
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{TEAMTAILOR_BASE_URL}{path}", params={"page[size]": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Teamtailor: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Teamtailor returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Teamtailor API key"
    return False, message or "Could not validate Teamtailor API key"
