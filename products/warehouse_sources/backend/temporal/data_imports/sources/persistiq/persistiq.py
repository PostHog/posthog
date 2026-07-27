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
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.settings import PERSISTIQ_ENDPOINTS

# The base URL already includes the `/v1` API version segment; endpoint paths are appended to it.
PERSISTIQ_BASE_URL = "https://api.persistiq.com/v1"
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint. `/users` is typically the smallest collection.
DEFAULT_PROBE_PATH = "/users"


@dataclasses.dataclass
class PersistiqResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1


def _headers() -> dict[str, str]:
    # Auth (the `x-api-key` header) is supplied via the framework auth config so its value is
    # redacted from logs and raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


class PersistiqPaginator(PageNumberPaginator):
    """PersistIQ paginates its list endpoints by 1-indexed ``page`` and signals whether more pages
    remain with a body-level ``has_more`` flag rather than a total-pages count, so termination reads
    that flag (an empty page is a defensive stop). No built-in paginator covers this shape.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page=1, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # An empty page ends the collection defensively (mirrors the old `not items` break).
        if not data:
            self._has_next_page = False
            return
        try:
            has_more = bool(response.json().get("has_more", False))
        except Exception:
            has_more = False
        # `has_more` is the authoritative end-of-collection signal.
        if not has_more:
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True


def persistiq_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PersistiqResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PERSISTIQ_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PERSISTIQ_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "api_key", "api_key": api_key, "name": "x-api-key", "location": "header"},
            "paginator": PersistiqPaginator(),
        },
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": config.list_key,
                    # A 200 whose body isn't the expected `{list_key: [...]}` envelope (a bare array,
                    # a missing resource key, or a non-list value) is treated as transient and
                    # retried — the old source raised a retryable error for exactly these shapes.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page > 1:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the next page (already-yielded pages are persisted) and merge dedupes on the primary key.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(PersistiqResumeConfig(next_page=int(state["page"])))

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


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a single list endpoint to validate the account-wide API key.

    The key grants access to every list endpoint, so one probe is enough. Maps the probe result to
    the same ``(is_valid, message)`` pairs the source has always returned.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{PERSISTIQ_BASE_URL}{DEFAULT_PROBE_PATH}?page=1",
        headers={"x-api-key": api_key, "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid PersistIQ API key"
    if status is None:
        return False, "Could not connect to PersistIQ"
    return False, f"PersistIQ returned HTTP {status}"
