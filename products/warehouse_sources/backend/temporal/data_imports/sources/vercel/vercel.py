import json
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
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.settings import (
    VERCEL_ENDPOINTS,
    VercelEndpointConfig,
)

VERCEL_BASE_URL = "https://api.vercel.com"

# Vercel caps the page size at 100 (default 20); request the max to minimize round-trips.
PAGE_SIZE = 100

# billing_charges backfill: the endpoint caps the `from`/`to` window at one year. A day-floored start
# 364 days back keeps the window strictly under that cap once `to` runs to the current instant.
BILLING_BACKFILL_DAYS = 364

# FOCUS measure fields — the amounts that change when a charge is restated. Everything else on the
# record is an identity/dimension field, so the synthetic id hashes all-but-these and a restated
# charge keeps its id (merge updates it in place instead of inserting a duplicate).
BILLING_MEASURE_FIELDS = frozenset({"BilledCost", "EffectiveCost", "ConsumedQuantity", "PricingQuantity"})

# Backstop against an endpoint that silently ignores the `until` cursor (which would otherwise
# re-serve page one forever). Resumable state means an interrupted sync picks back up, so this is
# a runaway guard, not a coverage limit — at 100 rows/page it allows ~1M rows before warning.
MAX_PAGES = 10_000

# Shown when the token check can't reach a verdict because Vercel is unreachable or returned a
# transient error (network failure, 429, 5xx). The token may be perfectly valid, so pointing the
# user at their credentials would send them chasing a problem they can't fix.
_VERCEL_UNREACHABLE_ERROR = "Couldn't reach Vercel to validate your access token. Please try again in a few minutes."


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


def _ms_to_iso8601(ms: int) -> str:
    """Convert a Unix-ms cursor value to the ISO 8601 UTC string format some Vercel endpoints
    (e.g. events) expect for `since`/`until` — see `VercelEndpointConfig.since_until_as_iso`."""
    seconds, millis = divmod(ms, 1000)
    return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def _build_params(
    config: VercelEndpointConfig,
    team_id: str | None,
    since_value: Any,
    until: int | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, **config.extra_params}

    if config.team_scoped and team_id:
        params["teamId"] = team_id

    if config.since_param and since_value is not None:
        params[config.since_param] = _ms_to_iso8601(since_value) if config.since_until_as_iso else since_value

    if until is not None:
        params["until"] = _ms_to_iso8601(until) if config.since_until_as_iso else until

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


def _cursor_from_page(items: list[dict[str, Any]], field_name: str) -> int | None:
    """Next `until` cursor for an endpoint that returns rows but no `pagination` envelope.

    Rows arrive newest-first, so the oldest timestamp on this page bounds the next one. The value is
    fed back unmodified rather than decremented: `until` is inclusive, so the boundary row is
    re-fetched and merge dedupes it on the primary key, whereas stepping back a millisecond would
    drop any row sharing that exact timestamp. A page whose rows all share one timestamp can't
    advance the cursor; the caller's non-advancing-cursor guard ends the walk there.
    """
    timestamps = [item[field_name] for item in items if isinstance(item.get(field_name), int)]
    return min(timestamps) if timestamps else None


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    """Confirm the access token is genuine via GET /v2/user — the cheapest authenticated probe,
    available to any valid Vercel token regardless of team scope or resource permissions."""
    try:
        response = make_tracked_session().get(
            f"{VERCEL_BASE_URL}/v2/user", headers=_get_headers(access_token), timeout=10
        )
    except requests.exceptions.RequestException:
        # A network failure or timeout is transient and unrelated to the token; the raw exception
        # embeds the URL and gives the user nothing actionable.
        return False, _VERCEL_UNREACHABLE_ERROR

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return (
            False,
            "Your Vercel access token is invalid or has been revoked. Create a new token in your Vercel account settings, then reconnect.",
        )
    if response.status_code == 403:
        return (
            False,
            "Your Vercel access token is not authorized for this resource. Check the token's scope (and team access), then reconnect.",
        )
    # 429 (rate limit) and 5xx are transient Vercel-side problems, not a bad token, so surface a
    # retry hint rather than telling the user to fix credentials they can't fix.
    if response.status_code == 429 or response.status_code >= 500:
        return False, _VERCEL_UNREACHABLE_ERROR
    return (
        False,
        "Couldn't validate your Vercel access token. Check that it's a valid token from your Vercel account settings, then try again.",
    )


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
        if next_until is None and config.cursor_from_field:
            next_until = _cursor_from_page(items, config.cursor_from_field)
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


def _iter_parent_rows(
    session: requests.Session,
    config: VercelEndpointConfig,
    team_id: str | None,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """Page a flat parent endpoint to completion and yield every row, for a fan-out child to seed
    its per-parent requests from. Full refresh: no incremental cutoff is applied, so every parent is
    visited each sync. Reuses the same cursor model as `get_rows` (walk `pagination.next` back as
    `until`, or derive it from the oldest row when the endpoint carries no envelope)."""
    until: int | None = None
    page_count = 0
    while True:
        url = _build_url(config.path, _build_params(config, team_id, None, until))
        data = _fetch_page(session, url, headers, logger)

        items = data.get(config.response_data_key) or []
        if not items:
            return
        yield from items

        next_until = (data.get("pagination") or {}).get("next")
        if next_until is None and config.cursor_from_field:
            next_until = _cursor_from_page(items, config.cursor_from_field)

        page_count += 1
        if next_until is None:
            return
        if next_until == until:
            logger.warning(f"Vercel: {config.name} pagination cursor did not advance (until={until}); stopping")
            return
        if page_count >= MAX_PAGES:
            logger.warning(f"Vercel: {config.name} hit MAX_PAGES={MAX_PAGES}; remaining pages skipped")
            return
        until = next_until


def get_fanout_rows(
    access_token: str,
    endpoint: str,
    team_id: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[Any]:
    """Fan out a child endpoint over every row of its parent: page the parent to completion, then
    issue one GET per parent id with the id filled into the child path's `{fan_out_path_param}`.

    Full refresh only. The child endpoint (check_runs) returns its whole list in one response with no
    pagination envelope, so each per-parent call is a single fetch. A parent row missing the fan-out
    field is skipped rather than crashing the sync."""
    config = VERCEL_ENDPOINTS[endpoint]
    assert config.fan_out_parent is not None and config.fan_out_path_param is not None
    parent_config = VERCEL_ENDPOINTS[config.fan_out_parent]
    headers = _get_headers(access_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session()

    try:
        for parent in _iter_parent_rows(session, parent_config, team_id, headers, logger):
            parent_id = parent.get(config.fan_out_parent_field)
            if parent_id is None:
                continue

            child_path = config.path.format(**{config.fan_out_path_param: parent_id})
            # The child endpoint documents no `limit`/pagination params, so build a minimal param set
            # rather than reusing `_build_params` (which always appends `limit`).
            params: dict[str, Any] = {**config.extra_params}
            if config.team_scoped and team_id:
                params["teamId"] = team_id

            data = _fetch_page(session, _build_url(child_path, params), headers, logger)
            for item in data.get(config.response_data_key) or []:
                batcher.batch(item)
                if batcher.should_yield():
                    yield batcher.get_table()

        if batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()
    finally:
        session.close()


def _iso8601_utc(moment: datetime) -> str:
    """Vercel's billing window params want ISO 8601 UTC with a trailing Z, e.g.
    2025-01-01T00:00:00.000Z."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _coerce_datetime(value: Any) -> datetime:
    """Normalize a watermark (datetime, date, or ISO string) to a UTC-aware datetime."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime_time.min, tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _floor_to_day(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _focus_charge_id(record: dict[str, Any]) -> str:
    """Deterministic surrogate id for a FOCUS charge row.

    FOCUS records carry no id. The 1-day grain is defined by the charge's identity/dimension fields
    (period, service, region, pricing dimensions, and the project carried in Tags), so hashing every
    field except the amounts yields a stable key: a charge whose cost is restated between runs keeps
    its id and merge updates it in place instead of inserting a duplicate."""
    dimensions = {k: v for k, v in record.items() if k not in BILLING_MEASURE_FIELDS}
    # sort_keys makes the serialization order-independent; default=str tolerates any nested value.
    serialized = json.dumps(dimensions, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _billing_window_start(
    should_use_incremental_field: bool, db_incremental_field_last_value: Any, now: datetime
) -> datetime:
    """Start of the `from`/`to` window to request.

    Incremental: the pipeline has already shifted the stored watermark back by the schema's lookback,
    so we day-floor it (keeping `from` aligned to Vercel's day buckets) and re-read from there. First
    sync / full refresh: go back the full backfill window. Either way, never start earlier than the
    endpoint's one-year cap."""
    floor_today = _floor_to_day(now)
    cap = floor_today - timedelta(days=BILLING_BACKFILL_DAYS)

    if should_use_incremental_field and db_incremental_field_last_value:
        start = min(_floor_to_day(_coerce_datetime(db_incremental_field_last_value)), floor_today)
    else:
        start = cap

    return max(start, cap)


@retry(
    retry=retry_if_exception_type((VercelRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _open_billing_stream(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    response = session.get(url, headers=headers, timeout=120, stream=True)

    if response.status_code == 429 or response.status_code >= 500:
        response.close()
        raise VercelRetryableError(f"Vercel API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        body = response.text
        response.close()
        logger.error(f"Vercel API error: status={response.status_code}, body={body}, url={url}")
        response.raise_for_status()

    return response


def get_billing_rows(
    access_token: str,
    endpoint: str,
    team_id: str | None,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    """Stream FOCUS v1.3 billing charges as newline-delimited JSON over a `from`/`to` window, stamp a
    synthetic id on each record, and yield them sorted by charge period ascending.

    Incremental runs re-read a trailing overlap window (the pipeline shifts the watermark back by the
    schema lookback) so restated charges are re-pulled; merge dedupes them on the synthetic id. The
    ascending sort upholds the `sort_mode="asc"` contract so the pipeline checkpoints the watermark
    correctly."""
    config = VERCEL_ENDPOINTS[endpoint]
    now = datetime.now(UTC)
    window_start = _billing_window_start(should_use_incremental_field, db_incremental_field_last_value, now)

    params: dict[str, Any] = {"from": _iso8601_utc(window_start), "to": _iso8601_utc(now)}
    if config.team_scoped and team_id:
        params["teamId"] = team_id

    url = _build_url(config.path, params)
    headers = _get_headers(access_token)
    session = make_tracked_session()

    try:
        # Response order is undocumented, and the pipeline's ascending watermark contract requires rows
        # to arrive oldest-first. Billing volume at 1-day granularity is small, so buffer the window and
        # sort it client-side rather than trusting the stream order.
        records: list[dict[str, Any]] = []
        response = _open_billing_stream(session, url, headers, logger)
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                record = json.loads(line)
                record["id"] = _focus_charge_id(record)
                records.append(record)
        finally:
            response.close()

        records.sort(key=lambda r: r.get("ChargePeriodStart") or "")

        batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
        for record in records:
            batcher.batch(record)
            if batcher.should_yield():
                yield batcher.get_table()

        if batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()
    finally:
        session.close()


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

    if endpoint_config.is_focus_billing:
        return SourceResponse(
            name=endpoint,
            items=lambda: get_billing_rows(
                access_token=access_token,
                endpoint=endpoint,
                team_id=team_id,
                logger=logger,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            ),
            primary_keys=[endpoint_config.primary_key],
            # Records are sorted by charge period ascending before yielding; the pipeline checkpoints
            # the watermark per batch.
            sort_mode="asc",
            partition_count=1,
            partition_size=1,
            partition_mode="datetime" if endpoint_config.partition_key else None,
            partition_format="month" if endpoint_config.partition_key else None,
            partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        )

    if endpoint_config.fan_out_parent is not None:
        return SourceResponse(
            name=endpoint,
            items=lambda: get_fanout_rows(
                access_token=access_token,
                endpoint=endpoint,
                team_id=team_id,
                logger=logger,
            ),
            primary_keys=[endpoint_config.primary_key],
            # Full-refresh fan-out with no incremental field, so sort_mode drives no watermark; kept
            # consistent with the resource endpoints below.
            sort_mode="desc",
        )

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
