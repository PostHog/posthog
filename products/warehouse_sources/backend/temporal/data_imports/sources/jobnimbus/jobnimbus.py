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
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.settings import JOBNIMBUS_ENDPOINTS

JOBNIMBUS_BASE_URL = "https://app.jobnimbus.com/api1"
# The Elasticsearch-backed list endpoints accept a `size` of up to 100; the largest page minimises
# round trips.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/contacts"


@dataclasses.dataclass
class JobNimbusResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `jnid`.
    offset: int = 0


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs and
    # raised errors; only the non-secret accept header is set here.
    return {"Accept": "application/json"}


def jobnimbus_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[JobNimbusResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = JOBNIMBUS_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": JOBNIMBUS_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "bearer", "token": api_key},
            # JobNimbus list endpoints paginate with size/from and report the grand total as `count`;
            # pagination stops once the offset reaches that total or a short/empty page arrives.
            "paginator": OffsetPaginator(
                limit=PAGE_SIZE,
                offset_param="from",
                limit_param="size",
                total_path="count",
            ),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": "results",
                    # A 200 body without a `results` list means the response shape changed — fail
                    # loud instead of silently syncing 0 rows (or wrapping a stray object as a row).
                    "data_selector_required": True,
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
        # the last page (merge dedupes on `jnid`) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(JobNimbusResumeConfig(offset=int(state["offset"])))

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
    # The API key is account-wide, so a single probe validates access to every list endpoint.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{JOBNIMBUS_BASE_URL}{DEFAULT_PROBE_PATH}?size=1&from=0",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid JobNimbus API key"
    if status is None:
        return False, "Could not validate JobNimbus API key"
    return False, f"JobNimbus returned HTTP {status}"
