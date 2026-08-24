import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.constants import (
    KLAVIYO_API_VERSION_2026_07_15,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.settings import (
    KLAVIYO_ENDPOINTS,
    KlaviyoEndpointConfig,
    KlaviyoFanOutConfig,
)

KLAVIYO_BASE_URL = "https://a.klaviyo.com/api"

# Klaviyo's reporting API requires a conversion metric on every values report. Placed Order is the
# metric its own reporting defaults to, so it's the fallback when the source doesn't name one.
DEFAULT_CONVERSION_METRIC_NAME = "Placed Order"
# Accounts have tens of metrics, so the fallback lookup stays bounded rather than walking forever.
MAX_CONVERSION_METRIC_PAGES = 20

# Klaviyo's exact detail string when a metric (configured or auto-resolved) can't be used as a
# values report's conversion metric, e.g. a system metric Klaviyo doesn't allow for conversion
# statistics. The same metric would be re-resolved on every retry, so this can never self-heal.
CONVERSION_METRIC_INELIGIBLE_DETAIL = "does not support querying for values data"


class KlaviyoRetryableError(Exception):
    pass


@dataclasses.dataclass
class KlaviyoResumeConfig:
    # Next page URL to fetch. None means "start the parent at its first page" — used when the
    # bookmark advances to a fan-out parent whose first page URL isn't known until it's built.
    next_url: str | None = None
    # The fan-out parent currently being processed (a list, segment, or flow action, depending on
    # the endpoint). A stable ID bookmark (not a positional index) so parents added or removed
    # between a crash and the retry can't resume us into the wrong one. None for the standard
    # (non-fan-out) endpoints. Named `list_id` because list membership was the first fan-out and
    # in-flight resume state persisted under that key must keep deserializing.
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
    incremental_filter = f"{config.incremental_operator}({filter_field},{formatted_value})" if formatted_value else None

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


def _get_headers(api_key: str, revision: str = KLAVIYO_API_VERSION_2026_07_15) -> dict[str, str]:
    # `revision` is the pinned vendor API version, threaded from the source instance's resolved pin.
    # Defaults to the current version for credential validation, which runs before any row is pinned.
    return {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": revision,
        "Accept": "application/json",
    }


def validate_credentials(api_key: str, api_version: str = KLAVIYO_API_VERSION_2026_07_15) -> bool:
    # Probe under the caller's resolved pin so a 2024-10-15-pinned source validates on the
    # same `revision` header it syncs with.
    url = f"{KLAVIYO_BASE_URL}/accounts"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key, api_version), timeout=10)
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


def _extract_error_detail(response: requests.Response) -> str | None:
    """Pull the human-readable reason out of a Klaviyo JSON:API error body, if there is one."""
    try:
        errors = response.json().get("errors", [])
        details = [
            str(detail)
            for error in errors
            if isinstance(error, dict) and (detail := error.get("detail") or error.get("title"))
        ]
        return "; ".join(details)[:500] if details else None
    except Exception:
        return None


def _raise_for_status_with_detail(response: requests.Response) -> None:
    """`raise_for_status`, with Klaviyo's error detail appended to the exception message.

    requests builds the HTTPError message from the status and URL alone, but a Klaviyo 403 carries
    the actual denial reason only in the body — a key missing a read scope and an endpoint the
    account's plan doesn't include (e.g. webhooks without Advanced KDP) are indistinguishable
    without it. Non-retryable classification matches on the exception message, so the detail must
    ride along. The response stays attached for handlers that branch on `exc.response`.
    """
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = _extract_error_detail(response)
        if detail:
            raise requests.HTTPError(f"{exc} ({detail})", response=response) from exc
        raise


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
    session: requests.Session,
    page_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
) -> dict:
    # Klaviyo's reporting endpoints take their query in a POST body; every other endpoint is a GET.
    if json_body is None:
        response = session.get(page_url, headers=headers, timeout=60)
    else:
        response = session.post(page_url, headers=headers, json=json_body, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise KlaviyoRetryableError(f"Klaviyo API error (retryable): status={response.status_code}, url={page_url}")

    if not response.ok:
        # 404 is expected and handled during a fan-out (a parent deleted mid-sync).
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Klaviyo API error: status={response.status_code}, body={response.text}, url={page_url}")
        _raise_for_status_with_detail(response)

    return response.json()


def _iter_resource_ids(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    path: str,
    page_size: int,
) -> Iterator[str]:
    """Page through a Klaviyo collection and yield each row's id, following the cursor links."""
    url = _build_url(f"{KLAVIYO_BASE_URL}{path}", {"page[size]": page_size})
    while True:
        data = _fetch_page(session, url, headers, logger)
        for item in data.get("data", []):
            yield item["id"]

        next_url = data.get("links", {}).get("next")
        if not next_url:
            break
        url = next_url


def _iter_fan_out_parents(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    fan_out: KlaviyoFanOutConfig,
) -> Iterator[tuple[dict[str, str], str]]:
    """Yield (ancestor columns, parent id) for every parent the child endpoint fans out over.

    A one-level fan-out walks the parent collection directly and carries no ancestor columns. A
    two-level fan-out (flows -> flow actions -> flow messages) walks the grandparent first and
    formats the parent path with each grandparent id, tagging every parent with that id.
    """
    if fan_out.grandparent is None:
        for parent_id in _iter_resource_ids(session, headers, logger, fan_out.parent_path, fan_out.parent_page_size):
            yield {}, parent_id
        return

    grandparent = fan_out.grandparent
    for grandparent_id in _iter_resource_ids(
        session, headers, logger, grandparent.parent_path, grandparent.parent_page_size
    ):
        path = fan_out.parent_path.format(**{grandparent.parent_id_column: grandparent_id})
        try:
            for parent_id in _iter_resource_ids(session, headers, logger, path, fan_out.parent_page_size):
                yield {grandparent.parent_id_column: grandparent_id}, parent_id
        except requests.HTTPError as exc:
            # A grandparent deleted between enumeration and this fetch 404s; its children are gone
            # with it, so skip rather than failing the whole sync.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Klaviyo: {path} not found while enumerating fan-out parents, skipping")
            else:
                raise


def _fan_out_row(
    fan_out: KlaviyoFanOutConfig, ancestors: dict[str, str], parent_id: str, item: dict[str, Any]
) -> dict[str, Any]:
    if fan_out.membership_rows:
        return {
            fan_out.parent_id_column: parent_id,
            "profile_id": item["id"],
            "joined_group_at": item.get("attributes", {}).get("joined_group_at"),
        }

    row = _flatten_item(item)
    row[fan_out.parent_id_column] = parent_id
    row.update(ancestors)
    return row


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[KlaviyoResumeConfig],
    config: KlaviyoEndpointConfig,
    params: dict[str, Any],
) -> Iterator[Any]:
    """Fan out over every parent, tagging each child row with the parent (and grandparent) it came from.

    For membership endpoints this materializes the otherwise-unqueryable many-to-many as flat
    {<parent>_id, profile_id, joined_group_at} rows; for the rest it yields the flattened child
    resource plus its ancestor ids.

    `params` carries any incremental filter (minus the config lookback, so rows that changed in an
    already-fetched parent mid-run get re-pulled; merge dedupes on the primary key). Klaviyo updates
    `joined_group_at` on re-join, so re-joins are picked up too — but there is no removal timestamp,
    so profiles removed from a list or segment only disappear on a full refresh.

    Fan-out runs report sort_mode="desc" (see klaviyo_source), so the watermark persists only after
    every parent completes. A crash + resume can also finalize an under-advanced watermark (the
    resumed attempt's running max only sees post-resume batches) — safe direction, the next run just
    re-fetches a wider window that merge dedupes.
    """
    fan_out = config.fan_out
    assert fan_out is not None
    parents = list(_iter_fan_out_parents(session, headers, logger, fan_out))
    parent_ids = [parent_id for _, parent_id in parents]

    # Resolve the saved parent-ID bookmark to the slice of parents still to process. If the
    # bookmarked parent no longer exists (deleted between runs), start over from the first one —
    # merge dedupes the re-pulled rows on the primary key. `resume_url` is consumed by the first
    # parent only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = parents
    resume_url: str | None = None
    if resume is not None and resume.list_id is not None and resume.list_id in parent_ids:
        remaining = parents[parent_ids.index(resume.list_id) :]
        resume_url = resume.next_url
        logger.debug(f"Klaviyo: resuming {config.name} from parent={resume.list_id}, url={resume_url}")

    for index, (ancestors, parent_id) in enumerate(remaining):
        child_path = config.path.format(**{fan_out.parent_id_column: parent_id})
        url = resume_url or _build_url(f"{KLAVIYO_BASE_URL}{child_path}", params)
        resume_url = None  # only the resumed-into parent uses the saved URL; the rest start fresh

        try:
            while True:
                data = _fetch_page(session, url, headers, logger)
                items = data.get("data", [])
                next_url = data.get("links", {}).get("next")

                for item in items:
                    batcher.batch(_fan_out_row(fan_out, ancestors, parent_id, item))

                    if batcher.should_yield():
                        yield batcher.get_table()
                        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the
                        # last page rather than skipping it — merge dedupes on the primary key.
                        if next_url:
                            resumable_source_manager.save_state(
                                KlaviyoResumeConfig(next_url=next_url, list_id=parent_id)
                            )

                if not next_url:
                    break
                url = next_url
        except requests.HTTPError as exc:
            # A parent deleted between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync — the rows are genuinely gone. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Klaviyo: {child_path} not found while fetching {config.name}, skipping")
            else:
                raise

        # Advance the bookmark to the next parent so a crash between parents resumes correctly. Its
        # first page URL is built fresh when the loop reaches it.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(KlaviyoResumeConfig(next_url=None, list_id=remaining[index + 1][1]))


def _resolve_conversion_metric_id(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> str | None:
    """Pick the metric that conversion statistics in the values reports are attributed to.

    Klaviyo requires a conversion metric on every values report but has no "account default" to
    read, so fall back to the Placed Order metric its own reporting defaults to, then to whatever
    metric the account defines first. A user who wants a different one sets it on the source.
    """
    url = f"{KLAVIYO_BASE_URL}/metrics"
    first_metric_id: str | None = None

    for _ in range(MAX_CONVERSION_METRIC_PAGES):
        data = _fetch_page(session, url, headers, logger)
        for item in data.get("data", []):
            if first_metric_id is None:
                first_metric_id = item["id"]
            if item.get("attributes", {}).get("name") == DEFAULT_CONVERSION_METRIC_NAME:
                return item["id"]

        next_url = data.get("links", {}).get("next")
        if not next_url:
            break
        url = next_url

    return first_metric_id


def _get_values_report_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    config: KlaviyoEndpointConfig,
    conversion_metric_id: str | None,
) -> Iterator[Any]:
    """Post a Klaviyo values report and flatten each grouping's statistics into one row.

    The report is an aggregate over a rolling window rather than a resource collection, so there is
    no cursor to advance — the table is replaced in full on every sync.
    """
    report = config.values_report
    assert report is not None

    metric_id = conversion_metric_id or _resolve_conversion_metric_id(session, headers, logger)
    if not metric_id:
        logger.warning(
            f"Klaviyo: no conversion metric found for {config.name}; set a conversion metric ID on the source"
        )
        return

    body = {
        "data": {
            "type": report.report_type,
            "attributes": {
                "statistics": report.statistics,
                "timeframe": {"key": report.timeframe_key},
                "conversion_metric_id": metric_id,
                "group_by": report.group_by,
            },
        }
    }
    # Klaviyo rejects a reporting POST that isn't sent as JSON:API.
    post_headers = {**headers, "Content-Type": "application/vnd.api+json"}
    url = f"{KLAVIYO_BASE_URL}{config.path}"

    try:
        while True:
            data = _fetch_page(session, url, post_headers, logger, json_body=body)
            attributes = data.get("data", {}).get("attributes", {})

            for result in attributes.get("results", []):
                batcher.batch(
                    {
                        **result.get("groupings", {}),
                        **result.get("statistics", {}),
                        "timeframe_key": report.timeframe_key,
                        "conversion_metric_id": metric_id,
                    }
                )
                if batcher.should_yield():
                    yield batcher.get_table()

            next_url = data.get("links", {}).get("next")
            if not next_url:
                break
            url = next_url
    except requests.HTTPError as exc:
        if (
            exc.response is not None
            and exc.response.status_code == 400
            and CONVERSION_METRIC_INELIGIBLE_DETAIL in exc.response.text
        ):
            logger.warning(
                f"Klaviyo: conversion metric {metric_id} isn't eligible for values reporting on "
                f"{config.name}; set a different conversion metric ID on the source, skipping"
            )
            return
        raise


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KlaviyoResumeConfig],
    api_version: str = KLAVIYO_API_VERSION_2026_07_15,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
    conversion_metric_id: str | None = None,
) -> Iterator[Any]:
    config = KLAVIYO_ENDPOINTS[endpoint]
    headers = _get_headers(api_key, api_version)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page (and, for fan-out, every parent) so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = make_tracked_session()

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    if config.values_report is not None:
        yield from _get_values_report_rows(session, headers, logger, batcher, config, conversion_metric_id)
        if batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()
        return

    if config.fan_out is not None:
        yield from _get_fan_out_rows(session, headers, logger, batcher, resumable_source_manager, config, params)
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
    api_version: str = KLAVIYO_API_VERSION_2026_07_15,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
    conversion_metric_id: str | None = None,
) -> SourceResponse:
    endpoint_config = KLAVIYO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            api_version=api_version,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
            conversion_metric_id=conversion_metric_id,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Fan-out runs persist the incremental watermark only at successful job end (desc mode): a
        # partial run's max says nothing about parents it never reached, so per-batch persistence
        # could advance the watermark past rows a crashed run still owes.
        sort_mode="desc" if endpoint_config.fan_out is not None else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
