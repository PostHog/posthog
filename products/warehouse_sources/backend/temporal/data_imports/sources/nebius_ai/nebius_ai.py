import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.settings import (
    FINE_TUNING_JOBS_PATH,
    NEBIUS_AI_ENDPOINTS,
    NebiusAIEndpointConfig,
)

# Token Factory rebrand of the former api.studio.nebius.ai host. OpenAI-compatible surface.
NEBIUS_AI_BASE_URL = "https://api.tokenfactory.nebius.com/v1"

# OpenAI-style `limit`. Nebius accepts up to 100 on the paginated list endpoints.
PAGE_SIZE = 100


class NebiusAIRetryableError(Exception):
    pass


class NebiusAIPaginationError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class NebiusAIResumeConfig:
    # OpenAI-style cursor: the id of the last object already yielded, sent as `after` to fetch the
    # next page. None starts the list from the beginning.
    after: str | None = None
    # Per-job child endpoints: the job whose children are read next, and the `after` cursor of the
    # fine-tuning job page that contains it.
    job_id: str | None = None
    jobs_after: str | None = None
    # `/operations`: ISO 8601 `cursor_time` for the next page.
    cursor_time: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    url = f"{NEBIUS_AI_BASE_URL}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # /models is the cheapest authenticated probe: every valid key can read it and it needs no params.
    # `redact_values` keeps the key out of captured request samples; redirects are pinned off so the
    # bearer token is never replayed to a host the probe did not validate against.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    try:
        response = session.get(f"{NEBIUS_AI_BASE_URL}/models", headers=_get_headers(api_key), timeout=10)
    except requests.RequestException as exc:
        # A timeout or connection blip is not a credential problem — never report it as an invalid key.
        return False, f"Could not reach Nebius AI: {exc}"

    if response.ok:
        return True, None

    if response.status_code == 401:
        return (
            False,
            "Your Nebius AI API key is invalid or has expired. Create a new key in the Nebius AI Studio console, then reconnect.",
        )

    if response.status_code == 403:
        return (
            False,
            "Your Nebius AI API key does not have the permissions needed to sync this data. Grant read access to the key, then reconnect.",
        )

    # 429/5xx and other unexpected statuses are transient; don't mislabel the key as invalid.
    return False, f"Nebius AI API returned status {response.status_code}, try reconnecting shortly."


@retry_with_deadline(
    # ChunkedEncodingError is a mid-stream connection break, transient like ConnectionError/ReadTimeout.
    retry=retry_if_exception_type(
        (
            NebiusAIRetryableError,
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

    # Nebius enforces per-plan rate limits with 429s; retry those and transient 5xx with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise NebiusAIRetryableError(f"Nebius AI API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Nebius AI API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _epoch_to_iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _get_operation_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: NebiusAIEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NebiusAIResumeConfig],
) -> Iterator[Any]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor_time = resume.cursor_time if resume else None
    previous_page_ids: set[str] = set()

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE, **config.params}
        if cursor_time:
            params["cursor_time"] = cursor_time

        data = _fetch_page(session, _build_url(config.path, params), headers, logger)
        items = data.get("data", [])
        # An inclusive cursor returns the boundary rows again.
        new_items = [item for item in items if item["id"] not in previous_page_ids]

        # The API does not document the order or whether `cursor_time` is inclusive. We assume
        # newest-first with the cursor as an upper bound. A full page whose cursor does not move
        # strictly back in time would loop or leave a gap, so fail instead of syncing a partial table.
        has_more = len(items) >= PAGE_SIZE
        next_cursor = _epoch_to_iso(items[-1]["created_at"]) if items else None
        if has_more and cursor_time is not None and next_cursor is not None and next_cursor >= cursor_time:
            raise NebiusAIPaginationError(
                f"Nebius AI {config.name}: cursor_time did not move back in time on a full page, cursor_time={cursor_time}, next_cursor={next_cursor}"
            )

        if has_more:
            resumable_source_manager.save_state(NebiusAIResumeConfig(cursor_time=next_cursor))

        if new_items:
            yield new_items
        else:
            resumable_source_manager.safe_point()

        if not has_more:
            break

        cursor_time = next_cursor
        previous_page_ids = {item["id"] for item in items}


def _get_job_child_pages(
    session: requests.Session,
    headers: dict[str, str],
    config: NebiusAIEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NebiusAIResumeConfig],
    job_id: str,
    after: str | None,
    jobs_after: str | None,
    position_after_job: NebiusAIResumeConfig | None,
) -> Iterator[Any]:
    path = config.path.format(job_id=quote(job_id, safe=""))

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE, **config.params}
        if after:
            params["after"] = after

        data = _fetch_page(session, _build_url(path, params), headers, logger)
        items = data.get("data", [])
        next_after = (data.get("last_id") or items[-1]["id"]) if items else None
        has_more = bool(items and data.get("has_more") and next_after)

        position = (
            NebiusAIResumeConfig(jobs_after=jobs_after, job_id=job_id, after=next_after)
            if has_more
            else position_after_job
        )
        if position is not None:
            resumable_source_manager.save_state(position)

        if items:
            # Events do not carry their job id, so add it for the composite primary key.
            for item in items:
                item.setdefault("fine_tuning_job_id", job_id)
            yield items
        else:
            resumable_source_manager.safe_point()

        if not has_more:
            return

        after = next_after


def _get_per_job_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: NebiusAIEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NebiusAIResumeConfig],
) -> Iterator[Any]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    jobs_after = resume.jobs_after if resume else None
    resume_job_id = resume.job_id if resume else None
    child_after = resume.after if resume else None

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if jobs_after:
            params["after"] = jobs_after

        jobs_page = _fetch_page(session, _build_url(FINE_TUNING_JOBS_PATH, params), headers, logger)
        job_ids = [job["id"] for job in jobs_page.get("data", [])]
        if not job_ids:
            break

        next_jobs_after = jobs_page.get("last_id") or job_ids[-1]
        has_more_jobs = bool(jobs_page.get("has_more"))

        start = 0
        if resume_job_id is not None:
            if resume_job_id in job_ids:
                start = job_ids.index(resume_job_id)
            else:
                # The job was deleted after the cursor was saved, so read its page from the start.
                child_after = None
            resume_job_id = None

        for index in range(start, len(job_ids)):
            if index + 1 < len(job_ids):
                position_after_job: NebiusAIResumeConfig | None = NebiusAIResumeConfig(
                    jobs_after=jobs_after, job_id=job_ids[index + 1]
                )
            elif has_more_jobs:
                position_after_job = NebiusAIResumeConfig(jobs_after=next_jobs_after)
            else:
                position_after_job = None

            yield from _get_job_child_pages(
                session,
                headers,
                config,
                logger,
                resumable_source_manager,
                job_id=job_ids[index],
                after=child_after,
                jobs_after=jobs_after,
                position_after_job=position_after_job,
            )
            child_after = None

        if not has_more_jobs:
            break

        jobs_after = next_jobs_after


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NebiusAIResumeConfig],
) -> Iterator[Any]:
    config = NEBIUS_AI_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive. `redact_values`
    # masks the key in captured samples; `allow_redirects=False` stops the bearer token being replayed
    # to an attacker-controlled host on a 30x.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)

    if config.per_fine_tuning_job:
        yield from _get_per_job_rows(session, headers, config, logger, resumable_source_manager)
        return

    if config.time_cursor_paginated:
        yield from _get_operation_rows(session, headers, config, logger, resumable_source_manager)
        return

    if not config.paginated:
        data = _fetch_page(session, _build_url(config.path, {}), headers, logger)
        items = data.get("data", [])
        if items:
            yield items
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after = resume.after if resume else None

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE, **config.params}
        if after:
            params["after"] = after

        data = _fetch_page(session, _build_url(config.path, params), headers, logger)
        items = data.get("data", [])
        if not items:
            break

        yield items

        # Prefer the server-provided cursor; fall back to the last row's id when the endpoint
        # omits `last_id` (some OpenAI-compatible list responses only return `has_more`). Index the
        # required primary key directly so any malformed final row — missing `id` or not even a
        # mapping — fails loudly instead of silently dropping every later page.
        last_id = data.get("last_id") or items[-1]["id"]
        if not data.get("has_more") or not last_id:
            break

        after = last_id
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; merge
        # dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(NebiusAIResumeConfig(after=after))


def nebius_ai_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NebiusAIResumeConfig],
) -> SourceResponse:
    config = NEBIUS_AI_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # These OpenAI-style list endpoints return newest-first. sort_mode is inert while every stream
        # is full-refresh (no incremental watermark), but declaring the true order keeps resume/
        # watermark semantics correct if a server-side time filter is ever added.
        sort_mode="desc",
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
