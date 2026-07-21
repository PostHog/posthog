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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.settings import PLANHAT_ENDPOINTS

PLANHAT_BASE_URL = "https://api.planhat.com"
# Planhat list endpoints default to a `limit` of 100; the largest common page minimises round trips.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an API token is genuine. The token is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/companies"


@dataclasses.dataclass
class PlanhatResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `_id`.
    offset: int = 0


def planhat_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PlanhatResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PLANHAT_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PLANHAT_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            # Planhat has no top-level `total`; termination is a short/empty page (OffsetPaginator default).
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # Planhat list endpoints return a bare JSON array of records; a 200 body that
                    # isn't a list is treated as a transient shape glitch and retried.
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
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(PlanhatResumeConfig(offset=int(state["offset"])))

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


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the account-wide API token.

    The token grants read access to every list endpoint, so one cheap probe (a single row from
    ``/companies``) confirms access for all schemas.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{PLANHAT_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1&offset=0",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Planhat API token"
    if status is None:
        return False, "Could not validate Planhat API token"
    return False, f"Planhat returned HTTP {status}"
