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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ApiKeyAuthConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.settings import SMARTREACH_ENDPOINTS

SMARTREACH_BASE_URL = "https://api.smartreach.io/api/v1"
# Cheap endpoint used to confirm an API key is genuine. The user key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_ENDPOINT = "campaigns"


@dataclasses.dataclass
class SmartreachResumeConfig:
    # Full URL of the next page, taken verbatim from `links.next`. None means "start at the
    # endpoint's first page". The next URL already carries every pagination param, so the original
    # query params must NOT be re-sent alongside it (the paginator drops them).
    next_url: str | None = None


def _headers() -> dict[str, str]:
    # Auth (the X-API-KEY header) is supplied via the framework auth config so its value is redacted
    # from logs and raised errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _api_key_auth(api_key: str) -> ApiKeyAuthConfig:
    return {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"}


def smartreach_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartreachResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SMARTREACH_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SMARTREACH_BASE_URL,
            "headers": _headers(),
            "auth": _api_key_auth(api_key),
            # SmartReach echoes the next page as a full URL in `links.next`, so it can't be trusted
            # blindly: a tampered response could point it at an arbitrary host and leak the API key.
            "paginator": JSONResponsePaginator(next_url_path="links.next"),
            # Pin every request — including paginator next-page and seeded resume URLs — to
            # SmartReach's own https origin. `allowed_hosts=[]` means "same host as base_url only",
            # and the base scheme/port are pinned too, so an off-origin or scheme-downgraded
            # (http://) `links.next` is rejected before the key goes out. `allow_redirects=False`
            # stops a redirect from bouncing the key off-origin.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # SmartReach nests the list under `data.<data_key>` (e.g. data.prospects). A
                    # missing key yields an empty page (matching the previous behavior) rather than
                    # failing loud, so data_selector_required is left off.
                    "data_selector": f"data.{config.data_key}",
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
        # the last page (merge dedupes) rather than skipping it. No state is saved for the final page.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(SmartreachResumeConfig(next_url=state["next_url"]))

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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(api_key: str, endpoint: str = DEFAULT_PROBE_ENDPOINT) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the user key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    config = SMARTREACH_ENDPOINTS[endpoint]
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        f"{SMARTREACH_BASE_URL}{config.path}",
        headers={"X-API-KEY": api_key, **_headers()},
    )
    if status is None:
        return 0, "Could not connect to SmartReach"
    if status in (401, 403):
        return status, None
    if ok:
        return status, None
    return status, f"SmartReach returned HTTP {status}"
