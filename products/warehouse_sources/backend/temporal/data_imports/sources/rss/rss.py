import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.rss.settings import RSS_ENDPOINTS

RSS_BASE_URL = "https://api.rss.com/v4"
# The episodes endpoint accepts a `limit` of up to 100 (default 100); the largest page minimises
# round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every endpoint.
DEFAULT_PROBE_PATH = "/podcasts"


class RssRetryableError(Exception):
    pass


@dataclasses.dataclass
class RssResumeConfig:
    """Resume state for the per-podcast episodes fan-out.

    `podcasts` and `categories` are single unpaginated requests, so only the episodes endpoint
    persists state: which podcasts are fully synced and the next page of the podcast in flight.
    Page-number pagination with `order=oldest` is deterministic, so a crashed sync resumes from the
    page after the last one yielded; merge dedupes re-pulled rows on the primary key.
    """

    completed_podcast_ids: list[int] = dataclasses.field(default_factory=list)
    current_podcast_id: int | None = None
    next_page: int = 1


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((RssRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_list(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = session.get(
        f"{RSS_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise RssRetryableError(f"RSS.com API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"RSS.com API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Every RSS.com list endpoint returns a bare JSON array of objects.
    if not isinstance(data, list):
        raise RssRetryableError(f"RSS.com returned an unexpected payload for {path}: {type(data).__name__}")

    return data


def _get_episode_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RssResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = RSS_ENDPOINTS["episodes"]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed = set(resume.completed_podcast_ids) if resume else set()
    if resume:
        logger.debug(f"RSS.com: resuming episodes fan-out, {len(completed)} podcasts already synced")

    podcasts = _fetch_list(session, RSS_ENDPOINTS["podcasts"].path, {}, logger)

    for podcast in podcasts:
        podcast_id = podcast["id"]
        if podcast_id in completed:
            continue

        page = resume.next_page if resume is not None and resume.current_podcast_id == podcast_id else 1
        path = config.path.format(podcast_id=podcast_id)

        while True:
            # `order=oldest` gives stable append-only ordering: episodes published mid-sync land on
            # the final pages instead of shifting every earlier page boundary by one.
            items = _fetch_list(session, path, {"page": page, "limit": PAGE_SIZE, "order": "oldest"}, logger)
            if items:
                # Episode rows don't carry their parent id, so inject it — it is part of the primary
                # key and what users join back to the podcasts table on.
                yield [{**item, "podcast_id": podcast_id} for item in items]

            # A short or empty page marks the end of this podcast's episodes.
            if len(items) < PAGE_SIZE:
                break

            page += 1
            # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages
            # are persisted); merge dedupes the re-pulled page on the primary key.
            resumable_source_manager.save_state(
                RssResumeConfig(
                    completed_podcast_ids=sorted(completed),
                    current_podcast_id=podcast_id,
                    next_page=page,
                )
            )

        completed.add(podcast_id)
        resumable_source_manager.save_state(RssResumeConfig(completed_podcast_ids=sorted(completed)))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RssResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = RSS_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    if config.fan_out_podcasts:
        yield from _get_episode_rows(session, logger, resumable_source_manager)
        return

    # podcasts / categories: a single unpaginated request returns the whole collection.
    items = _fetch_list(session, config.path, {}, logger)
    if items:
        yield items


def rss_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RssResumeConfig],
) -> SourceResponse:
    config = RSS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``402``/``403`` auth or plan failure,
    ``0`` for a connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{RSS_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to RSS.com: {e}"

    if response.status_code in (401, 402, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"RSS.com returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid RSS.com API key"
    if status == 402:
        return False, "The RSS.com API is only available on RSS.com Network plans. Upgrade your plan, then reconnect."
    return False, message or "Could not validate RSS.com API key"
