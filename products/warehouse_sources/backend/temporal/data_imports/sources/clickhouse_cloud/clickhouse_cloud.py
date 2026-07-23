import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.settings import (
    CLICKHOUSE_CLOUD_ENDPOINTS,
    USAGE_COST_MAX_WINDOW_DAYS,
    ClickhouseCloudEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CLICKHOUSE_CLOUD_BASE_URL = "https://api.clickhouse.cloud"
# Floor for a full-refresh usage_cost backfill when the organization's createdAt is missing —
# ClickHouse Cloud launched in late 2022, so no billing data can predate this.
DEFAULT_USAGE_COST_START = date(2022, 1, 1)


class ClickhouseCloudRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        # Seconds the server asked us to wait (from a 429 `Retry-After`), or None to back off blindly.
        self.retry_after = retry_after


# The API allows 10 requests per 10-second window per key, so 429s are expected on orgs with many
# services. Cap the honored `Retry-After` so a pathological header can't pin the worker.
_MAX_RETRY_AFTER_SECONDS = 60
_fallback_wait = wait_exponential_jitter(initial=2, max=30)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a delta-seconds `Retry-After` header. Returns None for a missing, non-numeric, or
    negative value so the caller falls back to exponential backoff."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _wait_clickhouse_cloud(retry_state: RetryCallState) -> float:
    """Honor the server's `Retry-After` on 429s (capped), else fall back to exponential jitter."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, ClickhouseCloudRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, _MAX_RETRY_AFTER_SECONDS)
    return _fallback_wait(retry_state)


@dataclasses.dataclass
class ClickhouseCloudResumeConfig:
    # usage_cost only: the organization and window start (YYYY-MM-DD) to resume from. Every other
    # endpoint is a single unpaginated request per organization, so a retry just refetches it.
    organization_id: str | None = None
    from_date: str | None = None


def _make_session(key_id: str, key_secret: str) -> requests.Session:
    session = make_tracked_session(headers={"Accept": "application/json"})
    # The Cloud API authenticates with HTTP Basic: key ID as username, key secret as password.
    session.auth = (key_id, key_secret)
    return session


def _build_url(path: str, params: dict[str, Any] | None = None) -> str:
    url = f"{CLICKHOUSE_CLOUD_BASE_URL}{path}"
    if not params:
        return url
    return f"{url}?{urlencode({k: str(v) for k, v in params.items() if v is not None})}"


@retry(
    retry=retry_if_exception_type(
        (
            ClickhouseCloudRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=_wait_clickhouse_cloud,
    reraise=True,
)
def _fetch(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    response = session.get(url, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        retry_after = _parse_retry_after(response.headers.get("retry-after")) if response.status_code == 429 else None
        raise ClickhouseCloudRetryableError(
            f"ClickHouse Cloud API error (retryable): status={response.status_code}, url={url}",
            retry_after=retry_after,
        )

    if not response.ok:
        logger.error(f"ClickHouse Cloud API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(key_id: str, key_secret: str) -> bool:
    url = _build_url("/v1/organizations")
    try:
        response = _make_session(key_id, key_secret).get(url, timeout=10)
    except Exception:
        return False
    # 200 => valid. 403 => a real key without the scope we probed; accept it at create time
    # (sync-time 403s are caught by get_non_retryable_errors). 401 => bad key ID/secret.
    return response.status_code in (200, 403)


def _coerce_date(value: Any) -> date | None:
    """Coerce a watermark or API value (date, datetime, or ISO string) to a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _format_rfc3339(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 UTC timestamp with a Z suffix."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _list_organizations(session: requests.Session, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    data = _fetch(session, _build_url("/v1/organizations"), logger)
    return data.get("result") or []


def _with_organization_id(item: dict[str, Any], organization_id: str) -> dict[str, Any]:
    """Stamp the parent organization onto a row so composite primary keys are always populated.
    Rows that already carry organizationId (activities) keep their own value."""
    if item.get("organizationId"):
        return item
    return {**item, "organizationId": organization_id}


def _iter_entity_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    config: ClickhouseCloudEndpointConfig,
    organizations: list[dict[str, Any]],
) -> Iterator[list[dict[str, Any]]]:
    for org in organizations:
        url = _build_url(config.path.format(organization_id=org["id"]))
        result = _fetch(session, url, logger).get("result") or []
        rows = [_with_organization_id(item, org["id"]) for item in result]
        if rows:
            yield rows


def _iter_activity_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    config: ClickhouseCloudEndpointConfig,
    organizations: list[dict[str, Any]],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    params: dict[str, Any] = {}
    if should_use_incremental_field and db_incremental_field_last_value:
        params["from_date"] = _format_rfc3339(db_incremental_field_last_value)

    for org in organizations:
        url = _build_url(config.path.format(organization_id=org["id"]), params)
        result = _fetch(session, url, logger).get("result") or []
        rows = [_with_organization_id(item, org["id"]) for item in result]
        # The API doesn't document response ordering; sort ascending client-side (the full array is
        # already in memory) so the pipeline's per-batch watermark checkpoints stay correct.
        rows.sort(key=lambda row: str(row.get("createdAt") or ""))
        if rows:
            yield rows


def _iter_backup_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    config: ClickhouseCloudEndpointConfig,
    organizations: list[dict[str, Any]],
) -> Iterator[list[dict[str, Any]]]:
    for org in organizations:
        services_url = _build_url(f"/v1/organizations/{org['id']}/services")
        services = _fetch(session, services_url, logger).get("result") or []
        for service in services:
            url = _build_url(config.path.format(organization_id=org["id"], service_id=service["id"]))
            result = _fetch(session, url, logger).get("result") or []
            rows = [
                {**_with_organization_id(item, org["id"]), "serviceId": item.get("serviceId") or service["id"]}
                for item in result
            ]
            if rows:
                yield rows


def _flatten_usage_cost_record(record: dict[str, Any], organization_id: str) -> dict[str, Any]:
    """Surface the nested per-record `metrics` object (storageCHC, computeCHC, ...) as flat columns
    so cost dashboards can query them directly. The metric keys are all distinct from the record's
    own fields, so flattening can't collide."""
    metrics = record.get("metrics") or {}
    row = {key: value for key, value in record.items() if key != "metrics"}
    row.update(metrics)
    row["organizationId"] = organization_id
    return row


def _usage_cost_start(
    org: dict[str, Any],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> date:
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        coerced = _coerce_date(db_incremental_field_last_value)
        if coerced is not None:
            return coerced
    # Full refresh / first sync: pull all available history from the organization's creation date.
    return _coerce_date(org.get("createdAt")) or DEFAULT_USAGE_COST_START


def _iter_usage_cost_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    config: ClickhouseCloudEndpointConfig,
    organizations: list[dict[str, Any]],
    resumable_source_manager: ResumableSourceManager[ClickhouseCloudResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Walk usageCost forward in windows of at most 31 days (the API's per-request cap) up to today.

    Windows never overlap (next start = previous end + 1 day, to_date is inclusive), so a single
    sync can't yield duplicate rows. The resume bookmark points at the next window start and is
    saved only AFTER the preceding window's rows are yielded — a crash re-pulls the last window and
    merge dedupes it on the primary key.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    today = datetime.now(UTC).date()

    for org in organizations:
        start = _usage_cost_start(org, should_use_incremental_field, db_incremental_field_last_value)
        if resume is not None and resume.organization_id == org["id"] and resume.from_date:
            start = date.fromisoformat(resume.from_date)
            logger.debug(f"ClickHouse Cloud: resuming usage_cost from {start.isoformat()}")
        # A future-dated watermark (clock skew, bad data) would make from_date > to_date and 400.
        start = min(start, today)

        while True:
            window_end = min(start + timedelta(days=USAGE_COST_MAX_WINDOW_DAYS - 1), today)
            url = _build_url(
                config.path.format(organization_id=org["id"]),
                {"from_date": start.isoformat(), "to_date": window_end.isoformat()},
            )
            result = _fetch(session, url, logger).get("result") or {}
            records = result.get("costs") or []
            rows = [_flatten_usage_cost_record(record, org["id"]) for record in records]
            # Records within a window aren't ordered; sort so dates ascend across the whole run and
            # the pipeline's per-batch watermark checkpoints stay correct.
            rows.sort(key=lambda row: str(row.get("date") or ""))
            if rows:
                yield rows

            if window_end >= today:
                break
            next_start = window_end + timedelta(days=1)
            resumable_source_manager.save_state(
                ClickhouseCloudResumeConfig(organization_id=org["id"], from_date=next_start.isoformat())
            )
            start = next_start


def get_rows(
    key_id: str,
    key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClickhouseCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CLICKHOUSE_CLOUD_ENDPOINTS[endpoint]
    session = _make_session(key_id, key_secret)

    organizations = _list_organizations(session, logger)
    if endpoint == "organizations":
        if organizations:
            yield organizations
        return

    if endpoint == "usage_cost":
        yield from _iter_usage_cost_rows(
            session,
            logger,
            config,
            organizations,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif endpoint == "activities":
        yield from _iter_activity_rows(
            session,
            logger,
            config,
            organizations,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.fan_out_over_services:
        yield from _iter_backup_rows(session, logger, config, organizations)
    else:
        yield from _iter_entity_rows(session, logger, config, organizations)


def clickhouse_cloud_source(
    key_id: str,
    key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClickhouseCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CLICKHOUSE_CLOUD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            key_id=key_id,
            key_secret=key_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # An API key is scoped to exactly one organization (the API documents this), usage_cost
        # windows advance forward, and activities are sorted client-side — so incremental rows
        # arrive in ascending order and the pipeline can checkpoint the watermark per batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
