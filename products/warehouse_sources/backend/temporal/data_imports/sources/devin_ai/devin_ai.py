import re
import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.settings import DEVIN_AI_ENDPOINTS

DEVIN_AI_BASE_URL = "https://api.devin.ai"
# v3 cursor pagination caps `first` at 200.
PAGE_SIZE = 200


@dataclasses.dataclass
class DevinAIResumeConfig:
    # Opaque cursor from the previous page's `end_cursor`, passed back as `after`. None starts at page 1.
    after: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


# Devin org IDs look like `org-<slug>`. Constrain to the characters an ID can legitimately contain so a
# malformed value can't inject `/` or `?` and route the stored API key at a different Devin API path.
_ORG_ID_RE = re.compile(r"[a-zA-Z0-9._-]+")


def _validate_org_id(org_id: str) -> str:
    org = org_id.strip()
    if not _ORG_ID_RE.fullmatch(org):
        raise ValueError(f"Invalid Devin organization ID: {org_id}")
    return org


def _endpoint_path(endpoint: str, org_id: str) -> str:
    return DEVIN_AI_ENDPOINTS[endpoint].path.format(org_id=_validate_org_id(org_id))


class DevinCursorPaginator(BasePaginator):
    """Cursor paginator for Devin's v3 list envelope.

    The response body carries ``{"items", "end_cursor", "has_next_page"}``. Each page after the first
    is fetched with ``after=<previous end_cursor>``. Pagination stops as soon as the API reports no
    next page OR omits the cursor — the ``has_next_page`` guard defends against a stale cursor lingering
    on the final page (which would otherwise loop forever). Resumable: a saved ``after`` cursor is
    replayed onto the first request so a restart continues from the last completed page.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        if self._after is None:
            return
        if request.params is None:
            request.params = {}
        request.params["after"] = self._after

    def init_request(self, request: Request) -> None:
        # Seed a resumed cursor onto the first request.
        self._apply_cursor(request)

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            self._has_next_page = False
            return

        next_cursor = body.get("end_cursor")
        if body.get("has_next_page") and next_cursor:
            self._after = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # ``_after`` already points at the next page's cursor; only meaningful while more pages remain.
        return {"after": self._after} if self._has_next_page and self._after is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after = state.get("after")
        if after is not None:
            self._after = after
            self._has_next_page = True

    def __str__(self) -> str:
        return "DevinCursorPaginator()"


def devin_ai_source(
    api_key: str,
    org_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DevinAIResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = DEVIN_AI_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": DEVIN_AI_BASE_URL,
            # Only the non-secret Accept header goes here; the Bearer token is supplied via the
            # framework `auth` config so its value is redacted from logs.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    # `_endpoint_path` validates org_id so a malformed value can't inject `/` or `?`
                    # and retarget the stored key at a different Devin API path.
                    "path": _endpoint_path(endpoint, org_id),
                    "params": {"first": PAGE_SIZE},
                    "data_selector": "items",
                    "paginator": DevinCursorPaginator(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.after is not None:
            initial_paginator_state = {"after": resume.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("after") is not None:
            resumable_source_manager.save_state(DevinAIResumeConfig(after=str(state["after"])))

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
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        column_hints=resource.column_hints,
    )


def get_status_code(api_key: str, org_id: str, endpoint: str) -> int:
    """Cheap single-page probe used by credential validation. Returns the HTTP status code."""
    url = f"{DEVIN_AI_BASE_URL}{_endpoint_path(endpoint, org_id)}"
    session = make_tracked_session(redact_values=(api_key,))
    response = session.get(url, params={"first": 1}, headers=_get_headers(api_key), timeout=10)
    return response.status_code


def validate_credentials(api_key: str, org_id: str, endpoint: str = "sessions") -> int:
    """Probe the given endpoint and return its HTTP status code (or raise on transport failure)."""
    return get_status_code(api_key, org_id, endpoint)
