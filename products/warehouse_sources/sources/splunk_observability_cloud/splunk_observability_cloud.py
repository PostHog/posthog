import re
import json
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.splunk_observability_cloud.settings import (
    DETECTOR_EVENTS_RESULT_CAP,
    EVENT_SEARCH_PAGE_SIZE,
    EVENT_SEARCH_RESULT_CAP,
    MAX_OFFSET,
    PAGE_SIZE,
    SIGNALFLOW_DEFAULT_LOOKBACK_DAYS,
    SPLUNK_OBSERVABILITY_CLOUD_ENDPOINTS,
    SYNTHETIC_RUNS_DEFAULT_LOOKBACK_DAYS,
    SYNTHETICS_PAGE_SIZE,
    SplunkObservabilityCloudEndpointConfig,
)

# Realms are short lowercase alphanumeric codes (us0, us1, eu0, jp0, ...). The realm is
# interpolated into the request hostname, so anything else is rejected up front — both to
# fail fast on typos and to stop a crafted "realm" from retargeting the stored token.
_REALM_RE = re.compile(r"^[a-z0-9]{1,32}$")

# Rows per yielded batch; the pipeline re-batches, this just bounds source-side memory.
_BATCH_SIZE = 5000

REQUEST_TIMEOUT_SECONDS = 60
# (connect, read) for the SignalFlow SSE stream; the read timeout applies between chunks,
# and historical computations emit control/data messages well within this.
STREAM_TIMEOUT_SECONDS = (30, 180)


class SplunkObservabilityCloudRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class SplunkObservabilityCloudResumeConfig:
    # Offset of the next page to fetch within the current endpoint (or current detector
    # for the detector_events fan-out).
    offset: int = 0
    # Stable bookmark for the detector_events fan-out: the detector currently being
    # processed. None for every other endpoint.
    detector_id: str | None = None
    # Bookmark for the synthetic_runs fan-out: the test and the page of its runs to fetch next,
    # plus the run window of the interrupted attempt. A retry keeps that window, so tests it
    # skips and tests it still reads cover the same time range.
    test_id: int | None = None
    page: int | None = None
    window_start: str | None = None
    window_end: str | None = None
    # Start of the current event search window. The search caps each query at 10,000
    # results, so a long history is read as a series of windows; `offset` is within it.
    event_start_ms: int | None = None
    # Ids of events at `event_start_ms` that an earlier window already yielded. A resumed full
    # refresh appends rows, so it must skip them again.
    event_boundary_ids: list[str] | None = None


def normalize_realm(realm: str) -> str:
    normalized = realm.strip().lower()
    if not _REALM_RE.match(normalized):
        raise ValueError(
            "Invalid Splunk Observability Cloud realm. Use the short realm code from your profile page (e.g. us0, eu0)."
        )
    return normalized


def _api_base_url(realm: str) -> str:
    return f"https://api.{normalize_realm(realm)}.signalfx.com"


def _stream_base_url(realm: str) -> str:
    return f"https://stream.{normalize_realm(realm)}.signalfx.com"


def _get_headers(access_token: str) -> dict[str, str]:
    # The Synthetics API documents Content-Type as required, also on GET requests.
    return {"X-SF-TOKEN": access_token, "Accept": "application/json", "Content-Type": "application/json"}


def _to_epoch_ms(value: Any) -> int:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    return int(value)


def _ms_to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _to_iso8601(value: Any) -> str:
    return (
        datetime.fromtimestamp(_to_epoch_ms(value) / 1000, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_iso8601(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


@retry_with_deadline(
    retry=retry_if_exception_type(
        (
            SplunkObservabilityCloudRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    method: str = "GET",
    json_body: Any = None,
) -> Any:
    response = session.request(method, url, headers=headers, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise SplunkObservabilityCloudRetryableError(
            f"Splunk Observability Cloud API error (retryable): status={response.status_code}, url={url}"
        )

    # Redirects are never followed (the session pins allow_redirects=False so the
    # X-SF-TOKEN header can't be replayed to another host); the API answers directly,
    # so a 3xx means the realm doesn't point at a real API tenant.
    if response.is_redirect:
        raise Exception(
            f"Splunk Observability Cloud returned a redirect, which usually means the realm is wrong. url={url}"
        )

    if not response.ok:
        logger.error(
            f"Splunk Observability Cloud API error: status={response.status_code}, body={response.text}, url={url}"
        )
        response.raise_for_status()

    return response.json()


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    query = urlencode({key: str(value) for key, value in params.items()})
    return f"{base_url}/v2{path}?{query}" if query else f"{base_url}/v2{path}"


def _extract_page(config: SplunkObservabilityCloudEndpointConfig, data: Any) -> list[dict[str, Any]]:
    if config.response_style == "wrapped":
        results = data.get(config.data_key) if isinstance(data, dict) else None
        results = results if isinstance(results, list) else []
    else:
        results = data if isinstance(data, list) else []
    return [row for row in results if isinstance(row, dict)]


def _paginate(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: SplunkObservabilityCloudEndpointConfig,
    logger: FilteringBoundLogger,
    path: str | None = None,
    extra_params: dict[str, Any] | None = None,
    start_offset: int = 0,
    on_page: Callable[[int | None], None] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk an offset/limit-paginated endpoint, yielding one list of rows per page.

    `on_page(next_offset | None)` is called after each page is yielded so callers can
    checkpoint resume state (None means the endpoint is exhausted).
    """
    offset = start_offset
    while True:
        params: dict[str, Any] = {"offset": offset, "limit": PAGE_SIZE}
        params.update(config.extra_params)
        params.update(extra_params or {})
        url = _build_url(base_url, path if path is not None else config.path, params)
        # The only POST endpoint is a search whose filters are all optional.
        json_body: dict[str, Any] | None = {} if config.method == "POST" else None
        data = _fetch(session, url, headers, logger, method=config.method, json_body=json_body)
        rows = _extract_page(config, data)

        if not rows:
            if on_page is not None:
                on_page(None)
            return

        offset += len(rows)
        has_more = len(rows) >= PAGE_SIZE and offset < MAX_OFFSET
        yield rows
        if on_page is not None:
            on_page(offset if has_more else None)

        if offset >= MAX_OFFSET:
            logger.warning(
                f"Splunk Observability Cloud: offset cap reached, truncating results. endpoint={config.name}, offset={offset}"
            )
        if not has_more:
            return


def _iter_detector_ids(
    session: requests.Session, base_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    detectors_config = SPLUNK_OBSERVABILITY_CLOUD_ENDPOINTS["detectors"]
    for page in _paginate(session, base_url, headers, detectors_config, logger):
        for row in page:
            detector_id = row.get("id")
            if detector_id:
                yield str(detector_id)


def _get_detector_event_rows(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: SplunkObservabilityCloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplunkObservabilityCloudResumeConfig],
    from_ms: int,
    to_ms: int,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every detector and pull its alert events within [from_ms, to_ms].

    The bookmark is the detector id (stable across runs, unlike a positional index) plus
    the offset within that detector. If the bookmarked detector was deleted between a
    crash and the retry, we start over from the first detector — merge dedupes re-pulled
    rows on the primary key.
    """
    detector_ids = list(_iter_detector_ids(session, base_url, headers, logger))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = detector_ids
    resume_offset = 0
    if resume is not None and resume.detector_id is not None and resume.detector_id in detector_ids:
        remaining = detector_ids[detector_ids.index(resume.detector_id) :]
        resume_offset = resume.offset
        logger.debug(
            f"Splunk Observability Cloud: resuming detector_events from detector_id={resume.detector_id}, offset={resume_offset}"
        )

    for index, detector_id in enumerate(remaining):
        path = config.path.format(detector_id=detector_id)

        def _checkpoint(next_offset: int | None, detector_id: str = detector_id) -> None:
            # Save AFTER the page is yielded so a crash re-yields the last page rather
            # than skipping it — merge dedupes on the primary key.
            if next_offset is None:
                return
            resumable_source_manager.save_state(
                SplunkObservabilityCloudResumeConfig(offset=next_offset, detector_id=detector_id)
            )
            if next_offset >= DETECTOR_EVENTS_RESULT_CAP:
                logger.warning(
                    f"Splunk Observability Cloud: detector events cap reached; older events may be truncated. detector_id={detector_id}"
                )

        for page in _paginate(
            session,
            base_url,
            headers,
            config,
            logger,
            path=path,
            extra_params={"from": from_ms, "to": to_ms},
            start_offset=resume_offset,
            on_page=_checkpoint,
        ):
            yield [_normalize_event_row(row) for row in page]

        resume_offset = 0

        # Advance the bookmark to the next detector so a crash between detectors resumes
        # in the right place.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(
                SplunkObservabilityCloudResumeConfig(offset=0, detector_id=remaining[index + 1])
            )


def _normalize_event_row(row: dict[str, Any]) -> dict[str, Any]:
    # Epoch-ms timestamps don't work as datetime incremental/partition fields, so surface
    # the event time as a real datetime.
    normalized = dict(row)
    normalized["timestamp"] = _ms_to_datetime(row.get("timestamp"))
    return normalized


def _has_next_page(data: Any) -> bool:
    return isinstance(data, dict) and bool(data.get("nextPageLink"))


def _iter_synthetic_test_ids(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplunkObservabilityCloudResumeConfig],
) -> list[int]:
    tests_config = SPLUNK_OBSERVABILITY_CLOUD_ENDPOINTS["synthetic_tests"]
    test_ids: list[int] = []
    page = 1
    while page <= MAX_OFFSET // SYNTHETICS_PAGE_SIZE:
        url = _build_url(base_url, tests_config.path, {"page": page, "perPage": SYNTHETICS_PAGE_SIZE})
        data = _fetch(session, url, headers, logger)
        rows = _extract_page(tests_config, data)
        test_ids.extend(int(row["id"]) for row in rows if row.get("id") is not None)
        # No rows were yielded yet, so resuming from the loaded state loses nothing.
        resumable_source_manager.safe_point()
        if not rows or not _has_next_page(data):
            break
        page += 1
    return test_ids


def _paginate_pages(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: SplunkObservabilityCloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplunkObservabilityCloudResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk a Synthetics page/perPage list endpoint, yielding one list of rows per page."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None and resume.page else 1
    while True:
        params = {**config.extra_params, "page": page, "perPage": SYNTHETICS_PAGE_SIZE}
        data = _fetch(session, _build_url(base_url, config.path, params), headers, logger)
        rows = _extract_page(config, data)
        has_more = bool(rows) and _has_next_page(data)
        if has_more and page * SYNTHETICS_PAGE_SIZE >= MAX_OFFSET:
            logger.warning(f"Splunk Observability Cloud: page cap reached, truncating results. endpoint={config.name}")
            has_more = False
        if has_more:
            resumable_source_manager.save_state(SplunkObservabilityCloudResumeConfig(page=page + 1))
        if rows:
            yield rows
        if not has_more:
            return
        page += 1


def _normalize_synthetic_run_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["timestamp"] = _parse_iso8601(row.get("timestamp"))
    return normalized


def _get_synthetic_run_rows(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: SplunkObservabilityCloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplunkObservabilityCloudResumeConfig],
    start_time: str,
    end_time: str,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every synthetic test and page through its runs within [start_time, end_time].

    The bookmark is the test id plus the next page of its runs. If the bookmarked test was
    deleted before the retry, the walk starts again from the first test; merge dedupes the
    rows it reads again.
    """
    test_ids = _iter_synthetic_test_ids(session, base_url, headers, logger, resumable_source_manager)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = test_ids
    page = 1
    if resume is not None and resume.test_id is not None and resume.test_id in test_ids:
        remaining = test_ids[test_ids.index(resume.test_id) :]
        page = resume.page or 1
        start_time = resume.window_start or start_time
        end_time = resume.window_end or end_time

    for index, test_id in enumerate(remaining):
        path = config.path.format(test_id=test_id)
        while True:
            params = {"page": page, "perPage": SYNTHETICS_PAGE_SIZE, "startTime": start_time, "endTime": end_time}
            data = _fetch(session, _build_url(base_url, path, params), headers, logger)
            rows = _extract_page(config, data)
            has_more = bool(rows) and _has_next_page(data)
            if has_more and page * SYNTHETICS_PAGE_SIZE >= MAX_OFFSET:
                logger.warning(
                    f"Splunk Observability Cloud: synthetic run page cap reached, truncating results. test_id={test_id}"
                )
                has_more = False

            if has_more:
                resumable_source_manager.save_state(
                    SplunkObservabilityCloudResumeConfig(
                        test_id=test_id, page=page + 1, window_start=start_time, window_end=end_time
                    )
                )
            elif index + 1 < len(remaining):
                resumable_source_manager.save_state(
                    SplunkObservabilityCloudResumeConfig(
                        test_id=remaining[index + 1], page=1, window_start=start_time, window_end=end_time
                    )
                )

            if rows:
                yield [_normalize_synthetic_run_row(row) for row in rows]
            else:
                resumable_source_manager.safe_point()

            if not has_more:
                break
            page += 1
        page = 1


def _get_event_search_rows(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: SplunkObservabilityCloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplunkObservabilityCloudResumeConfig],
    start_ms: int,
    end_ms: int,
) -> Iterator[list[dict[str, Any]]]:
    """Read every event in [start_ms, end_ms] from a windowed event search.

    One query returns at most 10,000 events, whatever the offset. The request sorts by event
    time, so when a window reaches the cap the next window starts at the latest timestamp
    read. Events at that timestamp that were already yielded are skipped.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    window_start = start_ms
    offset = 0
    if resume is not None and resume.event_start_ms is not None:
        window_start = resume.event_start_ms
        offset = resume.offset

    start_param, end_param = config.window_params
    already_yielded: set[str] = set(resume.event_boundary_ids or []) if resume is not None else set()
    latest_ms: int | None = None
    ids_at_latest: set[str] = set()

    while True:
        limit = min(EVENT_SEARCH_PAGE_SIZE, EVENT_SEARCH_RESULT_CAP - offset)
        params = {
            **config.extra_params,
            start_param: window_start,
            end_param: end_ms,
            "offset": offset,
            "limit": limit,
        }
        data = _fetch(session, _build_url(base_url, config.path, params), headers, logger)
        rows = _extract_page(config, data)

        for row in rows:
            timestamp = row.get("timestamp")
            if timestamp is None:
                continue
            timestamp = int(timestamp)
            if latest_ms is None or timestamp > latest_ms:
                latest_ms = timestamp
                ids_at_latest = set()
            if timestamp == latest_ms and row.get("id") is not None:
                ids_at_latest.add(str(row["id"]))

        offset += len(rows)
        next_state: SplunkObservabilityCloudResumeConfig | None = None
        if len(rows) >= limit and offset < EVENT_SEARCH_RESULT_CAP:
            next_state = SplunkObservabilityCloudResumeConfig(
                offset=offset, event_start_ms=window_start, event_boundary_ids=sorted(already_yielded)
            )
        elif len(rows) >= limit:
            if latest_ms is None:
                logger.warning("Splunk Observability Cloud: event search page had no timestamps; stopping the read")
            elif latest_ms <= window_start:
                # The search cannot page past this timestamp, so skip to the next millisecond
                # instead of stopping: later events, and later syncs, still make progress.
                logger.warning(
                    f"Splunk Observability Cloud: more than {EVENT_SEARCH_RESULT_CAP} events share one timestamp; "
                    f"some events at it are skipped. timestamp_ms={window_start}"
                )
                next_state = SplunkObservabilityCloudResumeConfig(offset=0, event_start_ms=window_start + 1)
            else:
                next_state = SplunkObservabilityCloudResumeConfig(
                    offset=0, event_start_ms=latest_ms, event_boundary_ids=sorted(ids_at_latest)
                )

        if next_state is not None:
            resumable_source_manager.save_state(next_state)

        fresh = [row for row in rows if row.get("id") is None or str(row["id"]) not in already_yielded]
        if fresh:
            yield [_normalize_event_row(row) for row in fresh]
        else:
            resumable_source_manager.safe_point()

        if next_state is None:
            return
        if next_state.event_start_ms != window_start:
            window_start = next_state.event_start_ms or window_start
            offset = 0
            already_yielded = ids_at_latest
            ids_at_latest = set(ids_at_latest)


def _iter_sse_events(response: requests.Response) -> Iterator[tuple[str, str]]:
    """Minimal Server-Sent Events parser: yields (event_name, data) per event."""
    event_name: str | None = None
    data_lines: list[str] = []
    for line in response.iter_lines(decode_unicode=True):
        if line is None:
            continue
        if line == "":
            if data_lines:
                yield event_name or "message", "\n".join(data_lines)
            event_name = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if data_lines:
        yield event_name or "message", "\n".join(data_lines)


def _get_signalflow_rows(
    session: requests.Session,
    realm: str,
    access_token: str,
    program: str,
    start_ms: int,
    stop_ms: int,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Run a SignalFlow computation over [start_ms, stop_ms] and yield datapoint rows.

    The computation streams back as Server-Sent Events: `metadata` messages describe each
    output time series ({tsId, properties}), `data` messages carry one batch of values per
    logical timestamp ({logicalTimestampMs, data: [{tsId, value}]}), and a final
    END_OF_CHANNEL control message closes the stream. Message shapes follow the official
    SignalFlow SSE transport (signalfx-python).
    """
    url = f"{_stream_base_url(realm)}/v2/signalflow/execute"
    params = {"start": str(start_ms), "stop": str(stop_ms), "immediate": "true"}
    headers = {"X-SF-TOKEN": access_token, "Content-Type": "text/plain"}

    response = session.post(
        url,
        params=params,
        data=program.encode("utf-8"),
        headers=headers,
        stream=True,
        timeout=STREAM_TIMEOUT_SECONDS,
    )
    # A 3xx passes `response.ok`, and the session never follows redirects (token
    # replay protection) — fail loudly instead of ending the stream empty.
    if response.is_redirect:
        raise Exception(
            "Splunk Observability Cloud SignalFlow returned a redirect, which usually means the realm is wrong"
        )
    if not response.ok:
        logger.error(
            f"Splunk Observability Cloud SignalFlow error: status={response.status_code}, body={response.text[:2000]}"
        )
        response.raise_for_status()

    metadata_by_tsid: dict[str, dict[str, Any]] = {}
    batch: list[dict[str, Any]] = []

    try:
        for event_name, data in _iter_sse_events(response):
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                logger.warning(
                    f"Splunk Observability Cloud: skipping undecodable SignalFlow message. event={event_name}"
                )
                continue

            if event_name == "metadata":
                metadata_by_tsid[payload["tsId"]] = payload.get("properties") or {}
            elif event_name == "data":
                timestamp = _ms_to_datetime(payload.get("logicalTimestampMs"))
                for datum in payload.get("data", []):
                    tsid = datum.get("tsId")
                    properties = metadata_by_tsid.get(tsid, {})
                    batch.append(
                        {
                            "tsId": tsid,
                            "timestamp": timestamp,
                            "value": datum.get("value"),
                            "metric": properties.get("sf_metric"),
                            # Dimensions vary per time series, so keep them as one JSON column
                            # instead of exploding an unbounded set of columns.
                            "properties": json.dumps(properties) if properties else None,
                        }
                    )
                if len(batch) >= _BATCH_SIZE:
                    yield batch
                    batch = []
            elif event_name == "error":
                raise Exception(f"SignalFlow computation failed: {payload.get('errors')}")
            elif event_name == "control-message":
                control_event = payload.get("event")
                if control_event == "CHANNEL_ABORT":
                    raise Exception(f"SignalFlow computation aborted: {payload.get('abortInfo')}")
                if control_event == "END_OF_CHANNEL":
                    break
    finally:
        response.close()

    if batch:
        yield batch


def get_rows(
    realm: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplunkObservabilityCloudResumeConfig],
    signalflow_program: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SPLUNK_OBSERVABILITY_CLOUD_ENDPOINTS[endpoint]
    base_url = _api_base_url(realm)
    headers = _get_headers(access_token)
    # allow_redirects=False pins every credentialed request to the Splunk hosts:
    # requests only strips `Authorization` on a cross-host redirect, so a followed
    # redirect would replay the X-SF-TOKEN header to whatever host the 3xx names.
    # capture=False: detector/dashboard/chart response bodies and the SignalFlow
    # program hold arbitrary customer content the name-based scrubber can't redact.
    session = make_tracked_session(redact_values=(access_token,), allow_redirects=False, capture=False)
    now_ms = _to_epoch_ms(datetime.now(UTC))

    if config.uses_signalflow:
        program = (signalflow_program or "").strip()
        if not program:
            raise ValueError(
                "The metric_time_series table requires a SignalFlow program. Edit the source and fill in the "
                "'SignalFlow program' field (e.g. data('cpu.utilization').publish())."
            )
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            start_ms = _to_epoch_ms(db_incremental_field_last_value)
        else:
            start_ms = now_ms - int(timedelta(days=SIGNALFLOW_DEFAULT_LOOKBACK_DAYS).total_seconds() * 1000)
        yield from _get_signalflow_rows(session, realm, access_token, program, start_ms, now_ms, logger)
        return

    if config.pagination == "none":
        rows = _extract_page(
            config, _fetch(session, _build_url(base_url, config.path, config.extra_params), headers, logger)
        )
        if rows:
            yield rows
        return

    if config.fan_out_over_synthetic_tests:
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            start_time = _to_iso8601(db_incremental_field_last_value)
        else:
            start_time = _to_iso8601(
                now_ms - int(timedelta(days=SYNTHETIC_RUNS_DEFAULT_LOOKBACK_DAYS).total_seconds() * 1000)
            )
        yield from _get_synthetic_run_rows(
            session, base_url, headers, config, logger, resumable_source_manager, start_time, _to_iso8601(now_ms)
        )
        return

    if config.pagination == "page":
        yield from _paginate_pages(session, base_url, headers, config, logger, resumable_source_manager)
        return

    if config.is_event_search:
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            start_ms = _to_epoch_ms(db_incremental_field_last_value)
        else:
            start_ms = 0
        yield from _get_event_search_rows(
            session, base_url, headers, config, logger, resumable_source_manager, start_ms, now_ms
        )
        return

    if config.fan_out_over_detectors:
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            from_ms = _to_epoch_ms(db_incremental_field_last_value)
        else:
            from_ms = 0
        yield from _get_detector_event_rows(
            session, base_url, headers, config, logger, resumable_source_manager, from_ms, now_ms
        )
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_offset = resume.offset if resume is not None else 0

    def _checkpoint(next_offset: int | None) -> None:
        # Save AFTER the page is yielded so a crash re-yields the last page rather than
        # skipping it — merge dedupes on the primary key.
        if next_offset is not None:
            resumable_source_manager.save_state(SplunkObservabilityCloudResumeConfig(offset=next_offset))

    yield from _paginate(
        session,
        base_url,
        headers,
        config,
        logger,
        start_offset=start_offset,
        on_page=_checkpoint,
    )


def splunk_observability_cloud_source(
    realm: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplunkObservabilityCloudResumeConfig],
    signalflow_program: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = SPLUNK_OBSERVABILITY_CLOUD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            realm=realm,
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            signalflow_program=signalflow_program,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        sort_mode=_sort_mode(endpoint_config),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def _sort_mode(config: SplunkObservabilityCloudEndpointConfig) -> Literal["asc", "desc"] | None:
    # The detector_events fan-out is not globally time-ordered (events arrive grouped
    # by detector), so declare desc to persist the incremental watermark only at
    # successful job end instead of checkpointing a misleading per-batch max.
    if config.fan_out_over_detectors:
        return "desc"
    # Synthetic runs arrive grouped by test. The event search restarts its window at the
    # cap, and its sort field is not documented as the same value as the row timestamp.
    if config.fan_out_over_synthetic_tests or config.is_event_search:
        return None
    # SignalFlow data messages stream in ascending logical-timestamp order.
    return "asc"


def validate_credentials(realm: str, access_token: str) -> tuple[bool, str | None]:
    try:
        base_url = _api_base_url(realm)
    except ValueError as e:
        return False, str(e)

    try:
        # One cheap probe: /v2/organization answers for any valid API-scoped token.
        # allow_redirects=False so the X-SF-TOKEN header can't be replayed off-host.
        # capture=False: the org response body carries arbitrary customer content.
        response = make_tracked_session(redact_values=(access_token,), allow_redirects=False, capture=False).get(
            f"{base_url}/v2/organization",
            headers=_get_headers(access_token),
            timeout=10,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Splunk Observability Cloud access token or realm"
    if response.is_redirect:
        return False, "Splunk Observability Cloud redirected the request, which usually means the realm is wrong"
    return False, f"Splunk Observability Cloud returned an unexpected status code: {response.status_code}"
