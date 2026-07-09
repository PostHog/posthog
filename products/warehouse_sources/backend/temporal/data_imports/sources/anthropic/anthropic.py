import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ANTHROPIC_ENDPOINTS,
    AnthropicEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
# Entity list endpoints accept limit 1-1000.
ENTITY_PAGE_SIZE = 500
# Report endpoints cap buckets per page; at 1d width the max is 31.
REPORT_BUCKET_LIMIT = 31
# Earliest window start when there is no incremental watermark yet (the Anthropic API launched
# in 2023, so no usage or cost data can predate this).
DEFAULT_STARTING_AT = datetime(2023, 1, 1, tzinfo=UTC)
# Usage/cost data lands up to ~5 minutes after a request completes, and the current day's bucket
# is always partial, so incremental syncs re-fetch a trailing window and rely on merge dedupe.
INCREMENTAL_LOOKBACK = timedelta(days=1)
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class AnthropicRetryableError(Exception):
    pass


@dataclasses.dataclass
class AnthropicResumeConfig:
    # Cursor (last_id) into an after_id-paginated entity list.
    after_id: Optional[str] = None
    # Report endpoints: the window start of the in-flight request chain plus the opaque
    # next_page token to continue from.
    starting_at: Optional[str] = None
    page: Optional[str] = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{ANTHROPIC_BASE_URL}{path}"
    # doseq expands the group_by[] list into repeated params.
    return f"{ANTHROPIC_BASE_URL}{path}?{urlencode(clean_params, doseq=True)}"


def _to_start_datetime(value: Any) -> Optional[datetime]:
    """Coerce a persisted incremental watermark into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _format_rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_starting_at(db_incremental_field_last_value: Any) -> str:
    """Window start for a report request: the watermark minus a lookback, floored to midnight UTC
    (buckets snap to day boundaries), or the default backfill start on the first sync."""
    last_value = _to_start_datetime(db_incremental_field_last_value)
    if last_value is None:
        return _format_rfc3339(DEFAULT_STARTING_AT)
    start = (last_value - INCREMENTAL_LOOKBACK).replace(hour=0, minute=0, second=0, microsecond=0)
    return _format_rfc3339(max(start, DEFAULT_STARTING_AT))


def _flatten_report_buckets(buckets: list[dict[str, Any]], config: AnthropicEndpointConfig) -> list[dict[str, Any]]:
    """Flatten time buckets into one row per (bucket, group-by combination) with a synthetic
    primary key, so re-fetched windows merge instead of duplicating."""
    rows: list[dict[str, Any]] = []
    for bucket in buckets:
        # Direct access: a missing bucket boundary must fail loudly rather than seed rows with a
        # None primary key, watermark, and partition key.
        bucket_starting_at = bucket["starting_at"]
        bucket_ending_at = bucket["ending_at"]
        for result in bucket.get("results") or []:
            row = dict(result)
            row["bucket_starting_at"] = bucket_starting_at
            row["bucket_ending_at"] = bucket_ending_at
            row["id"] = "|".join([str(bucket_starting_at), *(str(result.get(key)) for key in config.key_fields)])
            rows.append(row)
    return rows


def validate_credentials(api_key: str) -> bool:
    """Confirm the Admin API key works. Listing one organization user is the cheapest
    authenticated probe every admin key can perform."""
    try:
        response = make_tracked_session().get(
            _build_url("/v1/organizations/users", {"limit": 1}),
            headers=_get_headers(api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def _make_fetch_page(headers: dict[str, str], logger: FilteringBoundLogger) -> Callable[[str], dict[str, Any]]:
    @retry(
        retry=retry_if_exception_type((AnthropicRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(url: str) -> dict[str, Any]:
        response = make_tracked_session().get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # The Admin API rate limit is sustained-per-minute with burst allowance; exponential
        # backoff on 429 is sufficient.
        if response.status_code == 429 or response.status_code >= 500:
            raise AnthropicRetryableError(f"Anthropic API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Anthropic API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    return fetch_page


def _entity_pages(
    fetch_page: Callable[[str], dict[str, Any]],
    config: AnthropicEndpointConfig,
    after_id: Optional[str],
    on_page_complete: Optional[Callable[[str], None]] = None,
) -> Iterator[list[dict[str, Any]]]:
    """Iterate an after_id-cursor list endpoint, yielding each page's items."""
    while True:
        params: dict[str, Any] = {**config.params, "limit": ENTITY_PAGE_SIZE}
        if after_id:
            params["after_id"] = after_id

        data = fetch_page(_build_url(config.path, params))
        items = data.get("data") or []

        if items:
            yield items

        after_id = data.get("last_id")
        if not data.get("has_more") or not after_id:
            break

        if on_page_complete is not None:
            on_page_complete(after_id)


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ANTHROPIC_ENDPOINTS[endpoint]
    fetch_page = _make_fetch_page(_get_headers(api_key), logger)
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        logger.debug(f"Anthropic: resuming {endpoint} from saved state: {resume_config}")

    if config.kind == "entity":
        after_id = resume_config.after_id if resume_config else None
        yield from _entity_pages(
            fetch_page,
            config,
            after_id,
            on_page_complete=lambda last_id: resumable_source_manager.save_state(
                AnthropicResumeConfig(after_id=last_id)
            ),
        )
    elif config.kind == "workspace_members":
        # Fan-out over the (small) workspace list. Rows merge on (workspace_id, user_id), so no
        # intermediate resume state is saved — a resumed sync restarts the fan-out cleanly.
        workspaces_config = ANTHROPIC_ENDPOINTS["workspaces"]
        for workspace_page in _entity_pages(fetch_page, workspaces_config, None):
            for workspace in workspace_page:
                member_config = dataclasses.replace(config, path=config.path.format(workspace_id=workspace["id"]))
                yield from _entity_pages(fetch_page, member_config, None)
    else:
        if resume_config is not None and resume_config.starting_at is not None:
            starting_at = resume_config.starting_at
            page = resume_config.page
        else:
            starting_at = _compute_starting_at(
                db_incremental_field_last_value if should_use_incremental_field else None
            )
            page = None

        while True:
            params: dict[str, Any] = {
                "starting_at": starting_at,
                "limit": REPORT_BUCKET_LIMIT,
                "bucket_width": config.bucket_width,
                "group_by[]": config.group_by or None,
                "page": page,
            }
            data = fetch_page(_build_url(config.path, params))

            rows = _flatten_report_buckets(data.get("data") or [], config)
            if rows:
                yield rows

            page = data.get("next_page")
            if not data.get("has_more") or not page:
                break

            resumable_source_manager.save_state(AnthropicResumeConfig(starting_at=starting_at, page=page))


def anthropic_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ANTHROPIC_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Report time buckets are returned in chronological order; entity lists are full refresh
        # where ordering does not affect the watermark.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
