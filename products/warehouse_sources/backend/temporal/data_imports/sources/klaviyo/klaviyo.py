import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.settings import (
    KLAVIYO_ENDPOINTS,
    KlaviyoEndpointConfig,
)

KLAVIYO_BASE_URL = "https://a.klaviyo.com/api"


class KlaviyoRetryableError(Exception):
    pass


@dataclasses.dataclass
class KlaviyoResumeConfig:
    # Next page URL to fetch. None means "start the list at its first page" — used when the bookmark
    # advances to a fan-out list whose first page URL isn't known until it's built.
    next_url: str | None = None
    # The fan-out list currently being processed. A stable list-ID bookmark (not a positional index)
    # so lists added/removed between a crash and the retry can't resume us into the wrong list. None
    # for the standard (non-fan-out) endpoints.
    list_id: str | None = None


def _format_datetime_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 with Z suffix, which Klaviyo's API requires.

    Klaviyo rejects the +00:00 UTC offset format produced by isoformat(),
    so we must use the Z suffix instead.
    """
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value for Klaviyo API filters."""
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date incremental cursor at the current time.

    The incremental cursor tracks the max value seen for the endpoint's datetime field
    (e.g. an event's customer-supplied `datetime`). If the source's data contains a
    future-dated record, the cursor advances past now and every subsequent sync builds
    a `greater-than(<field>,<future>)` filter that Klaviyo rejects with a 400, wedging
    the sync. Asking for records newer than now is a no-op anyway, so capping the value
    keeps the request valid and lets the sync self-heal.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware_value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware_value > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _apply_lookback(value: Any, lookback: timedelta | None) -> Any:
    """Shift a datetime/date incremental cursor back by `lookback` to re-pull a safety window.

    The re-pulled rows are deduped by the endpoint's primary key on merge. No-op for
    non-temporal values or when the endpoint declares no lookback.
    """
    if lookback is None:
        return value
    if isinstance(value, datetime):
        return value - lookback
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC) - lookback
    return value


def _build_filter(
    config: KlaviyoEndpointConfig,
    incremental_field: str | None,
    formatted_value: str | None,
) -> str | None:
    """Build Klaviyo filter string from config."""
    filter_field = incremental_field or config.default_incremental_field
    incremental_filter = f"greater-than({filter_field},{formatted_value})" if formatted_value else None

    if config.base_filter and incremental_filter:
        return f"and({config.base_filter},{incremental_filter})"
    elif config.base_filter:
        return config.base_filter
    else:
        return incremental_filter


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    """Build a URL with query params without percent-encoding.

    Klaviyo's API expects literal brackets, parentheses, and quotes in query params
    (e.g. page[size]=100, filter=equals(messages.channel,'email')).
    All param keys and values are constructed internally, so no encoding is needed.
    """
    if not params:
        return base_url
    parts = [f"{key}={value}" for key, value in params.items()]
    return f"{base_url}?{'&'.join(parts)}"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": "2024-10-15",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    url = f"{KLAVIYO_BASE_URL}/accounts"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten the 'attributes' object into the root level for a single item."""
    if "attributes" in item and isinstance(item["attributes"], dict):
        attributes = item.pop("attributes")
        item.update(attributes)
    return item


def _build_initial_params(
    config: KlaviyoEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build query params for the initial Klaviyo API request."""
    params: dict[str, Any] = {}

    if config.page_size is not None and config.page_size > 0:
        params["page[size]"] = config.page_size

    # On first sync/full refresh, apply a lookback window to avoid fetching the entire history
    if should_use_incremental_field and not db_incremental_field_last_value and config.default_lookback_days:
        db_incremental_field_last_value = datetime.now(UTC) - timedelta(days=config.default_lookback_days)

    # Future-dated source data can push the cursor past now; Klaviyo 400s on a future filter value.
    # The lookback must apply after the clamp, so a clamped cursor still re-pulls its safety window.
    if should_use_incremental_field and db_incremental_field_last_value:
        db_incremental_field_last_value = _clamp_future_value_to_now(db_incremental_field_last_value)
        db_incremental_field_last_value = _apply_lookback(db_incremental_field_last_value, config.incremental_lookback)

    formatted_last_value = (
        _format_incremental_value(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value
        else None
    )
    filter_value = _build_filter(config, incremental_field, formatted_last_value)
    if filter_value:
        params["filter"] = filter_value

    if config.sort:
        params["sort"] = config.sort

    params.update(config.extra_params)

    return params


@retry(
    # ChunkedEncodingError is a mid-stream connection break (the server truncated a chunked
    # response body); it's transient like ConnectionError/ReadTimeout, not a ConnectionError subclass.
    retry=retry_if_exception_type(
        (
            KlaviyoRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, page_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict:
    response = session.get(page_url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise KlaviyoRetryableError(f"Klaviyo API error (retryable): status={response.status_code}, url={page_url}")

    if not response.ok:
        # 404 is expected and handled during the list_profiles fan-out (a list deleted mid-sync).
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Klaviyo API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response.json()


def _iter_list_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> Iterator[str]:
    """Page through /lists and yield each list's id, following the cursor links."""
    # Klaviyo caps the /lists endpoint at a page size of 10 (larger values 400).
    url = _build_url(f"{KLAVIYO_BASE_URL}/lists", {"page[size]": 10})
    while True:
        data = _fetch_page(session, url, headers, logger)
        for item in data.get("data", []):
            yield item["id"]

        next_url = data.get("links", {}).get("next")
        if not next_url:
            break
        url = next_url


def _get_list_profile_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[KlaviyoResumeConfig],
    config: KlaviyoEndpointConfig,
    params: dict[str, Any],
) -> Iterator[Any]:
    """Fan out over every list, materializing membership as {list_id, profile_id, joined_group_at} rows.

    `params` carries any incremental filter on `joined_group_at` (minus the config lookback, so joins
    that landed in already-fetched lists mid-run get re-pulled; merge dedupes on the
    [list_id, profile_id] primary key). Klaviyo updates `joined_group_at` on re-join, so re-joins are
    picked up too — but there is no removal timestamp, so profiles removed from a list only disappear
    on a full refresh.

    The endpoint declares sort_mode="desc" (see the config comment in settings.py), so the watermark
    persists only after every list completes. A crash + resume can also finalize an under-advanced
    watermark (the resumed attempt's running max only sees post-resume batches) — safe direction, the
    next run just re-fetches a wider window that merge dedupes.
    """
    list_ids = list(_iter_list_ids(session, headers, logger))

    # Resolve the saved list-ID bookmark to the slice of lists still to process. If the bookmarked list
    # no longer exists (deleted between runs), start over from the first list — merge dedupes the
    # re-pulled rows on the primary key. `resume_url` is consumed by the first list only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = list_ids
    resume_url: str | None = None
    if resume is not None and resume.list_id is not None and resume.list_id in list_ids:
        remaining = list_ids[list_ids.index(resume.list_id) :]
        resume_url = resume.next_url
        logger.debug(f"Klaviyo: resuming list_profiles from list_id={resume.list_id}, url={resume_url}")

    for index, list_id in enumerate(remaining):
        url = resume_url or _build_url(f"{KLAVIYO_BASE_URL}{config.path.format(list_id=list_id)}", params)
        resume_url = None  # only the resumed-into list uses the saved URL; the rest start fresh

        try:
            while True:
                data = _fetch_page(session, url, headers, logger)
                items = data.get("data", [])
                next_url = data.get("links", {}).get("next")

                for item in items:
                    batcher.batch(
                        {
                            "list_id": list_id,
                            "profile_id": item["id"],
                            "joined_group_at": item.get("attributes", {}).get("joined_group_at"),
                        }
                    )

                    if batcher.should_yield():
                        yield batcher.get_table()
                        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the
                        # last page rather than skipping it — merge dedupes on the primary key.
                        if next_url:
                            resumable_source_manager.save_state(KlaviyoResumeConfig(next_url=next_url, list_id=list_id))

                if not next_url:
                    break
                url = next_url
        except requests.HTTPError as exc:
            # A list deleted between enumeration and this fetch 404s. Skip it rather than failing the
            # whole sync — the membership is genuinely gone. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Klaviyo: list {list_id} not found while fetching profiles, skipping")
            else:
                raise

        # Advance the bookmark to the next list so a crash between lists resumes correctly. Its first
        # page URL is built fresh when the loop reaches it.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(KlaviyoResumeConfig(next_url=None, list_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KlaviyoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = KLAVIYO_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page (and, for fan-out, every list) so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = make_tracked_session()

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    if config.fan_out_over_lists:
        yield from _get_list_profile_rows(session, headers, logger, batcher, resumable_source_manager, config, params)
        if batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()
        return

    # Check for resume state
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume_config is not None and resume_config.next_url:
        url = resume_config.next_url
        logger.debug(f"Klaviyo: resuming from URL: {url}")
    else:
        url = _build_url(f"{KLAVIYO_BASE_URL}{config.path}", params)

    while True:
        data = _fetch_page(session, url, headers, logger)

        items = data.get("data", [])
        if not items:
            break

        # Get next page URL before iterating items
        links = data.get("links", {})
        next_url = links.get("next")

        for item in items:
            batcher.batch(_flatten_item(item))

            if batcher.should_yield():
                py_table = batcher.get_table()
                yield py_table

                if next_url:
                    resumable_source_manager.save_state(KlaviyoResumeConfig(next_url=next_url))

        if not next_url:
            break

        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        py_table = batcher.get_table()
        yield py_table


def klaviyo_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KlaviyoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = KLAVIYO_ENDPOINTS[endpoint]

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
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
