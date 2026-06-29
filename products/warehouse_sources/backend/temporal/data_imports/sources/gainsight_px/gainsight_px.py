from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import (
    GAINSIGHT_PX_ENDPOINTS,
)

# Gainsight PX is a global, region-pinned service (not a per-tenant subdomain). The region is fixed by
# where the customer's PX instance lives; it maps to one of these hosts. Verified against
# https://px-apidocs.gainsight.com and the open-source Airbyte connector (url_base api.aptrinsic.com).
REGION_HOSTS = {
    "us": "https://api.aptrinsic.com/v1",
    "eu": "https://api-eu.aptrinsic.com/v1",
    "us2": "https://api-us2.aptrinsic.com/v1",
}

# PX authenticates with a static API key passed in this custom header (not Authorization: Bearer).
API_KEY_HEADER = "X-APTRINSIC-API-KEY"

# PX caps pageSize at 1000; 500 balances throughput against per-page memory.
PAGE_SIZE = 500

# Pure runaway guard for a cursor that never advances (e.g. an API that ignores `scrollId` and re-serves
# a full page forever). Set far above any realistic PX entity count so it never truncates real data; a
# hit is logged loudly rather than silently capping the sync.
_MAX_PAGES = 20_000


class GainsightPxRetryableError(Exception):
    pass


def _base_url(region: str) -> str:
    return REGION_HOSTS.get(region, REGION_HOSTS["us"])


def _headers(api_key: str) -> dict[str, str]:
    return {API_KEY_HEADER: api_key, "Accept": "application/json"}


def _extract_records(payload: Any, data_key: str, logger: FilteringBoundLogger | None = None) -> list[dict[str, Any]]:
    """Pull the record list out of a PX list response.

    Happy path: ``payload[data_key]`` — the per-endpoint record key, verified against the production
    Airbyte connector. Safety net for a response-shape change we can't live-test without an API key:
    if that key is absent, fall back to the body's sole list-of-objects field so a renamed key
    self-heals (with a warning) instead of silently yielding zero rows.
    """
    if not isinstance(payload, dict):
        return []
    records = payload.get(data_key)
    if isinstance(records, list):
        return records
    candidates = [
        v for v in payload.values() if isinstance(v, list) and v and all(isinstance(item, dict) for item in v)
    ]
    if len(candidates) == 1:
        if logger is not None:
            logger.warning(
                f"Gainsight PX: record key '{data_key}' not in response (keys: {list(payload)}); "
                f"falling back to the sole list field — the API response shape may have changed."
            )
        return candidates[0]
    return []


def _scroll_id(payload: Any) -> str | None:
    return payload.get("scrollId") if isinstance(payload, dict) else None


def _check_response(response: requests.Response, url: str, logger: FilteringBoundLogger) -> requests.Response:
    """Classify a response: raise retryable on 429/5xx, raise HTTPError on other 4xx, else pass through."""
    if response.status_code == 429 or response.status_code >= 500:
        raise GainsightPxRetryableError(f"Gainsight PX API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Gainsight PX API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


@retry(
    retry=retry_if_exception_type((GainsightPxRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Any:
    response = session.get(url, headers=headers, params=params, timeout=60)
    return _check_response(response, url, logger).json()


def validate_credentials(region: str, api_key: str) -> bool:
    """One cheap probe against `/accounts` to confirm the key authenticates for this region."""
    url = f"{_base_url(region)}/accounts"
    # `redact_values` masks the API key in the tracked transport's logs and sample capture — the custom
    # `X-APTRINSIC-API-KEY` header isn't on the name-based denylist, so value-based masking is required.
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            url, headers=_headers(api_key), params={"pageSize": 1}, timeout=10
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def get_rows(
    region: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = GAINSIGHT_PX_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive between requests.
    # `redact_values` masks the API key in tracked logs / sample capture (custom auth header).
    session = make_tracked_session(redact_values=(api_key,))
    url = f"{_base_url(region)}{config.path}"

    scroll_id: str | None = None
    page = 0
    while True:
        params: dict[str, Any] = {"pageSize": PAGE_SIZE}
        if scroll_id:
            params["scrollId"] = scroll_id

        payload = _fetch_page(session, url, headers, params, logger)
        records = _extract_records(payload, config.data_key, logger)
        if records:
            yield records

        page += 1
        scroll_id = _scroll_id(payload)

        # PX signals the last page by returning fewer rows than requested — it does NOT reliably clear
        # `scrollId` on the final page, so the short-page check (not a null cursor) is the real terminator.
        if len(records) < PAGE_SIZE or not scroll_id:
            break

        if page >= _MAX_PAGES:
            logger.error(
                f"Gainsight PX: hit the {_MAX_PAGES}-page safety cap on '{endpoint}' without the cursor "
                f"terminating; stopping to avoid an unbounded scan. Data may be incomplete."
            )
            break


def gainsight_px_source(
    region: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = GAINSIGHT_PX_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(region=region, api_key=api_key, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
    )
