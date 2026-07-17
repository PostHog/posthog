import time
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.settings import (
    TMDB_ENDPOINTS,
    TMDbEndpointConfig,
)

TMDB_BASE_URL = "https://api.themoviedb.org/3"

# TMDB list endpoints (popular/top_rated/...) and /discover are hard-capped at 500 pages server-side,
# so there's no point requesting beyond that — it 422s.
MAX_PAGES = 500

# TMDB disabled its documented 40 req / 10s limit in 2019 but enforces an undocumented upper bound
# (~50 req/s) to deter bulk scraping, blocking abusive IPs. A small inter-request delay keeps us well
# under that ceiling. Patched to 0 in tests.
THROTTLE_SECONDS = 0.05


class TMDbRetryableError(Exception):
    pass


@dataclasses.dataclass
class TMDbResumeConfig:
    # Next page number to fetch. Page-number pagination means a single integer is enough to resume.
    next_page: int


def _get_headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def _build_url(path: str, api_key: str, page: int | None = None) -> str:
    params: dict[str, Any] = {"api_key": api_key}
    if page is not None:
        params["page"] = page
        params["language"] = "en-US"
    return f"{TMDB_BASE_URL}{path}?{urlencode(params)}"


def _scrub_url(url: str | None) -> str:
    # The api_key rides in the query string, so strip the query before the URL reaches any error
    # message or log line — otherwise a non-2xx response would leak the credential into job errors.
    if not url:
        return TMDB_BASE_URL
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _do_fetch(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict | list:
    response = session.get(url, headers=_get_headers(), timeout=60)

    # 429 carries a Retry-After header; tenacity's backoff handles the wait deterministically.
    if response.status_code == 429 or response.status_code >= 500:
        raise TMDbRetryableError(f"TMDB API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"TMDB API error: status={response.status_code}, body={response.text}")
        # Raise with the api_key scrubbed from the URL rather than calling raise_for_status(), whose
        # message embeds the full credential-bearing URL. The base host stays intact so
        # `get_non_retryable_errors()` can still match on it.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {_scrub_url(response.url)}",
            response=response,
        )

    return response.json()


# Wrap the bare fetch in tenacity retries. Kept as a separate assignment (rather than a decorator) so
# tests can exercise the status-code classification in `_do_fetch` without driving the backoff loop.
_fetch = retry(
    retry=retry_if_exception_type((TMDbRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)(_do_fetch)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # /configuration is a cheap call that 200s for any valid key and 401s for an invalid one. Only a
    # 401 means the key is wrong — a transient failure (5xx, network error, timeout) must not be
    # reported as an invalid key, or a user with a perfectly valid key during a brief TMDB outage
    # would be told to regenerate it.
    url = _build_url("/configuration", api_key)
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(), timeout=10)
    except Exception:
        return False, "Could not reach TMDB to validate your API key. Check your connection and try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid TMDB API key"
    return (
        False,
        f"TMDB returned an unexpected response (status {response.status_code}) while validating your API key. Please try again.",
    )


def _extract_rows(data: dict | list, config: TMDbEndpointConfig) -> list[dict]:
    if config.data_key is None:
        # Bare-list endpoints (languages, countries).
        return data if isinstance(data, list) else []
    if isinstance(data, dict):
        rows = data.get(config.data_key, [])
        return rows if isinstance(rows, list) else []
    return []


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TMDbResumeConfig],
) -> Iterator[list[dict]]:
    config = TMDB_ENDPOINTS[endpoint]
    # One session reused across pages so urllib3 keeps the connection alive. The api_key lives in the
    # query string, so redact it from logged URLs and captured samples.
    session = make_tracked_session(redact_values=(api_key,))

    if not config.paginated:
        data = _fetch(session, _build_url(config.path, api_key), logger)
        rows = _extract_rows(data, config)
        if rows:
            yield rows
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1

    while page <= MAX_PAGES:
        data = _fetch(session, _build_url(config.path, api_key, page=page), logger)
        rows = _extract_rows(data, config)
        if rows:
            yield rows

        total_pages = data.get("total_pages", 0) if isinstance(data, dict) else 0
        if page >= total_pages:
            break

        next_page = page + 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key.
        resumable_source_manager.save_state(TMDbResumeConfig(next_page=next_page))
        page = next_page

        if THROTTLE_SECONDS:
            time.sleep(THROTTLE_SECONDS)


def tmdb_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TMDbResumeConfig],
) -> SourceResponse:
    endpoint_config = TMDB_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Full refresh (replace) on small, bounded ranking/reference datasets whose date fields can be
        # empty, so datetime partitioning isn't worthwhile here.
        partition_count=1,
        partition_size=1,
    )
