"""Mixmax REST transport (built on the shared ``rest_source`` framework).

Mixmax is a sales-engagement / email-productivity API served at https://api.mixmax.com/v1 with
`X-API-Token` header auth. List endpoints are cursor-paginated behind a `{results, next, hasNext,
previous, hasPrevious}` wrapper; `/…/me` endpoints return a single caller-scoped object with no
wrapper. Collections are returned newest-first (by creation time).

Incremental note: the API exposes no server-side timestamp filter (no `updated_after`/`since`), so
every endpoint is full-refresh only. A "client-side cursor walk" would still fetch every page each
run, so it buys nothing over full refresh and we don't advertise incremental for any table. We do
persist the pagination cursor between Temporal heartbeats (via `ResumableSourceManager`) so a sync
interrupted mid-pagination resumes from the last page rather than restarting the whole endpoint.

Rate limits: 120 requests / 60s per user+IP, `429` with `Retry-After`. The framework client retries
429/5xx (honoring `Retry-After`) and reissues transient network/truncation failures.
"""

import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.settings import (
    MIXMAX_ENDPOINTS,
    MixmaxEndpointConfig,
)

MIXMAX_BASE_URL = "https://api.mixmax.com/v1"
# Docs default the page size to 50 and cap it around 300; 100 keeps request volume low against the
# 120 req/min ceiling without risking a rejected oversized page.
PAGE_SIZE = 100


@dataclasses.dataclass
class MixmaxResumeConfig:
    # Fully-built URL of the next page to fetch. None means "start at the endpoint's first page".
    next_url: str | None = None


def _build_url(path: str, single_object: bool, next_cursor: str | None = None) -> str:
    """Build a Mixmax list URL. `/…/me` single-object endpoints take no pagination params."""
    if single_object:
        return f"{MIXMAX_BASE_URL}{path}"
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if next_cursor:
        # `next`/`previous` are documented as URL-safe strings, but urlencode keeps us correct
        # regardless of what the server hands back.
        params["next"] = next_cursor
    return f"{MIXMAX_BASE_URL}{path}?{urlencode(params)}"


def _reshape_row(item: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    """Normalize a Mixmax response body into rows.

    Runs per top-level item once the framework has wrapped the parsed body (no ``data_selector``):
    - A cursor-wrapped collection ``{results: [...], next, hasNext}`` explodes into its rows.
    - A single-object ``/…/me`` body (a dict without ``results``) maps 1:1 to one record.
    - A bare-list body reaches this map already element-wise, so each element maps 1:1.

    This mirrors the old ``_extract_page`` heuristic (`"results" in body`) exactly.
    """
    if "results" in item:
        return item.get("results") or []
    return item


class MixmaxCursorPaginator(BaseNextUrlPaginator):
    """Cursor pagination gated on the wrapper's ``hasNext`` flag.

    The body carries a ``next`` cursor token (not a full URL) and a ``hasNext`` boolean; the server
    can echo a ``next`` value on the last page, so pagination MUST stop on ``hasNext == false`` even
    when ``next`` is non-empty. We rebuild the self-contained next-page URL (``?limit=…&next=…``) so
    the framework's next-URL machinery (resume seeding + param clearing) applies unchanged, and the
    persisted resume state stays a full URL — byte-compatible with the pre-migration ``next_url``.
    """

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None

        next_cursor = body.get("next") if isinstance(body, dict) and body.get("hasNext") else None
        if next_cursor:
            self._next_url = _build_url(self._path, single_object=False, next_cursor=next_cursor)
            self._has_next_page = True
        else:
            self._has_next_page = False


def mixmax_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MixmaxResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: MixmaxEndpointConfig = MIXMAX_ENDPOINTS[endpoint]

    # Single-object `/…/me` endpoints take no pagination params; collections carry the page limit.
    params: dict[str, Any] = {} if config.single_object else {"limit": PAGE_SIZE}

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": MIXMAX_BASE_URL,
            # Auth (the `X-API-Token` header) goes through the framework auth config so its value is
            # redacted from logs and error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Token", "location": "header"},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # No data_selector: the body is reshaped per-item by `_reshape_row`, which handles
                    # both the cursor-wrapped collection and the single-object `/…/me` shapes.
                    "paginator": MixmaxCursorPaginator(config.path),
                },
                "data_map": _reshape_row,
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
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(MixmaxResumeConfig(next_url=state["next_url"]))

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
        # Collections arrive newest-first; declaring it honestly keeps full-refresh page ordering
        # transparent (no incremental watermark is derived for these tables).
        sort_mode="desc",
    )


def validate_credentials(api_key: str) -> bool:
    """Probe the cheapest always-available endpoint (`/users/me`) to confirm the token is genuine."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{MIXMAX_BASE_URL}/users/me",
        headers={"X-API-Token": api_key, "Accept": "application/json"},
    )
    return ok
