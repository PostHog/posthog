import dataclasses
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.settings import QUALAROO_ENDPOINTS

QUALAROO_BASE_URL = "https://api.qualaroo.com/api/v1"
# The Reporting API caps a page at 500 records; the largest page minimises round trips.
PAGE_SIZE = 500
# Cheap endpoint used to confirm the credentials are genuine. The API key/secret pair is
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/nudges.json"


@dataclasses.dataclass
class QualarooResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    offset: int = 0


def qualaroo_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[QualarooResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = QUALAROO_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": QUALAROO_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Qualaroo uses HTTP Basic auth with the API key as username and the secret as password.
            "auth": {"type": "http_basic", "username": api_key, "password": api_secret},
            # Qualaroo has no top-level `total`; termination is a short/empty page (OffsetPaginator default).
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
        },
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # Qualaroo list endpoints return a bare JSON array; a 200 whose body isn't a list
                    # is treated as a transient shape glitch and retried (not failed loud).
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `id`) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(QualarooResumeConfig(offset=int(state["offset"])))

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


def validate_credentials(api_key: str, api_secret: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the account-wide key/secret pair.

    Maps the probe result to the same messages the hand-rolled implementation returned: 200 valid,
    401/403 bad credentials, any other status surfaced verbatim, and an unreachable probe reported
    as an unvalidated (rather than failed) source.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key, api_secret)),
        f"{QUALAROO_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1&offset=0",
        auth=HTTPBasicAuth(api_key, api_secret),
        headers={"Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Qualaroo API key or secret"
    if status is None:
        return False, "Could not validate Qualaroo credentials"
    return False, f"Qualaroo returned HTTP {status}"
