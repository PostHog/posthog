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
from collections.abc import Iterable
from typing import Any, Optional, cast
from urllib.parse import quote, urlencode

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.settings import (
    MESSAGE_ID_PARAM_FIELD,
    MIXMAX_ENDPOINTS,
    PAGE_SIZE,
    MixmaxEndpointConfig,
)

MIXMAX_BASE_URL = "https://api.mixmax.com/v1"


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


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": MIXMAX_BASE_URL,
        # Auth (the `X-API-Token` header) goes through the framework auth config so its value is
        # redacted from logs and error messages; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Token", "location": "header"},
    }


def _with_encoded_message_id(row: dict[str, Any]) -> dict[str, Any]:
    row[MESSAGE_ID_PARAM_FIELD] = quote(str(row["_id"]), safe="")
    return row


def _fanout_source(
    api_key: str, endpoint: str, config: MixmaxEndpointConfig, team_id: int, job_id: str
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = MIXMAX_ENDPOINTS[config.fanout.parent_name]

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=MIXMAX_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # The parent page size rides in `fanout.parent_params`; the child takes no page size.
            page_size_param=None,
            parent_endpoint_extra={"paginator": MixmaxCursorPaginator(parent_config.path), "data_selector": "results"},
            # Child responses are a single `{results: [...]}` page, capped server-side.
            child_endpoint_extra={"paginator": SinglePagePaginator(), "data_selector": "results"},
            parent_data_map=_with_encoded_message_id,
        ),
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: dependent_resource,
        primary_keys=config.primary_keys,
        # Child rows follow the parent's newest-first order.
        sort_mode="desc",
    )


def mixmax_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MixmaxResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: MixmaxEndpointConfig = MIXMAX_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(api_key, endpoint, config, team_id, job_id)

    # Single-object `/…/me` endpoints take no pagination params; collections carry the page limit.
    params: dict[str, Any] = {} if config.single_object else {"limit": PAGE_SIZE}

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
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
