import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.settings import (
    PARENT_TEAM_ID_FIELD,
    ZENDUTY_ENDPOINTS,
    ZendutyEndpointConfig,
)

ZENDUTY_BASE_URL = "https://www.zenduty.com"
REQUEST_TIMEOUT_SECONDS = 60


class ZendutyRetryableError(Exception):
    pass


@dataclasses.dataclass
class ZendutyResumeConfig:
    # The next page URL (DRF returns absolute `next` URLs that already carry the page cursor).
    next_url: str | None = None
    # For team-nested (fan-out) endpoints, the team whose child collection was in progress. On
    # resume we skip teams already fully walked and pick this one back up at `next_url`.
    team_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json",
    }


def _initial_url(path: str, page_size: int) -> str:
    # `page_size` only steers the first request; DRF may cap or ignore it, after which we simply
    # follow the server's `next` links.
    return f"{ZENDUTY_BASE_URL}{path}?{urlencode({'page_size': page_size})}"


def _ensure_zenduty_url(url: str) -> str:
    """Require an HTTPS www.zenduty.com URL. Every request carries the account API key, so a
    pagination `next` URL (or a poisoned resume checkpoint) pointing anywhere else would leak the
    key and let the worker be steered at arbitrary/internal hosts."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "www.zenduty.com":
        raise ValueError(f"Refusing non-Zenduty pagination URL: {url}")
    return url


def _extract_items_and_next(data: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Normalize a Zenduty list response into (rows, next_url).

    Zenduty is Django REST framework, so collections come back either as a page-number envelope
    (`{"count", "next", "previous", "results"}`) or, for smaller team-nested collections, as a bare
    JSON array. Handle both, plus a lone object, so a per-endpoint pagination difference can't drop rows.
    """
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)], None
    if isinstance(data, dict):
        if "results" in data:
            results = data.get("results") or []
            rows = [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []
            next_url = data.get("next")
            return rows, next_url if isinstance(next_url, str) else None
        # A single resource object (not expected for list routes, but keep it lossless).
        return [data], None
    return [], None


@retry(
    retry=retry_if_exception_type((ZendutyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    # Redirects are refused: following one off the validated origin would re-send the API key
    # to wherever the response points.
    response = session.get(
        _ensure_zenduty_url(url), headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False
    )

    if 300 <= response.status_code < 400:
        raise ValueError(
            f"Zenduty returned an unexpected redirect: status={response.status_code}, "
            f"location={response.headers.get('Location')}, url={url}"
        )

    # 429 (rate limited) and 5xx are transient; retry them.
    if response.status_code == 429 or response.status_code >= 500:
        raise ZendutyRetryableError(f"Zenduty API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Zenduty API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    try:
        return response.json()
    except ValueError:
        # A 2xx that isn't JSON (e.g. a WAF interstitial). Treat as transient rather than crashing
        # the sync on a body we can't parse.
        raise ZendutyRetryableError(f"Zenduty returned a non-JSON body: status={response.status_code}, url={url}")


def _with_team_id(row: dict[str, Any], team_id: str) -> dict[str, Any]:
    return {**row, PARENT_TEAM_ID_FIELD: team_id}


def _list_team_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger, page_size: int
) -> list[str]:
    """Enumerate every team's `unique_id` — the parents fan-out endpoints iterate over."""
    url: str | None = _initial_url(ZENDUTY_ENDPOINTS["teams"].path, page_size)
    team_ids: list[str] = []
    while url:
        data = _fetch_page(session, url, headers, logger)
        rows, next_url = _extract_items_and_next(data)
        for row in rows:
            unique_id = row.get("unique_id")
            if isinstance(unique_id, str) and unique_id:
                team_ids.append(unique_id)
        url = _ensure_zenduty_url(next_url) if next_url else None
    return team_ids


def _paginate_top_level(
    session: requests.Session,
    headers: dict[str, str],
    config: ZendutyEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendutyResumeConfig],
    resume: ZendutyResumeConfig | None,
    page_size: int,
) -> Iterator[list[dict[str, Any]]]:
    url = resume.next_url if (resume and resume.next_url) else _initial_url(config.path, page_size)
    while True:
        data = _fetch_page(session, url, headers, logger)
        rows, next_url = _extract_items_and_next(data)
        if rows:
            yield rows
        if not next_url:
            break
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key. Advance the URL before the next fetch to avoid re-looping it.
        # Validate before saving so an off-origin URL never lands in the resume checkpoint.
        resumable_source_manager.save_state(ZendutyResumeConfig(next_url=_ensure_zenduty_url(next_url)))
        url = next_url


def _paginate_fan_out(
    session: requests.Session,
    headers: dict[str, str],
    config: ZendutyEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendutyResumeConfig],
    resume: ZendutyResumeConfig | None,
    page_size: int,
) -> Iterator[list[dict[str, Any]]]:
    team_ids = _list_team_ids(session, headers, logger, page_size)
    if not team_ids:
        return

    start_index = 0
    resume_url: str | None = None
    if resume and resume.team_id and resume.team_id in team_ids:
        start_index = team_ids.index(resume.team_id)
        resume_url = resume.next_url

    for idx in range(start_index, len(team_ids)):
        team_id = team_ids[idx]
        url = (
            resume_url
            if (idx == start_index and resume_url)
            else _initial_url(config.path.format(team_id=team_id), page_size)
        )
        while True:
            data = _fetch_page(session, url, headers, logger)
            rows, next_url = _extract_items_and_next(data)
            if rows:
                yield [_with_team_id(row, team_id) for row in rows]
            if next_url:
                resumable_source_manager.save_state(
                    ZendutyResumeConfig(next_url=_ensure_zenduty_url(next_url), team_id=team_id)
                )
                url = next_url
                continue
            # Team done — checkpoint at the next team's start so a resume skips completed teams
            # instead of re-walking them.
            if idx + 1 < len(team_ids):
                resumable_source_manager.save_state(ZendutyResumeConfig(next_url=None, team_id=team_ids[idx + 1]))
            break


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendutyResumeConfig],
    page_size: int = 100,
) -> Iterator[list[dict[str, Any]]]:
    config = ZENDUTY_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across pages so urllib3 keeps the connection alive.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.team_nested:
        yield from _paginate_fan_out(session, headers, config, logger, resumable_source_manager, resume, page_size)
    else:
        yield from _paginate_top_level(session, headers, config, logger, resumable_source_manager, resume, page_size)


def zenduty_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendutyResumeConfig],
    page_size: int = 100,
) -> SourceResponse:
    config = ZENDUTY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            page_size=page_size,
        ),
        primary_keys=config.primary_keys,
        # No partitioning: Zenduty's per-resource creation-timestamp field names aren't verified
        # against a live account, and partitioning on an absent field fails the sync. Partitioning
        # can be added later once the stable creation-date column is confirmed per endpoint.
    )


def probe_credentials(api_key: str) -> int | None:
    """Cheap probe of the account teams collection. Returns the HTTP status code, or None on a
    connection failure. Zenduty returns 403 with `{"error": "Invalid or Inactive Token"}` for a bad
    token (there is no 401), and 200 for a valid one."""
    url = _initial_url(ZENDUTY_ENDPOINTS["teams"].path, page_size=1)
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return None
    return response.status_code
