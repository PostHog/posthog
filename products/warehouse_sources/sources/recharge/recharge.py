"""Recharge API client used by the data warehouse source.

Spec: https://developer.rechargepayments.com/2021-11 (API version 2021-11).

Recharge is a subscription-billing platform. The API is pure REST/JSON with
API-key auth (`X-Recharge-Access-Token`), cursor pagination, and server-side
timestamp filters (`updated_at_min` / `created_at_min`) for incremental syncs.

Built on the shared ``rest_source`` framework: the framework ``api_key`` auth
carries the token in the ``X-Recharge-Access-Token`` header and redacts it from
logs and error messages, and a small custom cursor paginator reproduces
Recharge's rule that a cursor page accepts only ``cursor`` + ``limit`` (the
original sort/filter params are baked into the cursor, and re-sending them 422s).

NOTE: these endpoint params were taken from the public 2021-11 docs and could
not be curl-verified against a live store during implementation (no test
credentials). The pagination/filter handling is intentionally conservative —
see inline comments where behavior is assumed rather than confirmed.
"""

import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from functools import partial
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.sources.recharge.settings import RECHARGE_ENDPOINTS, RechargeEndpointConfig
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    EndpointResource,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

RECHARGE_BASE_URL = "https://api.rechargeapps.com"
RECHARGE_API_VERSION = "2021-11"
# Per-endpoint page size lives on each `RechargeEndpointConfig` (default 250,
# Recharge's max); see `settings.py` for why some endpoints request less.


@dataclasses.dataclass(frozen=False)
class RechargeResumeConfig:
    """Cursor state for resumable list iteration.

    ``cursor`` is the Recharge-issued ``next_cursor``; it encodes the original
    request filters (sort + timestamp window), so resuming only needs to replay
    the cursor. ``endpoint`` scopes the cursor to a single endpoint so we never
    replay a customers cursor against orders. ``owner_resource`` names the
    ``metafields`` owner type that the cursor belongs to; with no cursor, the
    sync starts that owner type from its first page.
    """

    endpoint: str
    cursor: Optional[str] = None
    owner_resource: Optional[str] = None


class RechargeCursorPaginator(BasePaginator):
    """Cursor pagination for Recharge list endpoints.

    Recharge returns a ``next_cursor`` in each list response body. When following
    it, the API accepts ONLY ``cursor`` + ``limit`` — the original sort/filter
    params are baked into the cursor, and re-sending them returns a 422. So every
    cursor page (and a resumed first page) replaces the request params with just
    cursor + limit, while a fresh first page keeps the initial sort/filter params.
    """

    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit
        self._cursor: Optional[str] = None

    def _cursor_params(self) -> dict[str, Any]:
        return {"cursor": self._cursor, "limit": self.limit}

    def init_request(self, request: Request) -> None:
        # On a resumed run the seeded cursor replays only cursor + limit; a fresh
        # run (cursor is None) keeps the initial sort/filter params already set.
        if self._cursor is not None:
            request.params = self._cursor_params()

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        if isinstance(body, list) and len(body) >= self.limit:
            raise ValueError(
                f"Recharge returned a full page of {len(body)} rows with no next_cursor, "
                "so the rows after this page cannot be read."
            )
        next_cursor = body.get("next_cursor") if isinstance(body, dict) else None
        if next_cursor:
            self._cursor = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        request.params = self._cursor_params()

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor:
            self._cursor = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return f"RechargeCursorPaginator(limit={self.limit})"


def _headers() -> dict[str, str]:
    # Auth (the `X-Recharge-Access-Token` token) is supplied via the framework
    # api_key auth so its value is redacted from logs and errors; only the
    # non-secret version/accept headers are set here.
    return {"X-Recharge-Version": RECHARGE_API_VERSION, "Accept": "application/json"}


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value for Recharge's ``*_min`` filters.

    Recharge expects ISO 8601 without a timezone offset (e.g.
    ``2021-05-04T00:00:00``), interpreted as the store's timezone. We normalize
    to UTC first to keep behavior deterministic.
    """
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00")
    return str(value)


def _build_initial_params(
    config: RechargeEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Query params for the first page (cursor pages drop everything but limit)."""
    params: dict[str, Any] = {"limit": config.page_size}

    use_incremental = (
        config.supports_incremental
        and should_use_incremental_field
        and incremental_field is not None
        and db_incremental_field_last_value is not None
    )

    if use_incremental:
        # `incremental_field` is the user's chosen cursor column (updated_at or
        # created_at). Filter server-side on `<field>_min` and sort ascending on
        # the same field so the pipeline watermark advances monotonically.
        params[f"{incremental_field}_min"] = _format_incremental_value(db_incremental_field_last_value)
        sort_field = incremental_field
    else:
        sort_field = config.default_sort_field

    # Some endpoints (e.g. `/products` on the 2021-11 API) reject `sort_by`
    # outright with a 422 — they rely on cursor pagination for stable ordering.
    if config.supports_sort:
        params["sort_by"] = f"{sort_field}-asc"

    return params


def _page_rows(key: str, item: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    """Read the rows of a page that is either an envelope with the rows under ``key`` or a bare array."""
    if key in item:
        return item[key] or []
    if "id" in item:
        return item
    raise ValueError(f"Recharge {key} response has no {key} list (keys: {sorted(item)[:20]})")


def _iter_owner_resources(
    owner_count: int,
    start_index: int,
    start_state: Optional[dict[str, Any]],
    build_resource: Callable[[int, Optional[dict[str, Any]]], Any],
) -> Iterator[list[dict[str, Any]]]:
    for index in range(start_index, owner_count):
        yield from build_resource(index, start_state if index == start_index else None)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe ``/token_information`` — the cheapest call that confirms the token.

    Returns ``(ok, error)``. A 401 means the token is invalid; anything else
    reachable-and-2xx is treated as valid.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{RECHARGE_BASE_URL}/token_information",
        headers={"X-Recharge-Access-Token": api_key, **_headers()},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Recharge API token. Please check the token and try again."
    if status is None:
        return False, "Could not reach Recharge. Please check your connection and try again."
    return False, f"Recharge rejected the request (HTTP {status})."


def recharge_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RechargeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = RECHARGE_ENDPOINTS[endpoint]

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume: Optional[RechargeResumeConfig] = None
    if resumable_source_manager.can_resume():
        loaded = resumable_source_manager.load_state()
        # Only replay a cursor issued for THIS endpoint — a customers cursor is
        # meaningless (and rejected) against orders.
        if loaded is not None and loaded.endpoint == endpoint:
            resume = loaded

    def save_checkpoint(state: Optional[dict[str, Any]], owner_resource: Optional[str] = None) -> None:
        # Persist only when a next cursor remains; save AFTER a page is yielded so
        # a crash re-yields the last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(
                RechargeResumeConfig(endpoint=endpoint, cursor=state["cursor"], owner_resource=owner_resource)
            )

    def build_resource(
        request_params: dict[str, Any],
        initial_paginator_state: Optional[dict[str, Any]],
        resume_hook: Callable[[Optional[dict[str, Any]]], None],
    ) -> Resource:
        resource_config: EndpointResource = {
            "name": endpoint,
            "endpoint": {
                "path": config.path,
                "params": request_params,
                # Recharge wraps records under a key matching the resource
                # (e.g. `{"customers": [...], "next_cursor": "..."}`).
                "data_selector": None if config.accepts_bare_list else endpoint,
                "paginator": RechargeCursorPaginator(limit=config.page_size),
            },
        }
        if config.accepts_bare_list:
            resource_config["data_map"] = partial(_page_rows, endpoint)
        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": RECHARGE_BASE_URL,
                "headers": _headers(),
                # api_key auth injects the token into the `X-Recharge-Access-Token`
                # header and redacts it from logs and raised error messages.
                "auth": {
                    "type": "api_key",
                    "api_key": api_key,
                    "name": "X-Recharge-Access-Token",
                    "location": "header",
                },
            },
            "resource_defaults": {},
            "resources": [resource_config],
        }
        return rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=resume_hook,
            initial_paginator_state=initial_paginator_state,
        )

    resume_state = {"cursor": resume.cursor} if resume is not None and resume.cursor else None

    items: Callable[[], Iterable[Any]]
    if config.owner_resources:
        owners = config.owner_resources
        if resume is not None and resume.owner_resource in owners:
            start_index = owners.index(resume.owner_resource)
        else:
            start_index, resume_state = 0, None

        def save_owner_checkpoint(index: int, state: Optional[dict[str, Any]]) -> None:
            if state and state.get("cursor"):
                save_checkpoint(state, owners[index])
            elif index + 1 < len(owners):
                # Staged with the last page of an owner type, so a resume after that page starts the next one.
                resumable_source_manager.save_state(
                    RechargeResumeConfig(endpoint=endpoint, owner_resource=owners[index + 1])
                )

        def build_owner_resource(index: int, state: Optional[dict[str, Any]]) -> Resource:
            return build_resource(
                {**params, "owner_resource": owners[index]}, state, partial(save_owner_checkpoint, index)
            )

        resource = build_owner_resource(start_index, resume_state)
        owner_walk = Resource(
            partial(_iter_owner_resources, len(owners), start_index, resume_state, build_owner_resource),
            name=endpoint,
            hints=resource._hints,
        )

        def owner_walk_items() -> Iterable[Any]:
            return owner_walk

        items = owner_walk_items
    else:
        resource = build_resource(params, resume_state, save_checkpoint)

        def resource_items() -> Iterable[Any]:
            return resource

        items = resource_items

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        # Without `sort_by` the rows come in the API's default order, not by the
        # incremental field. An owner walk restarts the order for each owner type.
        sort_mode="asc" if config.supports_sort and not config.owner_resources else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
