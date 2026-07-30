import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.settings import STIGG_ENDPOINTS

STIGG_BASE_URL = "https://api.stigg.io/api/v1"
# List endpoints accept a `limit` of up to 100 (default 20); the largest page minimises round trips.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an API key is genuine. Server API keys are environment-wide,
# so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/customers"


@dataclasses.dataclass
class StiggResumeConfig:
    # Cursor for the next page: Stigg returns it as `pagination.next` and accepts it back as
    # the `after` query param. A crashed full-refresh sync resumes from the page after the last
    # one yielded; merge dedupes the re-pulled page on the primary key. `None` means start from
    # the first page.
    cursor: str | None = None


class StiggCursorPaginator(JSONResponseCursorPaginator):
    """Cursor paginator for Stigg's list contract.

    Stigg wraps records in ``{"data": [...], "pagination": {"next": ..., "prev": ...}}`` and
    accepts the `next` cursor back as the ``after`` query param. Beyond the built-in null-cursor
    stop, an EMPTY page also ends the sync — a defensive guard so a buggy upstream cursor that
    keeps returning a non-null `next` can't loop the sync forever.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="pagination.next", cursor_param="after")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not data:
            self._has_next_page = False


def _accept_header() -> dict[str, str]:
    # Auth (the X-API-KEY header) is supplied via the framework auth config so its value is
    # redacted from logs and raised errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def stigg_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[StiggResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = STIGG_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": STIGG_BASE_URL,
            "headers": _accept_header(),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"},
            "paginator": StiggCursorPaginator(),
        },
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data",
                    # A 200 whose body isn't the `{"data": [...]}` shape (a non-dict body or a
                    # missing/ non-list `data` key) is treated as transient — retry rather than
                    # fail loud or ingest the stray payload as a single garbage row.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next page (already-yielded pages are persisted) rather than skipping it; merge
        # dedupes the re-pulled page on the primary key.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(StiggResumeConfig(cursor=str(state["cursor"])))

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
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # Server API keys are environment-wide, so probing one cheap endpoint validates access to
    # every list endpoint. The framework probe swallows transport errors and returns (ok, status).
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{STIGG_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        headers={"X-API-KEY": api_key, **_accept_header()},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys."
    if status is None:
        return False, "Could not validate Stigg API key"
    return False, f"Stigg returned HTTP {status}"
