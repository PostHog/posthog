"""Recharge API client used by the data warehouse source.

Spec: https://developer.rechargepayments.com/2021-11 (API version 2021-11).

Recharge is a subscription-billing platform. The API is pure REST/JSON with
API-key auth (`X-Recharge-Access-Token`), cursor pagination, and server-side
timestamp filters (`updated_at_min` / `created_at_min`) for incremental syncs.

Everything here routes through ``make_tracked_session`` so outbound calls show
up in our HTTP logs, OTel metrics, and sample-capture pipeline.

NOTE: these endpoint params were taken from the public 2021-11 docs and could
not be curl-verified against a live store during implementation (no test
credentials). The pagination/filter handling is intentionally conservative —
see inline comments where behavior is assumed rather than confirmed.
"""

import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.settings import (
    RECHARGE_ENDPOINTS,
    RechargeEndpointConfig,
)

RECHARGE_BASE_URL = "https://api.rechargeapps.com"
RECHARGE_API_VERSION = "2021-11"
# Per-endpoint page size lives on each `RechargeEndpointConfig` (default 250,
# Recharge's max); see `settings.py` for why some endpoints request less.
REQUEST_TIMEOUT_SECONDS = 60


class RechargeRetryableError(Exception):
    pass


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


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-Recharge-Access-Token": api_key,
        "X-Recharge-Version": RECHARGE_API_VERSION,
        "Accept": "application/json",
    }


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


def _extract_items(payload: dict[str, Any], resource_key: str) -> list[dict[str, Any]]:
    """Pull the list of records out of a Recharge list response.

    Recharge wraps results under a key matching the resource (e.g.
    ``{"customers": [...], "next_cursor": "..."}``). Fall back to the first
    list-valued, non-cursor key if the resource key isn't present.
    """
    items = payload.get(resource_key)
    if isinstance(items, list):
        return items

    for key, value in payload.items():
        if key in ("next_cursor", "previous_cursor"):
            continue
        if isinstance(value, list):
            return value
    return []


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe ``/token_information`` — the cheapest call that confirms the token.

    Returns ``(ok, error)``. A 401 means the token is invalid; anything else
    reachable-and-2xx is treated as valid.
    """
    url = f"{RECHARGE_BASE_URL}/token_information"
    try:
        # `redact_values` masks the token wherever it appears in captured HTTP
        # samples — the `X-Recharge-Access-Token` header isn't in the shared
        # auth-header denylist, so without this the token would leak in plaintext.
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(api_key), timeout=10)
    except requests.RequestException as e:
        return False, f"Could not reach Recharge: {e}"

    if response.status_code == 401:
        return False, "Invalid Recharge API token. Please check the token and try again."
    if response.ok:
        return True, None
    return False, f"Recharge rejected the request (HTTP {response.status_code})."


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RechargeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = RECHARGE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: str | None = resume.cursor if resume is not None and resume.endpoint == endpoint else None

    @retry(
        retry=retry_if_exception_type((RechargeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(request_params: dict[str, Any]) -> dict[str, Any]:
        url = f"{RECHARGE_BASE_URL}{config.path}?{urlencode(request_params)}"
        # `redact_values` masks the token in captured HTTP samples (the custom
        # `X-Recharge-Access-Token` header isn't in the shared auth denylist).
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise RechargeRetryableError(
                f"Recharge API error (retryable): status={response.status_code}, endpoint={endpoint}"
            )

        if not response.ok:
            logger.error(
                f"Recharge API error: status={response.status_code}, body={response.text}, endpoint={endpoint}"
            )
            response.raise_for_status()

        return response.json()

    while True:
        # When following a cursor, Recharge only accepts `cursor` + `limit` —
        # the original sort/filters are baked into the cursor itself. Sending
        # them again returns a 422.
        request_params: dict[str, Any] = {"cursor": cursor, "limit": config.page_size} if cursor else params

        data = fetch_page(request_params)
        items = _extract_items(data, endpoint)

        if items:
            yield items

        next_cursor = data.get("next_cursor")
        if not next_cursor:
            break

        # Save state AFTER yielding so a crash re-yields the last page (merge
        # dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(RechargeResumeConfig(endpoint=endpoint, cursor=next_cursor))
        cursor = next_cursor


def recharge_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RechargeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = RECHARGE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
