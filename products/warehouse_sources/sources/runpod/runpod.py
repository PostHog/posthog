import hashlib
import dataclasses
from collections.abc import Iterator
from datetime import (
    UTC,
    date,
    datetime,
    time as datetime_time,
    timedelta,
)
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.runpod.settings import (
    BILLING_BUCKET_SIZE,
    INVENTORY_PAGE_SIZE,
    RUNPOD_BASE_URL,
    RUNPOD_ENDPOINTS,
    RunPodEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    retry_with_deadline,
)

# Billing responses are unpaginated, so bound each request to a fixed window and walk the windows
# chronologically — memory stays bounded and a crash resumes at the last unfetched window.
BILLING_WINDOW = timedelta(days=90)

# Floor for `startTime` on a full refresh. RunPod launched in 2022, so no billing data can predate
# this — starting here pulls all available history without requesting decades of empty buckets.
DEFAULT_STARTING_AT = datetime(2022, 1, 1, tzinfo=UTC)


class RunPodRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class RunPodResumeConfig:
    # RFC 3339 start of the next unfetched billing window. Windows before it are fully yielded.
    window_start: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_rfc3339(value: datetime) -> str:
    dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime_time.min, tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _floor_to_day(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _build_url(path: str, params: dict[str, Any]) -> str:
    encoded = urlencode([(k, str(v)) for k, v in params.items() if v is not None])
    url = f"{RUNPOD_BASE_URL}{path}"
    return f"{url}?{encoded}" if encoded else url


@retry_with_deadline(
    retry=retry_if_exception_type(
        (
            RunPodRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise RunPodRetryableError(f"RunPod API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"RunPod API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"RunPod API returned an unexpected non-object response for url={url}")
    return data


def _rows_from(data: dict[str, Any], key: str, url: str) -> list[dict[str, Any]]:
    rows = data.get(key)
    if not isinstance(rows, list):
        raise ValueError(f"RunPod API returned a non-list `{key}` for url={url}")
    return rows


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe against the pods list confirms the API key is genuine.
    url = _build_url("/pods", {"limit": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False
    # 200 => valid. 403 => valid key restricted to other endpoints; still a real key, so accept it at
    # create time (sync-time 403s are caught by get_non_retryable_errors). 401 => bad key.
    return response.status_code in (200, 403)


def _row_id(*parts: Any) -> str:
    """Deterministic surrogate id for a billing record.

    Hashes only the identity/dimension fields (never the amounts), so a bucket whose charges get
    restated between runs keeps the same id and merge updates it in place rather than inserting a
    duplicate.
    """
    # Use a sentinel for None so a missing dimension can never collide with an empty-string value.
    joined = "|".join("\x00" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


def _billing_row_id(record: dict[str, Any]) -> str:
    # Same parts and order as the v1 ids (time, podId, endpointId, gpuTypeId), so merge updates the
    # buckets that v1 wrote instead of duplicating them. v2 has no GPU type grouping, so it is None.
    parts = [record.get("time"), record.get("podId"), record.get("serverlessId"), None]
    # v1 network volume billing was one account-wide record per bucket; v2 is one per volume.
    if (volume_id := record.get("networkVolumeId")) is not None:
        parts.append(volume_id)
    return _row_id(*parts)


def _normalize_billing_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    if "time" not in normalized and "startTime" in normalized:
        # `time` is the v1 column name and the declared incremental field and partition key.
        normalized["time"] = normalized.pop("startTime")
    return {
        **normalized,
        # Set last so a record that happens to carry its own "id" key can never override the
        # synthesized surrogate id merge relies on for dedup.
        "id": _billing_row_id(normalized),
    }


def _billing_params(window_start: datetime, window_end: Optional[datetime]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "bucketSize": BILLING_BUCKET_SIZE,
        "startTime": _format_rfc3339(window_start),
    }
    if window_end is not None:
        params["endTime"] = _format_rfc3339(window_end)
    return params


def _initial_window_start(
    resumable_source_manager: ResumableSourceManager[RunPodResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
    now: datetime,
) -> datetime:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start:
        logger.debug(f"RunPod: resuming billing sync from window_start={resume.window_start}")
        return _coerce_datetime(resume.window_start)

    if should_use_incremental_field and db_incremental_field_last_value:
        # Floor to UTC midnight so `startTime` stays aligned with day-bucket boundaries — a shifted
        # start could re-bucket the overlap window under different `time` values that merge can't
        # dedupe. Cap at today's bucket so a future-dated watermark still re-pulls the open bucket.
        watermark = _floor_to_day(_coerce_datetime(db_incremental_field_last_value))
        return min(watermark, _floor_to_day(now))

    return DEFAULT_STARTING_AT


def _iter_billing_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RunPodResumeConfig],
    config: RunPodEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    now = datetime.now(UTC)
    window_start = _initial_window_start(
        resumable_source_manager, should_use_incremental_field, db_incremental_field_last_value, logger, now
    )

    while window_start <= now:
        proposed_end = window_start + BILLING_WINDOW
        # The final window runs to "now": omit endTime so the open bucket is included.
        window_end = proposed_end if proposed_end < now else None

        url = _build_url(config.path, _billing_params(window_start, window_end))
        records = _rows_from(_fetch_json(session, url, headers, logger), config.response_key, url)

        # Response ordering is undocumented; each window arrives whole, so sort client-side to keep
        # the ascending guarantee sort_mode="asc" promises the pipeline.
        rows = sorted((_normalize_billing_record(record) for record in records), key=lambda r: r.get("time") or "")
        if window_end is not None:
            resumable_source_manager.save_state(RunPodResumeConfig(window_start=_format_rfc3339(window_end)))
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()

        if window_end is None:
            break
        window_start = window_end


def _strip_sensitive_keys(value: Any, keys: tuple[str, ...]) -> Any:
    """Recursively drop keys holding user-configured secrets (e.g. `env` maps).

    Removes the whole field wherever it appears in the object graph, so a secret map nested under an
    embedded resource (an endpoint's template, say) is stripped too. The names inside an `env` map are
    arbitrary and user-chosen, so a key-name denylist can't recognise them — removing the container is
    the only reliable way to keep credentials out of the warehouse.
    """
    if isinstance(value, dict):
        return {k: _strip_sensitive_keys(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_strip_sensitive_keys(item, keys) for item in value]
    return value


def _iter_inventory_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: RunPodEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    cursor: Optional[str] = None
    while True:
        url = _build_url(config.path, {"limit": INVENTORY_PAGE_SIZE, "cursor": cursor})
        data = _fetch_json(session, url, headers, logger)
        items = _rows_from(data, config.response_key, url)
        pagination = data.get("pagination") or {}
        del data
        if config.sensitive_keys:
            items = [_strip_sensitive_keys(item, config.sensitive_keys) for item in items]
        if items:
            yield items

        cursor = pagination.get("nextCursor")
        if not pagination.get("hasNextPage") or not cursor:
            break


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RunPodResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = RUNPOD_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # Endpoints carrying user-configured `env` secrets are excluded from HTTP sample capture so raw
    # response bodies with those credentials never reach captured samples (the values have arbitrary
    # names the name-based sample scrubbers can't recognise).
    session = make_tracked_session(capture=not config.sensitive_keys)

    if config.is_billing:
        yield from _iter_billing_rows(
            session,
            headers,
            logger,
            resumable_source_manager,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        yield from _iter_inventory_rows(session, headers, logger, config)


def runpod_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RunPodResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RUNPOD_ENDPOINTS[endpoint]

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
        # Billing windows advance chronologically and each window is sorted by bucket start before
        # yielding, so rows arrive ascending — the pipeline checkpoints the watermark per batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
