import time
from collections.abc import AsyncIterable, Callable, Iterable, Iterator
from typing import Any, Optional

import structlog
from requests import Request, Response, Session
from requests.exceptions import HTTPError
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.settings import (
    INTERCOM_ENDPOINTS,
    IntercomEndpointConfig,
)

INTERCOM_API_BASE = "https://api.intercom.io"
INTERCOM_API_VERSION = "2.13"

logger = structlog.get_logger(__name__)


def _is_not_found(exc: HTTPError) -> bool:
    """A child row referenced by a parent can vanish (deleted/merged) between
    the parent listing and the per-row detail fetch — Intercom then returns
    404. Skip that single row instead of failing the whole sync."""
    return exc.response is not None and exc.response.status_code == 404


def _is_scroll_exists(exc: HTTPError) -> bool:
    """Intercom permits only one open companies scroll per workspace; opening a
    new scroll while another is still alive returns `400` with `code:
    scroll_exists`. A scroll left behind by an interrupted or concurrent sync
    clears itself once it expires (~1 min idle), so the lock is transient —
    wait it out and retry rather than failing the whole sync. Match on the
    stable error `code`, not the message text or URL."""
    resp = exc.response
    if resp is None or resp.status_code != 400:
        return False
    try:
        body = resp.json()
    except Exception:
        return False
    errors = body.get("errors") if isinstance(body, dict) else None
    return any(isinstance(e, dict) and e.get("code") == "scroll_exists" for e in errors or [])


def _is_server_error(exc: HTTPError) -> bool:
    """Intercom's companies Scroll API intermittently returns a 5xx mid-walk —
    a transient backend blip, not a poisoned cursor. Retrying the identical
    scroll request clears it, so back off and retry inline rather than failing
    the whole sync. Distinct from the short transport-level retry: this gives
    the flaky endpoint a wider window before a Temporal activity retry."""
    resp = exc.response
    return resp is not None and 500 <= resp.status_code < 600


def _is_scroll_expired(exc: HTTPError) -> bool:
    """A companies scroll cursor can be invalidated mid-walk (idle expiry, or a
    concurrent scroll on the workspace — only one is allowed); the continuation
    then returns 404. The scroll walk only ever hits `/companies/scroll`, so any
    404 there is a dead cursor rather than a missing row — distinct from
    `_is_not_found`, which classifies a vanished child row on a per-row fetch."""
    resp = exc.response
    return resp is not None and resp.status_code == 404


def _default_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Intercom-Version": INTERCOM_API_VERSION,
    }


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", **_default_headers()}


# The substream walk reaches `/conversations/search` via POST (the companies
# scroll walk is all GET). The shared `DEFAULT_RETRY` excludes POST from
# `allowed_methods`, so a transient read timeout on that call is *not* retried —
# unlike the GET calls in the same walk, which retry transparently. This POST is
# a read-only, idempotent query (the body just carries the query + cursor), so
# it's safe to retry it on transient read timeouts and 429/5xx like everything else.
# Derived from DEFAULT_RETRY so the shared policy stays the single source of
# truth — the only intentional difference is adding POST to allowed_methods.
_INTERCOM_RETRY = Retry(
    total=DEFAULT_RETRY.total,
    backoff_factor=DEFAULT_RETRY.backoff_factor,
    status_forcelist=DEFAULT_RETRY.status_forcelist,
    allowed_methods=frozenset(DEFAULT_RETRY.allowed_methods or ()) | {"POST"},
    raise_on_status=DEFAULT_RETRY.raise_on_status,
)


def _make_intercom_session(access_token: str) -> Session:
    """Build a tracked session with Intercom auth + default headers baked in.

    Reusing one session across the many requests a sync makes lets urllib3
    keep the underlying TCP+TLS connection alive — the substream generators
    (one GET per parent row) are the main beneficiary.
    """
    return make_tracked_session(headers=_auth_headers(access_token), retry=_INTERCOM_RETRY)


class IntercomSearchPaginator(BasePaginator):
    """Paginator for Intercom POST `/<resource>/search` endpoints.

    Intercom's search APIs put the pagination cursor in the request body
    (``pagination.starting_after``) rather than the query string, so the
    standard ``JSONResponseCursorPaginator`` — which writes to
    ``request.params`` — doesn't fit. The next cursor is read from
    ``pages.next.starting_after`` in the response, the same shape the list
    endpoints use.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_cursor: Optional[str] = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            payload = response.json()
        except Exception:
            self._has_next_page = False
            self._next_cursor = None
            return
        next_block = (payload.get("pages") or {}).get("next") or {}
        cursor = next_block.get("starting_after") if isinstance(next_block, dict) else None
        if cursor:
            self._next_cursor = cursor
            self._has_next_page = True
        else:
            self._next_cursor = None
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._next_cursor is None or request.json is None:
            return
        pagination = request.json.setdefault("pagination", {})
        pagination["starting_after"] = self._next_cursor


def _build_search_body(
    cfg: IntercomEndpointConfig,
    incremental_field: str,
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    """Build the POST body for Intercom's ``/<resource>/search`` endpoints.

    ``value: 0`` is the historical-backfill case (matches every record);
    once we have a watermark from a prior sync we filter ``<field> > <ts>``.
    Sorting ascending on the same field so the cursor advances monotonically
    — without it Intercom returns by relevance and the watermark we persist
    would be meaningless.
    """
    cursor_value = int(db_incremental_field_last_value) if db_incremental_field_last_value is not None else 0
    return {
        "query": {"field": incremental_field, "operator": ">", "value": cursor_value},
        "pagination": {"per_page": cfg.page_size},
        "sort": {"field": incremental_field, "order": "ascending"},
    }


def _build_paginator(cfg: IntercomEndpointConfig) -> BasePaginator:
    if cfg.paginator_kind == "search":
        return IntercomSearchPaginator()
    if cfg.paginator_kind == "cursor":
        return JSONResponseCursorPaginator(
            cursor_path="pages.next.starting_after",
            cursor_param="starting_after",
        )
    if cfg.paginator_kind == "next_url":
        return JSONResponsePaginator(next_url_path="pages.next")
    return SinglePagePaginator()


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    cfg = INTERCOM_ENDPOINTS[name]

    endpoint: Endpoint = {
        "path": cfg.path,
        "data_selector": cfg.data_selector,
        "paginator": _build_paginator(cfg),
    }

    if cfg.method == "POST":
        endpoint["method"] = "POST"

    if cfg.paginator_kind == "search":
        # Even in full-refresh mode the search endpoints need a query body;
        # `value: 0` matches every record. Default to "updated_at" (the only
        # cursor Intercom search endpoints support) when no field is passed.
        endpoint["json"] = _build_search_body(cfg, incremental_field or "updated_at", db_incremental_field_last_value)
    elif cfg.paginator_kind in ("cursor", "next_url"):
        params: dict[str, Any] = {"per_page": cfg.page_size, **cfg.extra_params}
        if cfg.incremental_query_param:
            # Intercom's `/admins/activity_logs` returns a much smaller default
            # window when called without `created_at_after`, so we always set
            # the param. `0` matches every record (Unix epoch start).
            if should_use_incremental_field and db_incremental_field_last_value is not None:
                params[cfg.incremental_query_param] = int(db_incremental_field_last_value)
            else:
                params[cfg.incremental_query_param] = 0
        endpoint["params"] = params
    elif cfg.paginator_kind == "single" and cfg.extra_params:
        endpoint["params"] = dict(cfg.extra_params)

    # Upsert on incremental syncs so updates to existing rows replace the
    # prior version instead of appending duplicates. Full-refresh endpoints
    # stay on replace.
    is_incremental = should_use_incremental_field and (
        cfg.paginator_kind == "search" or cfg.incremental_query_param is not None
    )
    write_disposition: Any = {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace"

    return {
        "name": cfg.name,
        "table_name": cfg.name,
        "write_disposition": write_disposition,
        "endpoint": endpoint,
        "table_format": "delta",
    }


def _resolve_intercom_url(path_or_url: str) -> str:
    """Accept either an API path or a full URL (e.g. a `pages.next` link)."""
    return path_or_url if path_or_url.startswith("http") else f"{INTERCOM_API_BASE}{path_or_url}"


def _intercom_get(session: Session, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = session.get(_resolve_intercom_url(path_or_url), params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _intercom_post(session: Session, path_or_url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = session.post(_resolve_intercom_url(path_or_url), json=body, timeout=30)
    response.raise_for_status()
    return response.json()


def _iter_conversations(
    session: Session,
    incremental_field: str,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[dict[str, Any]]:
    """Walk `POST /conversations/search` honoring the same `updated_at >`
    server-side filter the conversations endpoint uses, so substreams only
    refetch parents whose timestamp advanced."""
    body = _build_search_body(INTERCOM_ENDPOINTS["conversations"], incremental_field, db_incremental_field_last_value)
    while True:
        payload = _intercom_post(session, "/conversations/search", body)
        yield from (payload.get("conversations") or [])
        next_block = (payload.get("pages") or {}).get("next") or {}
        cursor = next_block.get("starting_after") if isinstance(next_block, dict) else None
        if not cursor:
            return
        body["pagination"]["starting_after"] = cursor


def _conversation_parts_generator(
    session: Session,
    incremental_field: str,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[dict[str, Any]]:
    """Yield each conversation part. Parents are server-filtered by
    `updated_at >`; the part rows themselves carry their own `updated_at`,
    so the pipeline's cursor watermark advances per-part. `conversation_id`
    is injected onto each row for joinability."""
    for conv in _iter_conversations(session, incremental_field, db_incremental_field_last_value):
        try:
            full = _intercom_get(session, f"/conversations/{conv['id']}")
        except HTTPError as exc:
            if _is_not_found(exc):
                logger.warning("intercom_conversation_not_found", conversation_id=conv["id"])
                continue
            raise
        parts = (full.get("conversation_parts") or {}).get("conversation_parts") or []
        for part in parts:
            part["conversation_id"] = conv["id"]
            yield part


# Intercom expires an idle companies scroll after ~1 minute, so a stale scroll
# left by an interrupted or concurrent sync clears within that window. Wait
# past it before retrying the open, and cap the retries so a genuinely stuck
# lock still surfaces instead of looping forever.
_SCROLL_EXISTS_BACKOFF_SECONDS = 60
_SCROLL_EXISTS_MAX_RETRIES = 2

# Transient 5xx from the companies Scroll API (see `_is_server_error`). Retry the
# identical request inline with exponential backoff, then let it surface so
# Temporal retries the activity (which re-opens a fresh scroll).
_SCROLL_SERVER_ERROR_BACKOFF_SECONDS = 2.0
_SCROLL_SERVER_ERROR_MAX_RETRIES = 3

# A companies scroll cursor can be invalidated mid-walk: Intercom expires an idle
# scroll (~1 min) and permits only one open scroll per workspace, so a concurrent
# sync opening its own scroll kills this one. The continuation then returns 404. A
# scroll can't be resumed, only restarted from the beginning, so recovery is a full
# re-walk — safe only where no rows have been emitted yet (see `_drain_company_ids`).
_SCROLL_EXPIRED_MAX_RETRIES = 2


def _scroll_companies_get(session: Session, scroll_param: str | None = None) -> dict[str, Any]:
    """Fetch one `/companies/scroll` page, retrying a transient 5xx inline.

    `scroll_param` is None to open the scroll, or the cursor from the prior page
    to continue it. Retrying the same request is safe — the cursor doesn't
    advance until a page is returned, so a retried call yields the same page
    without duplicating or skipping rows."""
    params = {"scroll_param": scroll_param} if scroll_param is not None else None
    for attempt in range(_SCROLL_SERVER_ERROR_MAX_RETRIES + 1):
        try:
            return _intercom_get(session, "/companies/scroll", params=params)
        except HTTPError as exc:
            if _is_server_error(exc) and attempt < _SCROLL_SERVER_ERROR_MAX_RETRIES:
                wait = _SCROLL_SERVER_ERROR_BACKOFF_SECONDS * (2**attempt)
                logger.warning(
                    "intercom_companies_scroll_server_error_retry",
                    attempt=attempt + 1,
                    backoff_seconds=wait,
                    status_code=exc.response.status_code if exc.response is not None else None,
                )
                time.sleep(wait)
                continue
            raise
    # Unreachable: the final attempt either returns or re-raises above.
    raise AssertionError("unreachable")


def _open_companies_scroll(session: Session) -> dict[str, Any]:
    """Open a fresh companies scroll, waiting out a stale `scroll_exists` lock.

    See `_is_scroll_exists`: a scroll left open by an interrupted or concurrent
    sync blocks a new one with `400 scroll_exists` until it expires. Back off
    and retry the open instead of failing — re-opening is the only recovery, as
    a scroll can't be resumed from a point, only restarted from the beginning
    (which is exactly what opening again does, and no rows have been yielded
    yet at this stage)."""
    for attempt in range(_SCROLL_EXISTS_MAX_RETRIES + 1):
        try:
            return _scroll_companies_get(session)
        except HTTPError as exc:
            if _is_scroll_exists(exc) and attempt < _SCROLL_EXISTS_MAX_RETRIES:
                logger.warning(
                    "intercom_companies_scroll_exists_retry",
                    attempt=attempt + 1,
                    backoff_seconds=_SCROLL_EXISTS_BACKOFF_SECONDS,
                )
                time.sleep(_SCROLL_EXISTS_BACKOFF_SECONDS)
                continue
            raise
    # Unreachable: the final attempt either returns or re-raises above.
    raise AssertionError("unreachable")


def _iter_companies(session: Session) -> Iterator[dict[str, Any]]:
    """Walk every company via `GET /companies/scroll` (full refresh).

    `POST /companies/list` is hard-capped at 10,000 companies — paging past
    that ceiling makes Intercom return `400 bad_request: page limit reached,
    please use scroll API`. The Scroll API has no such ceiling: each response
    carries a `scroll_param` to feed into the next request, and the walk ends
    when `data` comes back empty (the scroll param then expires). Only one
    scroll can be open per workspace at a time, so the initial open backs off
    past a stale `scroll_exists` lock (see `_open_companies_scroll`)."""
    scroll_param: str | None = None
    while True:
        if scroll_param is None:
            payload = _open_companies_scroll(session)
        else:
            payload = _scroll_companies_get(session, scroll_param)
        data = payload.get("data") or []
        if not data:
            return
        yield from data
        scroll_param = payload.get("scroll_param")
        if not scroll_param:
            return


def _drain_company_ids(session: Session) -> list[str]:
    """Walk the whole companies scroll and collect every id, restarting the walk
    from the beginning if the scroll cursor expires mid-drain (404 on a
    continuation — see `_SCROLL_EXPIRED_MAX_RETRIES`).

    Restarting is safe here precisely because the ids are drained up front,
    before any segment row is yielded downstream: nothing has been written to the
    destination yet, so a re-walk can't duplicate rows. (The streaming `companies`
    endpoint can't recover this way — it yields rows as it walks, and the load is
    full-refresh with no primary-key dedup, so an expired cursor there surfaces
    and Temporal restarts the whole run from a freshly-wiped table instead.)"""
    for attempt in range(_SCROLL_EXPIRED_MAX_RETRIES + 1):
        try:
            return [company["id"] for company in _iter_companies(session)]
        except HTTPError as exc:
            if _is_scroll_expired(exc) and attempt < _SCROLL_EXPIRED_MAX_RETRIES:
                logger.warning("intercom_companies_scroll_expired_restart", attempt=attempt + 1)
                continue
            raise
    # Unreachable: the final attempt either returns or re-raises above.
    raise AssertionError("unreachable")


def _company_segments_generator(session: Session) -> Iterator[dict[str, Any]]:
    """Walk all companies and yield each attached segment with `company_id`
    injected. Full refresh — Intercom has no server-side timestamp filter on
    either parent or child.

    The scroll is drained up front rather than interleaved with the per-company
    segment fetches: Intercom expires an idle companies scroll after ~1 minute,
    and a slow stretch of `/companies/{id}/segments` calls between two scroll
    pages lets the cursor lapse — the next continuation then 404s mid-walk.
    Draining first keeps the scroll requests back-to-back so it stays alive;
    only the ids are held, not the full company payloads, so the memory
    footprint stays small. If the cursor is still invalidated mid-drain,
    `_drain_company_ids` restarts the walk from scratch."""
    company_ids = _drain_company_ids(session)
    for company_id in company_ids:
        try:
            payload = _intercom_get(session, f"/companies/{company_id}/segments")
        except HTTPError as exc:
            if _is_not_found(exc):
                logger.warning("intercom_company_not_found", company_id=company_id)
                continue
            raise
        for seg in payload.get("data", []) or []:
            seg["company_id"] = company_id
            yield seg


def _substream_items(
    session: Session,
    endpoint: str,
    incremental_field: str | None,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[dict[str, Any]]:
    if endpoint == "conversation_parts":
        if not incremental_field:
            # Substream still works without an incremental field — we just
            # walk every conversation. `updated_at` is the only declared
            # cursor, so default to it for the parent search filter.
            incremental_field = "updated_at"
        return _conversation_parts_generator(session, incremental_field, db_incremental_field_last_value)
    if endpoint == "company_segments":
        return _company_segments_generator(session)
    raise ValueError(f"Unknown Intercom substream endpoint: {endpoint}")


def validate_credentials(access_token: str, schema_name: str | None = None) -> tuple[bool, str | None]:
    """Validate an Intercom access token by hitting `/me`.

    Works identically with OAuth-issued access tokens and Personal Access
    Tokens — both flow as `Authorization: Bearer …`.

    At source-create (``schema_name is None``) we accept 403 — the token
    is genuine but the workspace hasn't granted scope for ``/me``. The
    user can still grant scope per-endpoint downstream. Per-schema calls
    (``schema_name`` set) re-raise 403 so the missing-scope error
    surfaces against the specific table the user tried to use.
    """
    if not access_token:
        return False, "Missing Intercom access token"

    try:
        response = _make_intercom_session(access_token).get(
            f"{INTERCOM_API_BASE}/me",
            timeout=10,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Your Intercom access token is invalid or expired. Please reconnect."
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "Your Intercom access token is missing required scopes. Please reconnect."
    return False, f"HTTP {response.status_code}: {response.text[:200]}"


def intercom_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    cfg = INTERCOM_ENDPOINTS[endpoint]
    items: Callable[[], Iterable[Any] | AsyncIterable[Any]]

    if cfg.paginator_kind == "substream":
        # One session built here is reused across the parent walk and every
        # per-row child fetch, so urllib3 keeps the connection alive instead
        # of re-handshaking per request.
        session = _make_intercom_session(access_token)
        items = lambda: _substream_items(session, endpoint, incremental_field, db_incremental_field_last_value)
    elif cfg.paginator_kind == "scroll":
        # The Scroll API doesn't fit the framework paginators (the cursor is a
        # `scroll_param`, not a request mutation), so `companies` walks it with a
        # custom iterator. One session is reused across the whole scroll walk.
        session = _make_intercom_session(access_token)
        items = lambda: _iter_companies(session)
    else:
        config: RESTAPIConfig = {
            "client": {
                "base_url": INTERCOM_API_BASE,
                "auth": {
                    "type": "bearer",
                    "token": access_token,
                },
                "headers": _default_headers(),
            },
            "resource_defaults": {},
            "resources": [
                get_resource(
                    endpoint,
                    should_use_incremental_field,
                    incremental_field,
                    db_incremental_field_last_value,
                )
            ],
        }
        resource = rest_api_resource(config, team_id, job_id, db_incremental_field_last_value)
        items = lambda: resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=cfg.primary_keys,
        partition_keys=[cfg.partition_key],
        partition_mode=cfg.partition_mode,
        partition_format=cfg.partition_format,
        partition_count=cfg.partition_count,
        partition_size=cfg.partition_size,
        sort_mode=cfg.sort_mode,
    )
