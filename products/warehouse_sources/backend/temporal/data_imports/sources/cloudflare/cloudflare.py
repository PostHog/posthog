from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import CLOUDFLARE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

CLOUDFLARE_BASE_URL = "https://api.cloudflare.com/client/v4"
# Cloudflare list pages cap at 50 by default; most endpoints allow more.
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60
# 1200 req/5min global API rate limit; a 429 stays rate-limited until the window
# resets, so we honor the Retry-After header it carries instead of guessing.
MAX_RETRY_ATTEMPTS = 5
# Cap how long a single Retry-After can stall us, so a misbehaving header can't
# pin the activity open for the full 5-minute window times every attempt.
MAX_RETRY_AFTER_SECONDS = 120
# Stateless backoff used when a retryable error carries no Retry-After hint.
_FALLBACK_WAIT = wait_exponential_jitter(initial=1, max=60)
# A token can list zones (account-level Zone:Read) without holding DNS:Read on
# every one of them. Per-zone 403/404s mean "this zone is inaccessible/gone" —
# skip it and keep syncing the rest rather than failing the whole stream.
ZONE_SKIP_STATUS_CODES = frozenset({403, 404})


class CloudflareRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        # Seconds Cloudflare asked us to wait (from a 429 Retry-After), if any.
        self.retry_after = retry_after


def _parse_retry_after(response: requests.Response) -> float | None:
    """Cloudflare sends Retry-After as delta-seconds on 429s; ignore other forms."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, seconds)


def _wait_strategy(retry_state: RetryCallState) -> float:
    """Honor a 429's Retry-After when present, else fall back to jittered backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    if isinstance(exc, CloudflareRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
    return _FALLBACK_WAIT(retry_state)


def _get_session(api_token: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,))


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with Cloudflare's token verify endpoint."""
    try:
        response = _get_session(api_token).get(
            f"{CLOUDFLARE_BASE_URL}/user/tokens/verify",
            timeout=10,
        )
        return response.status_code == 200 and bool(response.json().get("success"))
    except Exception:
        return False


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = CLOUDFLARE_ENDPOINTS[endpoint]
    session = _get_session(api_token)

    @retry(
        retry=retry_if_exception_type((CloudflareRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=_wait_strategy,
        reraise=True,
    )
    def fetch(path: str, page: int) -> dict[str, Any]:
        url = f"{CLOUDFLARE_BASE_URL}{path}?{urlencode({'page': page, 'per_page': PAGE_SIZE})}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise CloudflareRetryableError(
                f"Cloudflare API error (retryable): status={response.status_code}, url={url}",
                retry_after=_parse_retry_after(response) if response.status_code == 429 else None,
            )

        if not response.ok:
            logger.error(f"Cloudflare API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    def iterate_pages(path: str) -> Iterator[list[dict[str, Any]]]:
        page = 1
        while True:
            body = fetch(path, page)
            items = body.get("result", []) or []
            if items:
                yield items
            total_pages = (body.get("result_info") or {}).get("total_pages")
            if not items or (isinstance(total_pages, int) and page >= total_pages):
                return
            if total_pages is None and len(items) < PAGE_SIZE:
                return
            page += 1

    if not config.zone_scoped:
        yield from iterate_pages(config.path)
        return

    assert config.parent_key is not None, (
        f"Zone-scoped endpoint '{endpoint}' must define parent_key in CLOUDFLARE_ENDPOINTS"
    )
    zone_ids = [zone["id"] for page in iterate_pages("/zones") for zone in page if zone.get("id")]
    for zone_id in zone_ids:
        path = config.path.replace("{zone_id}", quote(zone_id))
        try:
            for page_items in iterate_pages(path):
                yield [{**item, config.parent_key: zone_id} for item in page_items]
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code in ZONE_SKIP_STATUS_CODES:
                logger.warning(
                    f"Skipping Cloudflare zone {zone_id} for endpoint '{endpoint}': "
                    f"token lacks access (status={status_code})"
                )
                continue
            raise


def cloudflare_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = CLOUDFLARE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
