import dataclasses
from collections.abc import Iterator
from datetime import date
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.settings import (
    MARKETSTACK_ENDPOINTS,
    MarketstackEndpointConfig,
)

# Opaque Marketstack version labels (never parsed/ordered). Each version is served under its own
# path segment; the source pin selects the base URL. v1 is deprecated (vendor sunset 2025-06-30);
# v2 is the current GA API — same auth, envelope, and pagination, only additive response fields for
# every endpoint we sync, which the auto-inferred schema absorbs.
MARKETSTACK_API_VERSION_V1 = "v1"
MARKETSTACK_API_VERSION_V2 = "v2"

_MARKETSTACK_BASE_URLS = {
    MARKETSTACK_API_VERSION_V1: "https://api.marketstack.com/v1",
    MARKETSTACK_API_VERSION_V2: "https://api.marketstack.com/v2",
}


def marketstack_base_url(api_version: str) -> str:
    # Every supported label must map to a base URL — an unmapped pin raises rather than silently
    # sending an unversioned host (tracking "latest", the drift the versioning framework prevents).
    try:
        return _MARKETSTACK_BASE_URLS[api_version]
    except KeyError:
        raise ValueError(f"Unsupported Marketstack API version: {api_version!r}")


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
    # Offset of the next page to fetch — Marketstack uses limit/offset pagination. Fan-out
    # endpoints store the index of the next ticker / CIK to request instead.
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


def _split_values(raw: str | None) -> list[str]:
    values = (value.strip() for value in (raw or "").split(","))
    return list(dict.fromkeys(value for value in values if value))


def _company_rating_rows(item: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    basics = item.get("basics") or {}
    analysts = (item.get("output") or {}).get("analysts") or []
    rows = []
    for analyst in analysts:
        row = {key: value for key, value in analyst.items() if key != "rating"}
        row.update(analyst.get("rating") or {})
        rows.append({"ticker": basics.get("ticker") or ticker, "company_name": basics.get("company_name"), **row})
    return rows


def _filing_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    # SEC returns recent filings as parallel arrays, one array per field.
    recent = (item.get("filings") or {}).get("recent") or {}
    columns = {key: values for key, values in recent.items() if isinstance(values, list)}
    count = len(columns.get("accession_number") or [])
    company = {"cik_code": item.get("cik_code"), "company_name": item.get("company_name")}
    return [
        {**company, **{key: values[i] if i < len(values) else None for key, values in columns.items()}}
        for i in range(count)
    ]


def _shape_rows(endpoint: str, item: dict[str, Any], value: str) -> list[dict[str, Any]]:
    if endpoint == "companyratings":
        return _company_rating_rows(item, value)
    if endpoint == "submissions":
        return _filing_rows(item)
    return [{"ticker": value, **item}]


def _fan_out_pages(
    client: RESTClient,
    config: MarketstackEndpointConfig,
    values: list[str],
    resumable_source_manager: ResumableSourceManager[MarketstackResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    assert config.fan_out_param is not None
    start = 0
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            start = resume.next_offset
    hooks = create_response_hooks(_response_actions(), resource_name=config.name)

    for index in range(start, len(values)):
        if index > start and config.request_interval_seconds:
            interruptible_wait(config.request_interval_seconds, safe_point=resumable_source_manager.safe_point)
        rows: list[dict[str, Any]] = []
        for page in client.paginate(
            path=config.path,
            params={config.fan_out_param: values[index]},
            data_selector=config.data_selector,
            data_selector_required=True,
            hooks=hooks,
        ):
            for item in page:
                rows.extend(_shape_rows(config.name, item, values[index]))
        if index + 1 < len(values):
            resumable_source_manager.save_state(MarketstackResumeConfig(next_offset=index + 1))
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def _fan_out_source(
    access_key: str,
    config: MarketstackEndpointConfig,
    values: list[str],
    resumable_source_manager: ResumableSourceManager[MarketstackResumeConfig],
    api_version: str,
) -> SourceResponse:
    client = RESTClient(
        base_url=marketstack_base_url(api_version),
        auth=APIKeyAuth(api_key=access_key, name="access_key", location="query"),
        paginator=SinglePagePaginator(),
    )
    return SourceResponse(
        name=config.name,
        items=lambda: _fan_out_pages(client, config, values, resumable_source_manager),
        primary_keys=config.primary_keys,
        sort_mode="asc",
    )


def marketstack_source(
    access_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MarketstackResumeConfig],
    api_version: str,
    symbols: str | None = None,
    db_incremental_field_last_value: Optional[Any] = None,
    cik_codes: str | None = None,
) -> SourceResponse:
    config = MARKETSTACK_ENDPOINTS[endpoint]

    if config.fan_out_over is not None:
        values = _split_values(symbols if config.fan_out_over == "symbols" else cik_codes)
        if not values:
            raise ValueError(
                f"Marketstack API error [missing_{config.fan_out_over}]: the '{endpoint}' table requires one or "
                f"more {'symbols' if config.fan_out_over == 'symbols' else 'CIK codes'}. Add them to the source "
                "configuration, then resync."
            )
        return _fan_out_source(access_key, config, values, resumable_source_manager, api_version)

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
            "base_url": marketstack_base_url(api_version),
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


def validate_credentials(access_key: str, api_version: str) -> bool:
    # `/exchanges` is a static reference endpoint available on every plan (including free) and needs
    # no symbols, so it's a cheap probe that the access key is genuine. It's served under both v1 and
    # v2, so the resolved source pin picks the base URL. A bad key can surface either as a non-200
    # status or as an HTTP 200 with a body-level error envelope, so both are checked.
    url = f"{marketstack_base_url(api_version)}/exchanges"
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
