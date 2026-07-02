import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import COINGECKO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Two distinct hosts: the free Demo plan (and keyless public access) live on api.coingecko.com,
# paid Pro plans on pro-api.coingecko.com. The plan also selects which API-key header to send.
DEMO_BASE_URL = "https://api.coingecko.com/api/v3"
PRO_BASE_URL = "https://pro-api.coingecko.com/api/v3"

PLAN_DEMO = "demo"
PLAN_PRO = "pro"

# /coins/markets allows up to 250 per page; other paginated endpoints accept it too.
PAGE_SIZE = 250
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 6


class CoinGeckoRetryableError(Exception):
    pass


@dataclasses.dataclass
class CoinGeckoResumeConfig:
    # Next page to fetch for paginated endpoints. Unused for single-response reference endpoints.
    page: int = 1


def _base_url(plan: str) -> str:
    return PRO_BASE_URL if plan == PLAN_PRO else DEMO_BASE_URL


def _headers(plan: str, api_key: str) -> dict[str, str]:
    header_name = "x-cg-pro-api-key" if plan == PLAN_PRO else "x-cg-demo-api-key"
    headers = {"Accept": "application/json"}
    if api_key:
        headers[header_name] = api_key
    return headers


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


def _is_rate_limited(response: requests.Response) -> bool:
    """CoinGecko signals rate limiting both via a 429 status and, on the keyless/demo tier, via a
    200/4xx body carrying ``{"status": {"error_code": 429}}``. Treat both as retryable."""
    if response.status_code == 429:
        return True
    try:
        body = response.json()
    except ValueError:
        return False
    if isinstance(body, dict):
        status = body.get("status")
        if isinstance(status, dict) and status.get("error_code") == 429:
            return True
    return False


def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if _is_rate_limited(response) or response.status_code >= 500:
        raise CoinGeckoRetryableError(f"CoinGecko API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"CoinGecko API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(plan: str, api_key: str) -> bool:
    """Confirm the key is genuine by pinging with the plan's auth header. A valid key returns 200;
    an invalid one returns 401."""
    url = f"{_base_url(plan)}/ping"
    try:
        session = make_tracked_session(redact_values=(api_key,) if api_key else ())
        response = session.get(url, headers=_headers(plan, api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    plan: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinGeckoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = COINGECKO_ENDPOINTS[endpoint]
    session = make_tracked_session(redact_values=(api_key,) if api_key else ())
    headers = _headers(plan, api_key)
    base_url = _base_url(plan)

    @retry(
        retry=retry_if_exception_type((CoinGeckoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def fetch(url: str) -> Any:
        return _fetch(session, url, headers, logger)

    if not config.paginated:
        data = fetch(_build_url(base_url, config.path, dict(config.extra_params)))
        if isinstance(data, list) and data:
            yield data
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 1
    if resume is not None:
        logger.debug(f"CoinGecko: resuming {endpoint} from page {page}")

    while True:
        params: dict[str, Any] = {**config.extra_params, "per_page": PAGE_SIZE, "page": page}
        data = fetch(_build_url(base_url, config.path, params))

        # An empty list means we've paged past the end of the collection.
        if not isinstance(data, list) or not data:
            break

        yield data

        # A short page is the last page; stop without an extra empty request.
        if len(data) < PAGE_SIZE:
            break

        page += 1
        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the primary key)
        # rather than skipping it.
        resumable_source_manager.save_state(CoinGeckoResumeConfig(page=page))


def coingecko_source(
    plan: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinGeckoResumeConfig],
) -> SourceResponse:
    config = COINGECKO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            plan=plan,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # Snapshot/reference endpoints expose no stable created_at, so there's nothing to partition on.
        partition_count=None,
        partition_size=None,
    )
