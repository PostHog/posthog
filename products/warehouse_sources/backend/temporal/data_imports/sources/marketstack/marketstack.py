import dataclasses
from datetime import date
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.settings import MARKETSTACK_ENDPOINTS

# Marketstack keeps two live API versions; v1 is stable, covers every endpoint we sync, and is
# available on the free plan. v2 only adds indices and the /latest lookups we don't use here.
MARKETSTACK_BASE_URL = "https://api.marketstack.com/v1"
# limit maxes out at 1000; larger pages mean fewer round trips against the 5 req/sec rate limit.
DEFAULT_PAGE_SIZE = 1000

# Marketstack (an APILayer product) returns HTTP 200 with an error envelope (`{"error": {"code": ...}}`).
# The transient codes are retried in-process; every listed permanent code (bad/blocked key, plan
# gating, exhausted monthly quota) fails fast and is surfaced with a stable `[code]` token matched by
# MarketstackSource.get_non_retryable_errors. An unrecognized error code has no `data` key, so the
# framework fails loud on the missing selector (data_selector_required) rather than syncing 0 rows.
_RETRYABLE_BODY_CODES = ("rate_limit_reached", "too_many_requests")
_PERMANENT_BODY_CODES = (
    "invalid_access_key",
    "missing_access_key",
    "inactive_user",
    "usage_limit_reached",
    "function_access_restricted",
    "https_access_restricted",
    "no_valid_symbols_provided",
)


@dataclasses.dataclass
class MarketstackResumeConfig:
    # Offset of the next page to fetch — Marketstack uses limit/offset pagination.
    next_offset: int


def _format_date(value: Any) -> str:
    """Format an incremental cursor for the `date_from` filter (Marketstack expects YYYY-MM-DD)."""
    # datetime is a subclass of date, so this covers both.
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    # A stored string cursor is already an ISO timestamp/date — keep just the date portion.
    return str(value)[:10]


def _response_actions() -> list[ResponseAction]:
    # The `content` matches the quoted error code as it appears in the JSON body, independent of
    # whitespace around the colon. Retryable codes first; each permanent code raises a secret-free,
    # non-retryable error whose message carries the `[code]` token get_non_retryable_errors matches.
    actions: list[ResponseAction] = [
        {"content": f'"{code}"', "action": "retry", "message": f"Marketstack API error (retryable) [{code}]"}
        for code in _RETRYABLE_BODY_CODES
    ]
    actions.extend(
        {"content": f'"{code}"', "action": "raise", "message": f"Marketstack API error [{code}]"}
        for code in _PERMANENT_BODY_CODES
    )
    # Marketstack also returns hard 401/403 for a bad key / plan gating. Author a secret-free message
    # (the access_key rides in the query string, so a bare raise_for_status would leak it) that still
    # matches the stable host prefix in get_non_retryable_errors.
    actions.append(
        {
            "status_code": 401,
            "action": "raise",
            "message": "401 Client Error: Unauthorized for url: https://api.marketstack.com",
        }
    )
    actions.append(
        {
            "status_code": 403,
            "action": "raise",
            "message": "403 Client Error: Forbidden for url: https://api.marketstack.com",
        }
    )
    return actions


def marketstack_source(
    access_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MarketstackResumeConfig],
    symbols: str | None = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MARKETSTACK_ENDPOINTS[endpoint]

    if config.requires_symbols and not (symbols and symbols.strip()):
        # Selecting a time-series table with no symbols is a permanent misconfiguration; fail loud
        # with a fix-it message rather than issuing a request that can never make progress.
        raise ValueError(
            f"Marketstack API error [missing_symbols]: the '{endpoint}' table requires one or more "
            "symbols. Add symbols to the source configuration, then resync."
        )

    params: dict[str, Any] = {}
    if config.requires_symbols and symbols:
        params["symbols"] = symbols
    if config.incremental_fields:
        # Ascending sort keeps rows in date order so the pipeline watermark advances correctly; it's
        # also required for date_from windowing to line up with SourceResponse.sort_mode="asc".
        params["sort"] = "ASC"
        if db_incremental_field_last_value is not None:
            params["date_from"] = _format_date(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": MARKETSTACK_BASE_URL,
            # access_key rides in the query string; the framework auth redacts its value from every
            # logged URL, captured sample, and raised error message.
            "auth": {"type": "api_key", "api_key": access_key, "name": "access_key", "location": "query"},
            "paginator": OffsetPaginator(limit=DEFAULT_PAGE_SIZE, total_path="pagination.total"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    # A 200 body without `data` means an error envelope (recognized codes are caught
                    # by response_actions first) or a changed shape — fail loud, don't sync 0 rows.
                    "data_selector_required": True,
                    "response_actions": _response_actions(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.next_offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge/replace dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(MarketstackResumeConfig(next_offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # We always request `sort=ASC` on the time-series feeds and reference tables are unordered
        # full refreshes, so ascending is safe across the board.
        sort_mode="asc",
        **partition_kwargs,
    )


def validate_credentials(access_key: str) -> bool:
    # `/exchanges` is a static reference endpoint available on every plan (including free) and needs
    # no symbols, so it's a cheap probe that the access key is genuine. A bad key can surface either
    # as a non-200 status or as an HTTP 200 with a body-level error envelope, so both are checked.
    url = f"{MARKETSTACK_BASE_URL}/exchanges"
    params: dict[str, Any] = {"access_key": access_key, "limit": 1}
    try:
        session = make_tracked_session(redact_values=(access_key,))
        response = session.get(url, params=params, timeout=10)
    except Exception:
        return False

    if response.status_code != 200:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return not (isinstance(body, dict) and bool(body.get("error")))
