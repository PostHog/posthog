import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner.settings import (
    LINKRUNNER_ENDPOINTS,
    LinkrunnerEndpointConfig,
)

LINKRUNNER_BASE_URL = "https://api.linkrunner.io/api/v1"

# Default wait when a 429 arrives without a usable Retry-After header. The reporting API documents a
# 1 request/minute limit with Retry-After: 60, so 60s is the safe fallback.
_DEFAULT_RETRY_AFTER_SECONDS = 60


class LinkrunnerRetryableError(Exception):
    pass


class LinkrunnerRateLimitError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Linkrunner rate limit hit; retry after {retry_after}s")
        self.retry_after = retry_after


@dataclasses.dataclass
class LinkrunnerResumeConfig:
    # Next page (1-indexed) to fetch for the current resource / campaign.
    page: int = 1
    # Fan-out bookmark: the campaign display_id currently being paged. None for top-level endpoints.
    campaign_display_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {"linkrunner-key": api_key, "Accept": "application/json"}


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor value as ISO 8601 UTC with a `Z` suffix.

    Linkrunner documents ISO 8601 timestamps in UTC by default. The cursor comes back as a
    datetime, date, or already-formatted string depending on how it was stored.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _parse_retry_after(response: "requests.Response") -> int:
    raw = response.headers.get("Retry-After")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_RETRY_AFTER_SECONDS


def _has_next_page(page: int, total_pages: Any, num_items: int, limit: int) -> bool:
    """Decide whether to fetch another page.

    Prefer the server's reported page count; fall back to "a full page implies more" when the
    pagination block is missing, and always stop on an empty page.
    """
    if num_items == 0:
        return False
    if isinstance(total_pages, int):
        return page < total_pages
    return num_items >= limit


def _wait_for_retry(retry_state: RetryCallState) -> float:
    """Respect the API's Retry-After on rate limits; otherwise exponential backoff with jitter."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, LinkrunnerRateLimitError):
        return float(exc.retry_after)
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


@retry(
    retry=retry_if_exception_type(
        (
            LinkrunnerRetryableError,
            LinkrunnerRateLimitError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(8),
    wait=_wait_for_retry,
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    headers: dict[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Optional[dict]:
    """Fetch one page. Returns the parsed body, or None when the API replies 204 No Content."""
    response = session.get(f"{LINKRUNNER_BASE_URL}{path}", headers=headers, params=params, timeout=60)

    # Several Linkrunner endpoints return 204 with an empty body when there's no data to return.
    if response.status_code == 204:
        return None

    if response.status_code == 429:
        retry_after = _parse_retry_after(response)
        logger.warning(f"Linkrunner rate limit hit on {path}; retrying after {retry_after}s")
        raise LinkrunnerRateLimitError(retry_after)

    if response.status_code >= 500:
        raise LinkrunnerRetryableError(f"Linkrunner API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Linkrunner API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{LINKRUNNER_BASE_URL}/campaigns", headers=_get_headers(api_key), params={"limit": 1}, timeout=10
        )
        return response.status_code in (200, 204)
    except Exception:
        return False


def _flatten_attributed_user(item: dict[str, Any]) -> dict[str, Any]:
    """Promote the nested `user_data` object to top-level `user_*` columns.

    `user_id` becomes a first-class column so it can be part of the primary key; the richer
    `device_data` object is kept nested under the row.
    """
    row = dict(item)
    user_data = row.pop("user_data", None)
    if isinstance(user_data, dict):
        # `user_id` is part of the primary key, so index directly: a missing id must fail loudly
        # rather than write None and seed a phantom, non-deduping row.
        row["user_id"] = user_data["id"]
        row["user_name"] = user_data.get("name")
        row["user_email"] = user_data.get("email")
        row["user_phone"] = user_data.get("phone")
        row["device_data"] = user_data.get("device_data")
    return row


def _iter_campaign_display_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    """Page through /campaigns and yield each campaign's display_id (used to seed the fan-out)."""
    config = LINKRUNNER_ENDPOINTS["campaigns"]
    page = 1
    while True:
        data = _fetch_page(session, config.path, headers, {"page": page, "limit": config.default_limit}, logger)
        if data is None:
            break
        payload = data.get("data") or {}
        items = payload.get("campaigns") or []
        for item in items:
            display_id = item.get("display_id")
            if display_id is not None:
                yield display_id

        pagination = payload.get("pagination") or {}
        if not _has_next_page(page, pagination.get("pages"), len(items), config.default_limit):
            break
        page += 1


def _get_list_rows(
    session: requests.Session,
    config: LinkrunnerEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[LinkrunnerResumeConfig],
    start_timestamp: str | None,
) -> Iterator[Any]:
    """Page a top-level list endpoint (campaigns / reporting_campaigns)."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None and resume.campaign_display_id is None else 1

    while True:
        params: dict[str, Any] = {"page": page, "limit": config.default_limit}
        if start_timestamp and config.incremental_start_param:
            params[config.incremental_start_param] = start_timestamp

        data = _fetch_page(session, config.path, headers, params, logger)
        if data is None:
            break

        payload = data.get("data") or {}
        items = payload.get(config.data_key) or []
        pagination = payload.get("pagination") or {}
        has_next = _has_next_page(page, pagination.get("pages"), len(items), config.default_limit)

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding (only when more pages remain) so a crash re-yields the last
                # page rather than skipping it — merge dedupes on the primary key.
                if has_next:
                    resumable_source_manager.save_state(LinkrunnerResumeConfig(page=page + 1))

        if not has_next:
            break
        page += 1


def _get_attributed_user_rows(
    session: requests.Session,
    config: LinkrunnerEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[LinkrunnerResumeConfig],
    start_timestamp: str | None,
) -> Iterator[Any]:
    """Fan out over every campaign, paging /attributed-users per campaign display_id."""
    campaign_ids = list(_iter_campaign_display_ids(session, headers, logger))

    # Resolve the saved campaign bookmark to the slice still to process. If the bookmarked campaign no
    # longer exists (deleted between runs), start over — merge dedupes on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = campaign_ids
    resume_page = 1
    if resume is not None and resume.campaign_display_id is not None and resume.campaign_display_id in campaign_ids:
        remaining = campaign_ids[campaign_ids.index(resume.campaign_display_id) :]
        resume_page = resume.page
        logger.debug(
            f"Linkrunner: resuming attributed_users from campaign={resume.campaign_display_id}, page={resume_page}"
        )

    for index, display_id in enumerate(remaining):
        page = resume_page
        resume_page = 1  # only the resumed-into campaign uses the saved page; the rest start at 1

        while True:
            params: dict[str, Any] = {"display_id": display_id, "page": page, "limit": config.default_limit}
            if start_timestamp:
                params["start_timestamp"] = start_timestamp

            data = _fetch_page(session, config.path, headers, params, logger)
            if data is None:  # 204 — campaign has no attributed users in range
                break

            payload = data.get("data") or {}
            items = payload.get(config.data_key) or []
            pagination = payload.get("pagination") or {}
            has_next = _has_next_page(page, pagination.get("pages"), len(items), config.default_limit)

            for item in items:
                batcher.batch(_flatten_attributed_user(item))
                if batcher.should_yield():
                    yield batcher.get_table()
                    if has_next:
                        resumable_source_manager.save_state(
                            LinkrunnerResumeConfig(page=page + 1, campaign_display_id=display_id)
                        )

            if not has_next:
                break
            page += 1

        # Advance the bookmark to the next campaign so a crash between campaigns resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(
                LinkrunnerResumeConfig(page=1, campaign_display_id=remaining[index + 1])
            )


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LinkrunnerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = LINKRUNNER_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page (and every campaign, for the fan-out) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. Redact the API key from tracked logs /
    # captured samples — it rides a nonstandard `linkrunner-key` header the denylist can't predict.
    session = make_tracked_session(redact_values=(api_key,))

    start_timestamp = (
        _format_timestamp(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value
        else None
    )

    if config.fan_out_over_campaigns:
        yield from _get_attributed_user_rows(
            session, config, headers, logger, batcher, resumable_source_manager, start_timestamp
        )
    else:
        yield from _get_list_rows(session, config, headers, logger, batcher, resumable_source_manager, start_timestamp)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def linkrunner_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LinkrunnerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = LINKRUNNER_ENDPOINTS[endpoint]

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
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # Linkrunner doesn't document a sort order and exposes no sort param. The pipeline computes the
        # incremental watermark as the max value seen and only commits it on success, and this source is
        # resumable, so ascending-order assumptions aren't relied upon for correctness here.
        sort_mode="asc",
    )
