"""Mixmax REST transport.

Mixmax is a sales-engagement / email-productivity API served at https://api.mixmax.com/v1 with
`X-API-Token` header auth. List endpoints are cursor-paginated behind a `{results, next, hasNext,
previous, hasPrevious}` wrapper; `/…/me` endpoints return a single caller-scoped object with no
wrapper. Collections are returned newest-first (by creation time).

Incremental note: the API exposes no server-side timestamp filter (no `updated_after`/`since`), so
every endpoint is full-refresh only. A "client-side cursor walk" would still fetch every page each
run, so it buys nothing over full refresh and we don't advertise incremental for any table. We do
persist the pagination cursor between Temporal heartbeats (via `ResumableSourceManager`) so a sync
interrupted mid-pagination resumes from the last page rather than restarting the whole endpoint.

Rate limits: 120 requests / 60s per user+IP, `429` with `Retry-After`. The tracked session's default
`urllib3` retry already honors `Retry-After` and backs off on 429/5xx; the tenacity wrapper below adds
resilience for transient network failures and a few extra 429/5xx attempts.
"""

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
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.settings import (
    MIXMAX_ENDPOINTS,
    MixmaxEndpointConfig,
)

MIXMAX_BASE_URL = "https://api.mixmax.com/v1"
# Docs default the page size to 50 and cap it around 300; 100 keeps request volume low against the
# 120 req/min ceiling without risking a rejected oversized page.
PAGE_SIZE = 100


class MixmaxRetryableError(Exception):
    pass


@dataclasses.dataclass
class MixmaxResumeConfig:
    # Fully-built URL of the next page to fetch. None means "start at the endpoint's first page".
    next_url: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-Token": api_key,
        "Accept": "application/json",
    }


def _build_url(path: str, single_object: bool, next_cursor: str | None = None) -> str:
    """Build a Mixmax list URL. `/…/me` single-object endpoints take no pagination params."""
    if single_object:
        return f"{MIXMAX_BASE_URL}{path}"
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if next_cursor:
        # `next`/`previous` are documented as URL-safe strings, but urlencode keeps us correct
        # regardless of what the server hands back.
        params["next"] = next_cursor
    return f"{MIXMAX_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(api_key: str) -> bool:
    """Probe the cheapest always-available endpoint (`/users/me`) to confirm the token is genuine."""
    try:
        # redact_values masks the token in logged URLs and captured HTTP samples — the sampler's
        # name-based header denylist doesn't recognise `X-API-Token`.
        with make_tracked_session(redact_values=(api_key,)) as session:
            response = session.get(f"{MIXMAX_BASE_URL}/users/me", headers=_get_headers(api_key), timeout=10)
            return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            MixmaxRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise MixmaxRetryableError(f"Mixmax API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Mixmax API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_page(data: Any) -> tuple[list[dict], str | None]:
    """Return (rows, next_cursor) for a single response.

    List endpoints wrap rows in `{results: [...], next, hasNext}`. `/…/me` endpoints return the
    object directly (or, defensively, a bare list). Only the wrapped shape paginates.
    """
    if isinstance(data, dict) and "results" in data:
        rows = data.get("results") or []
        next_cursor = data.get("next") if data.get("hasNext") else None
        return rows, next_cursor
    if isinstance(data, list):
        return data, None
    # Single-object endpoint (e.g. /users/me): treat the whole body as one record.
    return [data], None


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MixmaxResumeConfig],
) -> Iterator[list[dict]]:
    config = MIXMAX_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"Mixmax: resuming {endpoint} from URL: {url}")
    else:
        url = _build_url(config.path, config.single_object)

    # redact_values masks the token in logged URLs and captured HTTP samples; the `with` block
    # closes the session's pooled connections once the generator is exhausted.
    with make_tracked_session(redact_values=(api_key,)) as session:
        while True:
            data = _fetch_page(session, url, headers, logger)
            rows, next_cursor = _extract_page(data)

            if rows:
                yield rows

            if not next_cursor:
                break

            next_url = _build_url(config.path, config.single_object, next_cursor)
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
            # dedupes the re-pulled rows on the primary key.
            resumable_source_manager.save_state(MixmaxResumeConfig(next_url=next_url))
            url = next_url


def mixmax_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MixmaxResumeConfig],
) -> SourceResponse:
    endpoint_config: MixmaxEndpointConfig = MIXMAX_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Collections arrive newest-first; declaring it honestly keeps full-refresh page ordering
        # transparent (no incremental watermark is derived for these tables).
        sort_mode="desc",
    )
