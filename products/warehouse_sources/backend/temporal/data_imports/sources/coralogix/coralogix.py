import json
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.settings import (
    CORALOGIX_DOMAINS,
    CORALOGIX_ENDPOINTS,
    DEFAULT_LOOKBACK_DAYS,
    QUERY_LIMIT,
)

# The team's Coralogix domain must match the cluster its account lives on — a query against the
# wrong cluster fails outright, so the domain is a fixed choice on the source form.
TIERS = {
    "frequent_search": "TIER_FREQUENT_SEARCH",
    "archive": "TIER_ARCHIVE",
}

# Adaptive time-window slicing: the query API has no cursor pagination, only a per-query row cap,
# so we advance a [start, end) window through time. A window that hits the cap is bisected and
# retried; sparse windows grow back up to the max so quiet ranges don't cost one query per hour.
INITIAL_WINDOW = timedelta(hours=1)
MIN_WINDOW = timedelta(seconds=10)
MAX_WINDOW = timedelta(hours=24)

_MIN_DATETIME = datetime.min.replace(tzinfo=UTC)


class CoralogixRetryableError(Exception):
    """Raised for Coralogix responses that are safe to retry (429 / 5xx / mid-stream breaks)."""


@dataclasses.dataclass
class CoralogixResumeConfig:
    # ISO timestamp of the last fully-yielded window's end. Windows are half-open [start, end),
    # so resuming inclusively from this boundary neither skips nor re-yields rows.
    synced_until: str | None = None


def _query_url(domain: str) -> str:
    if domain not in CORALOGIX_DOMAINS:
        raise ValueError(f"Unknown Coralogix domain: {domain}")
    return f"https://api.{domain}/api/v1/dataprime/query"


def _make_session(api_key: str) -> requests.Session:
    """Session for all Coralogix traffic. The bearer token is set once on the session so its
    redaction policy applies everywhere, and redirects are pinned off so a credentialed request
    can't be replayed against another host. Response capture is disabled because log/span bodies
    are free-form user telemetry — they can carry credentials or PII the name-based sample
    scrubbers can't reliably recognise."""
    return make_tracked_session(
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        redact_values=(api_key,),
        allow_redirects=False,
        capture=False,
    )


def _format_datetime(dt: datetime) -> str:
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _parse_timestamp(value: Any) -> datetime | None:
    """Best-effort parse of a Coralogix timestamp into an aware UTC datetime.

    The query API's metadata timestamps are ISO 8601 strings, potentially with nanosecond
    precision (trimmed to microseconds — Python datetimes can't hold more). Numeric epochs are
    handled defensively by magnitude in case a cluster returns them instead.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, int | float):
        return _parse_epoch(float(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return _parse_epoch(float(stripped))
        except ValueError:
            pass
        iso = stripped.removesuffix("Z") + "+00:00" if stripped.endswith("Z") else stripped
        if "." in iso:
            head, _, tail = iso.partition(".")
            frac = ""
            offset = ""
            for index, char in enumerate(tail):
                if char.isdigit():
                    frac += char
                else:
                    offset = tail[index:]
                    break
            iso = f"{head}.{frac[:6]}{offset}"
        try:
            parsed = datetime.fromisoformat(iso)
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _parse_epoch(value: float) -> datetime:
    # Disambiguate epoch precision by magnitude: seconds (<1e11), millis, micros, nanos.
    for threshold, divisor in ((1e11, 1), (1e14, 1e3), (1e17, 1e6)):
        if abs(value) < threshold:
            return datetime.fromtimestamp(value / divisor, tz=UTC)
    return datetime.fromtimestamp(value / 1e9, tz=UTC)


def _normalize_row(result: dict[str, Any]) -> dict[str, Any]:
    """Flatten a query result row ({metadata: [{key, value}], labels: [...], userData: "..."}).

    Metadata keys (timestamp, severity, logid, ...) and label keys (applicationname,
    subsystemname, ...) become top-level columns; metadata wins on collision. The log/span body
    stays as the raw JSON string in `user_data` — flattening arbitrary user telemetry would
    produce an unstable column set.
    """
    row: dict[str, Any] = {}
    for pair in result.get("metadata") or []:
        key = pair.get("key")
        if key:
            row[key] = pair.get("value")
    for pair in result.get("labels") or []:
        key = pair.get("key")
        if key and key not in row:
            row[key] = pair.get("value")
    row["user_data"] = result.get("userData")
    row["timestamp"] = _parse_timestamp(row.get("timestamp"))
    return row


@retry(
    retry=retry_if_exception_type(
        (
            CoralogixRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            # Mid-stream connection break while consuming the NDJSON body.
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _run_query(
    session: requests.Session,
    url: str,
    dataprime_source: str,
    tier: str,
    start: datetime,
    end: datetime,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """Run one DataPrime query and parse its NDJSON stream into normalized rows.

    The stream interleaves `{"queryId": ...}`, `{"result": {"results": [...]}}`,
    `{"warning": ...}` and `{"statistics": ...}` lines; only result lines carry rows. The whole
    request/parse runs inside the retry so a mid-stream break re-issues the query.
    """
    body = {
        "query": f"source {dataprime_source}",
        "metadata": {
            "tier": tier,
            "syntax": "QUERY_SYNTAX_DATAPRIME",
            "startDate": _format_datetime(start),
            "endDate": _format_datetime(end),
            "limit": QUERY_LIMIT,
        },
    }

    response = session.post(url, json=body, stream=True, timeout=(10, 180))

    if response.status_code == 429 or response.status_code >= 500:
        raise CoralogixRetryableError(f"Coralogix API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Coralogix API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    rows: list[dict[str, Any]] = []
    for line in response.iter_lines():
        if not line:
            continue
        message = json.loads(line)
        result = message.get("result")
        if result is not None:
            rows.extend(_normalize_row(item) for item in result.get("results") or [])
            # The server honors the requested limit; stop reading defensively once we have it so
            # a misbehaving response can't grow memory unboundedly. Reaching the limit already
            # means the window gets bisected (or warned about) by the caller.
            if len(rows) >= QUERY_LIMIT:
                break
        elif "error" in message:
            raise Exception(f"Coralogix query error: {message['error']}")
        elif "warning" in message:
            logger.warning(f"Coralogix query warning: {message['warning']}")

    return rows


def _filter_and_sort(
    rows: list[dict[str, Any]], start: datetime, end: datetime, exclusive_start: bool
) -> list[dict[str, Any]]:
    """Enforce half-open [start, end) semantics client-side and sort ascending by timestamp.

    The API doesn't document whether startDate/endDate are inclusive, so the client filter is
    what guarantees adjacent windows never double-count a boundary row. `exclusive_start` drops
    rows at exactly the incremental watermark — they were yielded by the run that set it. Rows
    whose timestamp fails to parse are kept (they arrived inside this window server-side) and
    sort first so they never advance the watermark past parseable rows.
    """
    kept: list[dict[str, Any]] = []
    for row in rows:
        ts = row.get("timestamp")
        if isinstance(ts, datetime):
            if ts < start or ts >= end:
                continue
            if exclusive_start and ts == start:
                continue
        kept.append(row)
    kept.sort(key=lambda row: row["timestamp"] if isinstance(row.get("timestamp"), datetime) else _MIN_DATETIME)
    return kept


def get_rows(
    api_key: str,
    domain: str,
    tier: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoralogixResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CORALOGIX_ENDPOINTS[endpoint]
    session = _make_session(api_key)
    url = _query_url(domain)
    tier_value = TIERS.get(tier, TIERS["frequent_search"])

    end = datetime.now(UTC)
    last_value = _parse_timestamp(db_incremental_field_last_value) if should_use_incremental_field else None
    exclusive_start = last_value is not None
    start = last_value if last_value is not None else end - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.synced_until:
        resumed = _parse_timestamp(resume.synced_until)
        if resumed is not None and resumed > start:
            # `synced_until` is a half-open window boundary, so the inclusive restart is exact.
            start = resumed
            exclusive_start = False
            logger.debug(f"Coralogix: resuming {endpoint} from {resume.synced_until}")

    window = INITIAL_WINDOW
    cursor = start
    while cursor < end:
        window_end = min(cursor + window, end)
        rows = _run_query(session, url, config.dataprime_source, tier_value, cursor, window_end, logger)

        if len(rows) >= QUERY_LIMIT and window_end - cursor > MIN_WINDOW:
            # Cap hit — the API drops an arbitrary remainder, so bisect and re-query rather than
            # silently skipping rows.
            window = max((window_end - cursor) / 2, MIN_WINDOW)
            continue
        if len(rows) >= QUERY_LIMIT:
            logger.warning(
                f"Coralogix: {endpoint} window {_format_datetime(cursor)}..{_format_datetime(window_end)} still "
                f"hits the {QUERY_LIMIT}-row cap at the minimum window size; rows beyond the cap are skipped"
            )

        batch = _filter_and_sort(rows, cursor, window_end, exclusive_start)
        exclusive_start = False
        if batch:
            yield batch

        # Save AFTER yielding so a crash re-runs the last window rather than skipping it.
        resumable_source_manager.save_state(CoralogixResumeConfig(synced_until=_format_datetime(window_end)))
        cursor = window_end

        if len(rows) < QUERY_LIMIT // 4:
            window = min(window * 2, MAX_WINDOW)

    # A retry of a fully-walked run must start fresh from the new watermark, not resume mid-stream.
    resumable_source_manager.clear_state()


def coralogix_source(
    api_key: str,
    domain: str,
    tier: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoralogixResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = CORALOGIX_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            domain=domain,
            tier=tier,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Rows are sorted ascending within each window and windows advance chronologically, so the
        # stream is globally ascending and per-batch watermark checkpointing is safe.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="day",
        partition_keys=[endpoint_config.partition_key],
    )


def validate_credentials(api_key: str, domain: str) -> bool:
    """Cheapest probe that confirms the key is genuine and on the right cluster: a 1-row
    frequent-search query over the last few minutes. A wrong-cluster or invalid key returns 403."""
    end = datetime.now(UTC)
    body = {
        "query": "source logs | limit 1",
        "metadata": {
            "tier": TIERS["frequent_search"],
            "syntax": "QUERY_SYNTAX_DATAPRIME",
            "startDate": _format_datetime(end - timedelta(minutes=15)),
            "endDate": _format_datetime(end),
            "limit": 1,
        },
    }
    try:
        response = _make_session(api_key).post(_query_url(domain), json=body, timeout=30)
        return response.status_code == 200
    except Exception:
        return False
