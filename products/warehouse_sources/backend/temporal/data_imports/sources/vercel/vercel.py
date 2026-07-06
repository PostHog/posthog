import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.settings import (
    VERCEL_ENDPOINTS,
    VercelEndpointConfig,
)

VERCEL_BASE_URL = "https://api.vercel.com"

# Vercel caps the page size at 100 (default 20); request the max to minimize round-trips.
PAGE_SIZE = 100

# Backstop against an endpoint that silently ignores the `until` cursor (which would otherwise
# re-serve page one forever). Resumable state means an interrupted sync picks back up, so this is
# a runaway guard, not a coverage limit — at 100 rows/page it allows ~1M rows before warning.
MAX_PAGES = 10_000


class VercelRetryableError(Exception):
    pass


@dataclasses.dataclass
class VercelResumeConfig:
    # The `until` pagination cursor (Unix ms) for the next page. None means "start at page one".
    # The `since` lower bound is reconstructed from db_incremental_field_last_value on resume, so
    # only the cursor needs persisting.
    until: int | None = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _build_params(
    config: VercelEndpointConfig,
    team_id: str | None,
    since_value: Any,
    until: int | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE}

    if config.team_scoped and team_id:
        params["teamId"] = team_id

    if config.since_param and since_value is not None:
        params[config.since_param] = since_value

    if until is not None:
        params["until"] = until

    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{VERCEL_BASE_URL}{path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((VercelRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # Vercel rate limits per-endpoint and returns 429 with a reset window; treat 429 and any 5xx
    # as transient and let tenacity back off. A bad/insufficient token (401/403) is raised below
    # via raise_for_status() and matched by get_non_retryable_errors() so the sync stops.
    if response.status_code == 429 or response.status_code >= 500:
        raise VercelRetryableError(f"Vercel API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Vercel API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _should_stop_desc(items: list[dict[str, Any]], field_name: str | None, cutoff: Any) -> bool:
    """For an incremental, newest-first endpoint, stop paginating once a page contains a row at or
    below the watermark. This is a client-side backstop: the `since` filter should already exclude
    older rows, but if Vercel silently ignored it the watermark check still terminates the walk and
    prevents re-fetching the full history every sync."""
    if not field_name or cutoff is None or not items:
        return False
    return any(item.get(field_name) is not None and item[field_name] <= cutoff for item in items)


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    """Confirm the access token is genuine via GET /v2/user — the cheapest authenticated probe,
    available to any valid Vercel token regardless of team scope or resource permissions."""
    try:
        response = make_tracked_session().get(
            f"{VERCEL_BASE_URL}/v2/user", headers=_get_headers(access_token), timeout=10
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid or unauthorized Vercel access token"
    return False, f"Vercel API error: {response.status_code}"


def get_rows(
    access_token: str,
    endpoint: str,
    team_id: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VercelResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = VERCEL_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    field_name = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
    # Only deployments has a documented server-side `since` filter; for everything else cutoff stays
    # None and we full-refresh the resource.
    cutoff = (
        db_incremental_field_last_value
        if (should_use_incremental_field and config.since_param and db_incremental_field_last_value is not None)
        else None
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    until = resume.until if resume else None
    if resume is not None:
        logger.debug(f"Vercel: resuming {endpoint} from until={until}")

    page_count = 0
    while True:
        url = _build_url(config.path, _build_params(config, team_id, cutoff, until))
        data = _fetch_page(session, url, headers, logger)

        items = data.get(config.response_data_key) or []
        if not items:
            break

        next_until = (data.get("pagination") or {}).get("next")
        stop_after_page = _should_stop_desc(items, field_name, cutoff)

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Checkpoint the cursor for the CURRENT page (not next_until): a yield can fire
                # mid-page, so the rest of this page may still be unprocessed. Saving next_until
                # here would advance the watermark past those rows and silently skip them on
                # resume. Re-fetching the current page instead re-yields its rows; the merge
                # dedupes on the primary key, so the already-yielded rows are harmless duplicates.
                if not stop_after_page:
                    resumable_source_manager.save_state(VercelResumeConfig(until=until))

        page_count += 1
        if stop_after_page or next_until is None:
            break
        # If the cursor doesn't advance, the endpoint is ignoring `until`; stop rather than loop
        # forever on page one.
        if next_until == until:
            logger.warning(f"Vercel: {endpoint} pagination cursor did not advance (until={until}); stopping")
            break
        if page_count >= MAX_PAGES:
            logger.warning(f"Vercel: {endpoint} hit MAX_PAGES={MAX_PAGES}; remaining pages skipped")
            break
        until = next_until

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def vercel_source(
    access_token: str,
    endpoint: str,
    team_id: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VercelResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = VERCEL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[endpoint_config.primary_key],
        # Vercel returns rows newest-first; the watermark must checkpoint as descending.
        sort_mode="desc",
    )
