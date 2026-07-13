"""openFDA (U.S. Food and Drug Administration) REST API transport.

openFDA (https://api.fda.gov) is the FDA's free public API over drug, device, and food regulatory
datasets (adverse events, recalls/enforcement reports, drug labeling, 510(k) clearances, the NDC
directory). Every dataset is its own endpoint with its own schema and date field; responses wrap the
records in `{"meta": ..., "results": [...]}`.

Pagination is a `search_after` cursor exposed via the HTTP `Link: rel="next"` header (the `skip`
offset param is capped at 25,000, so the cursor is the only way to walk a large dataset). Each next
URL is absolute and pre-encoded, so we follow it verbatim and it preserves the original `search`
(date filter) and `sort` params — which lets an incremental sync stay server-side-bounded on every
page. A single page has no next link once the results are exhausted, which is the loop terminator.

Incremental sync uses the endpoint's date field: `search=<field>:[<watermark> TO 99991231]` with
`sort=<field>:asc`. openFDA date fields are `YYYYMMDD` (a few, like `decision_date`, arrive dashed,
but the API accepts `YYYYMMDD` in the search filter uniformly), and the range is inclusive on both
ends, so we re-request the watermark day each run and let the delta merge dedupe on the primary key.

Auth is an optional free API key. Without one, openFDA throttles to 240 req/min and 1,000 req/day
per IP; with one, 240 req/min and 120,000 req/day per key. The key is sent as the HTTP Basic auth
username (openFDA's documented header method) so it never lands in a logged URL or in the saved
cursor state.

An empty result set surfaces as HTTP 404 with `{"error": {"code": "NOT_FOUND"}}`, not an empty
`results` array — so a 404 is treated as "no matching records" and ends the sync cleanly (common on
an up-to-date incremental run whose watermark is already at the latest record).
"""

import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from requests.auth import HTTPBasicAuth
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.settings import (
    OPENFDA_ENDPOINTS,
    OpenFDAEndpointConfig,
)

OPENFDA_BASE_URL = "https://api.fda.gov"
_OPENFDA_HOST = "api.fda.gov"

# openFDA caps a single search request at 1,000 results; larger values 400.
PAGE_SIZE = 1000

# Inclusive upper bound for the incremental date-range filter — effectively "no ceiling".
_MAX_DATE = "99991231"


class OpenFDARetryableError(Exception):
    pass


@dataclasses.dataclass
class OpenFDAResumeConfig:
    # Absolute, pre-encoded `Link: rel="next"` URL to fetch next. None means "start from the first
    # page" (the initial URL is rebuilt from the endpoint config + watermark).
    next_url: str | None = None


def _is_valid_openfda_url(url: str) -> bool:
    """Only absolute `https://api.fda.gov/...` URLs may be followed. A pagination cursor comes from a
    `Link` header or from resumed state — both are attacker-influenceable, and following one off-host
    would leak the API key (sent as Basic auth) or hit an internal address."""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == _OPENFDA_HOST


def _get_headers() -> dict[str, str]:
    return {"Accept": "application/json", "User-Agent": "PostHog-DataWarehouse"}


def _format_date_value(value: Any) -> str:
    """Format an incremental watermark as the `YYYYMMDD` openFDA expects in a search date range."""
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    # A raw string watermark (e.g. "20200101" or "2020-01-01"): strip separators to YYYYMMDD.
    return str(value).replace("-", "")[:8]


def _build_initial_url(
    config: OpenFDAEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> str:
    params: dict[str, Any] = {"limit": PAGE_SIZE}

    field = incremental_field or config.incremental_field
    if field is not None:
        # Sort ascending on the date field so the pipeline's watermark advances monotonically as we
        # page (sort_mode="asc"). Full-refresh endpoints have no date field and page on the cursor's
        # internal ordering without a sort.
        params["sort"] = f"{field}:asc"

        if should_use_incremental_field and db_incremental_field_last_value is not None:
            low = _format_date_value(db_incremental_field_last_value)
            params["search"] = f"{field}:[{low} TO {_MAX_DATE}]"

    return f"{OPENFDA_BASE_URL}{config.path}?{urlencode(params)}"


@retry(
    # ChunkedEncodingError is a mid-stream connection break; transient like ConnectionError/ReadTimeout.
    retry=retry_if_exception_type(
        (
            OpenFDARetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    auth: HTTPBasicAuth | None,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], str | None] | None:
    """Fetch one page. Returns (results, next_url), or None when openFDA reports no matching records."""
    response = session.get(url, headers=_get_headers(), auth=auth, timeout=60)

    # openFDA signals "no matching records" with a 404, not an empty results array. That's an expected
    # terminal state (e.g. an incremental run already caught up), so end the sync rather than error.
    if response.status_code == 404:
        logger.debug(f"openFDA: no matching records (404), url={url}")
        return None

    # 429 (rate limited) and 5xx are transient — back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise OpenFDARetryableError(f"openFDA API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"openFDA API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    body = response.json()
    # openFDA guarantees `results` on every 200 (empty sets come back as a 404, handled above), so
    # access it directly — a missing key means an unexpected response shape we want to surface, not
    # silently treat as an empty page.
    results = body["results"]
    # `Link: rel="next"` carries the search_after cursor; absent once the dataset is exhausted.
    next_url = response.links.get("next", {}).get("url")
    if next_url is not None and not _is_valid_openfda_url(next_url):
        # A poisoned `Link` header pointing off-host would leak the API key (sent as Basic auth) to
        # another server or fetch an internal URL — refuse to follow it.
        raise ValueError(f"openFDA returned an off-host pagination URL, refusing to follow: {next_url}")
    return results, next_url


def validate_credentials(api_key: str | None) -> bool:
    # A single cheap probe of the drug enforcement endpoint confirms reachability and (if provided)
    # that the key is accepted. openFDA allows unauthenticated access, so a blank key is still valid —
    # it just gets the lower rate-limit tier.
    url = f"{OPENFDA_BASE_URL}/drug/enforcement.json?{urlencode({'limit': 1})}"
    try:
        session = make_tracked_session(
            redact_values=(api_key,) if api_key else (),
            allow_redirects=False,
            # Disable urllib3 adapter retries — a slow/unreachable endpoint shouldn't hang the
            # connect-time UI probe for minutes.
            retry=Retry(total=0),
        )
        response = session.get(url, headers=_get_headers(), auth=_make_auth(api_key), timeout=30)
        return response.status_code == 200
    except Exception:
        return False


def _make_auth(api_key: str | None) -> HTTPBasicAuth | None:
    # openFDA accepts the API key as the HTTP Basic auth username (empty password). Sending it in the
    # header keeps it out of logged URLs and out of the saved cursor state.
    return HTTPBasicAuth(api_key, "") if api_key else None


def get_rows(
    api_key: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenFDAResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = OPENFDA_ENDPOINTS[endpoint]
    auth = _make_auth(api_key)
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request. `redact_values` scrubs the key from logged URLs/samples;
    # `allow_redirects=False` stops a 30x from forwarding the credential off-host.
    session = make_tracked_session(
        redact_values=(api_key,) if api_key else (),
        allow_redirects=False,
        # `_fetch_page` already retries 429/5xx and connection errors via tenacity, so disable the
        # urllib3 adapter retries — otherwise the two layers stack and multiply the backoff.
        retry=Retry(total=0),
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        if not _is_valid_openfda_url(resume.next_url):
            # Poisoned resume state must not be followed — see `_is_valid_openfda_url`.
            raise ValueError(f"openFDA resume cursor is not a valid api.fda.gov URL: {resume.next_url}")
        url: str | None = resume.next_url
        logger.debug(f"openFDA: resuming {endpoint} from cursor")
    else:
        url = _build_initial_url(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )

    while url is not None:
        page = _fetch_page(session, url, auth, logger)
        if page is None:
            break

        results, next_url = page
        if results:
            yield results

        if not next_url:
            break

        # Save AFTER yielding (the pipeline has persisted the page by the time it asks for the next
        # item) so a crash re-fetches the just-yielded page rather than skipping it; merge dedupes the
        # re-pulled rows on the primary key.
        resumable_source_manager.save_state(OpenFDAResumeConfig(next_url=next_url))
        url = next_url


def openfda_source(
    api_key: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenFDAResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = OPENFDA_ENDPOINTS[endpoint]

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
        primary_keys=config.primary_keys,
        # Incremental endpoints request sort=<field>:asc so rows arrive oldest-first and the watermark
        # advances safely after each batch. Full-refresh endpoints add no sort (they page on the bare
        # cursor), so their arrival order is undefined — don't claim "asc" for them.
        sort_mode="asc" if config.incremental_field else None,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
