import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.settings import (
    PAPERSIGN_ENDPOINTS,
    PapersignEndpointConfig,
)

# Papersign shares Paperform's single-host REST API. There is no per-account subdomain.
BASE_URL = "https://api.paperform.co/v1"

# `limit` is capped server-side at 100; the default is 20. We request the max to minimise round trips.
PAGE_SIZE = 100

REQUEST_TIMEOUT_SECONDS = 60


class PapersignRetryableError(Exception):
    pass


@dataclasses.dataclass
class PapersignResumeConfig:
    # The `skip` (offset) of the page we're currently streaming. We persist *this* page's offset
    # (not the next one) so a crash mid-page resumes by re-fetching the same page rather than
    # skipping past rows still buffered but not yet merged — merge dedupes the re-pulled rows on
    # the primary key. `0` means "start from the first page".
    skip: int = 0


def _get_session(api_token: str) -> requests.Session:
    # `redact_values` masks the bearer token in logged URLs and captured HTTP samples, so an
    # operator-enabled capture never persists a customer's API key.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        redact_values=(api_token,),
    )


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{BASE_URL}{path}"
    return f"{BASE_URL}{path}?{urlencode(params, doseq=True)}"


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the API token is genuine with one cheap, low-limit list request.

    Paperform issues a single account-wide token (no per-resource scopes), so probing any Papersign
    list endpoint is sufficient. A 401 means the token is wrong; a 403 means the token is valid but
    the plan doesn't include Papersign API access. Anything else reachable counts as valid.
    """
    url = _build_url("/papersign/spaces", {"limit": 1})
    try:
        response = _get_session(api_token).get(url, timeout=10)
    except Exception:
        return False, "Could not reach Paperform. Check your network and try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Paperform API key. Create a new key on your Paperform account page and reconnect."
    if response.status_code == 403:
        return (
            False,
            "This Paperform API key does not have Papersign API access. The Papersign API requires a paid "
            "Paperform plan — upgrade the plan, then reconnect.",
        )
    return False, f"Paperform API returned an unexpected status ({response.status_code}) while validating credentials."


@retry(
    retry=retry_if_exception_type((PapersignRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # Paperform is rate limited per minute and returns 429 with a Retry-After header when exceeded.
    # The exact threshold is undocumented, so we back off exponentially rather than trusting the
    # header. 5xx are transient too.
    if response.status_code == 429 or response.status_code >= 500:
        raise PapersignRetryableError(f"Paperform API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Paperform API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PapersignResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PAPERSIGN_ENDPOINTS[endpoint]
    # One session reused across every page so urllib3 keeps the connection alive.
    session = _get_session(api_token)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    skip: int = resume.skip if resume is not None else 0
    if resume is not None:
        logger.debug(f"Papersign: resuming {endpoint} from skip={skip}")

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE, "skip": skip}
        if config.supports_sort:
            # Ascending by created_at keeps offset pagination stable: rows created during the sync
            # append at the end rather than shifting the offsets of pages we've already read.
            params["sort"] = "ASC"

        data = _fetch_page(session, _build_url(config.path, params), logger)
        # Index strictly rather than `.get(..., [])`: `results` and its resource key are required
        # fields of the documented response. A malformed 200 (e.g. during an upstream incident) must
        # raise KeyError and fail the sync loudly, not silently yield zero rows — on a full-refresh
        # table that would replace all previously synced data with an empty table.
        rows = data["results"][config.results_key]
        if not rows:
            break

        yield rows
        # Save the offset of the page we just yielded (not the next one) AFTER yielding, so a crash
        # re-fetches this page rather than skipping rows still buffered. Merge dedupes on the
        # primary key.
        resumable_source_manager.save_state(PapersignResumeConfig(skip=skip))

        # `has_more` is the authoritative end-of-list signal. The short-page check is a defensive
        # backstop for the folders/spaces endpoints, whose pagination is undocumented: if one ignores
        # `skip` yet still reports `has_more=true`, a full-page loop could otherwise never terminate.
        # A page shorter than the limit is always the last one.
        if not data.get("has_more") or len(rows) < PAGE_SIZE:
            break
        skip += len(rows)


def papersign_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PapersignResumeConfig],
) -> SourceResponse:
    endpoint_config: PapersignEndpointConfig = PAPERSIGN_ENDPOINTS[endpoint]

    partition_kwargs: dict[str, Any] = {}
    if endpoint_config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [endpoint_config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Documents arrive ascending (we request `sort=ASC`); folders/spaces are small full scans.
        sort_mode="asc",
        **partition_kwargs,
    )
