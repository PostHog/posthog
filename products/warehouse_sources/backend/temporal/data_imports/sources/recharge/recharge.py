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
from datetime import UTC, date, datetime
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.settings import (
    RECHARGE_ENDPOINTS,
    RechargeEndpointConfig,
)

RECHARGE_BASE_URL = "https://api.rechargeapps.com"
RECHARGE_API_VERSION = "2021-11"
# Per-endpoint page size lives on each `RechargeEndpointConfig` (default 250,
# Recharge's max); see `settings.py` for why some endpoints request less.


@dataclasses.dataclass
class RechargeResumeConfig:
    """Cursor state for resumable list iteration.

    ``cursor`` is the Recharge-issued ``next_cursor``; it encodes the original
    request filters (sort + timestamp window), so resuming only needs to replay
    the cursor. ``endpoint`` scopes the cursor to a single endpoint so we never
    replay a customers cursor against orders.
    """

    endpoint: str
    cursor: str


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
            next_cursor = response.json().get("next_cursor")
        except Exception:
            next_cursor = None
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
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Recharge wraps records under a key matching the resource
                    # (e.g. `{"customers": [...], "next_cursor": "..."}`).
                    "data_selector": endpoint,
                    "paginator": RechargeCursorPaginator(limit=config.page_size),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only replay a cursor issued for THIS endpoint — a customers cursor is
        # meaningless (and rejected) against orders.
        if resume is not None and resume.endpoint == endpoint:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next cursor remains; save AFTER a page is yielded so
        # a crash re-yields the last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(RechargeResumeConfig(endpoint=endpoint, cursor=state["cursor"]))

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
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
