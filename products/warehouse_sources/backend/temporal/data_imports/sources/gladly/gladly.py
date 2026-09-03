import io
import re
import csv
import json
import time
import hashlib
import dataclasses
from collections.abc import Buffer, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import (
    GLADLY_ENDPOINTS,
    REPORT_ROW_ID_COLUMN,
    GladlyEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 300
# 10 req/s per org; back off on 429.
MAX_RETRY_ATTEMPTS = 5
# Yield JSONL rows in chunks so big files don't build one giant list.
CHUNK_SIZE = 5000
# Pull the report CSV off the wire in 64 KiB reads.
REPORT_CHUNK_BYTES = 1 << 16
# Gladly caps report CSVs (100k rows for most reports) and truncates silently,
# so a window this full is likely missing rows.
REPORT_ROW_WARNING_THRESHOLD = 90_000
# The reports endpoint allows 10 requests per minute per org, so backfill
# windows are paced instead of riding the 429 backoff.
REPORT_REQUEST_INTERVAL_SECONDS = 6.0

# Gladly serves production on gladly.com and the testing sandbox on gladly.qa. The
# config field is typed as a Literal, but nothing validates Literal membership at
# runtime, so the domain is checked against this tuple before it reaches a URL. An
# unchecked value would send the Basic-auth credentials to an arbitrary host.
ALLOWED_DOMAINS = ("gladly.com", "gladly.qa")
DEFAULT_DOMAIN = "gladly.com"


class GladlyRetryableError(Exception):
    pass


class GladlyReportHeaderError(Exception):
    """A report body whose header is missing the columns the stream is keyed on.

    A body that isn't the promised CSV still parses: its first line becomes the
    header, so the rows come out carrying junk columns or nothing but the injected
    `_row_id`, and the sync then fails much later with a misleading complaint about
    the incremental field. Stop at the source instead. Keep the message matching
    the entry in the source's non-retryable errors.
    """

    def __init__(self, metric_set: str, missing: list[str], present: list[str]) -> None:
        super().__init__(
            f"Gladly report is missing required columns {missing} for metricSet={metric_set}. "
            f"Columns returned: {present!r:.300}"
        )


class _ResponseByteStream(io.RawIOBase):
    """Read a streaming response body through ``iter_content`` as a binary file.

    Wrapping ``response.raw`` directly crashes on an empty report body: urllib3
    closes the connection the moment it reads EOF, and a ``TextIOWrapper`` over
    the now-closed raw stream raises ``ValueError: I/O operation on closed file``.
    ``iter_content`` yields nothing for an empty body and turns a dropped
    connection into a retryable ``requests`` error mid-stream.
    """

    def __init__(self, response: requests.Response, chunk_size: int) -> None:
        self._chunks = response.iter_content(chunk_size=chunk_size)
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def readinto(self, target: Buffer) -> int:
        while not self._buffer:
            try:
                self._buffer = next(self._chunks)
            except StopIteration:
                return 0
        view = memoryview(target).cast("B")
        take = min(len(view), len(self._buffer))
        view[:take] = self._buffer[:take]
        self._buffer = self._buffer[take:]
        return take


@dataclasses.dataclass
class GladlyResumeConfig:
    # Jobs are processed oldest-first; persisting the last fully-processed
    # job's updatedAt lets a retried sync skip straight past it.
    last_job_updated_at: str | None = None
    # Report streams persist the end date (YYYY-mm-dd) of the last fully-processed
    # window; a retried sync restarts at that date and merge dedupes the overlap.
    last_report_window_end: str | None = None


def _get_session(agent_email: str, api_token: str) -> requests.Session:
    session = make_tracked_session(redact_values=(api_token,))
    session.auth = (agent_email, api_token)
    return session


def _clean_organization(organization: str) -> str:
    """Accept the bare org subdomain, a region-qualified one like myorg.us-1, or a pasted full domain/URL."""
    org = organization.strip().removeprefix("https://").removeprefix("http://")
    org = org.split("/")[0]
    if org.lower().endswith(".gladly.com"):
        org = org[: -len(".gladly.com")]
    # One optional extra label covers Gladly's region-sharded orgs (myorg.us-1.gladly.com);
    # the charset keeps the credentials pinned to a subdomain of gladly.com.
    if not re.fullmatch(r"[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)?", org):
        raise ValueError(
            "Invalid Gladly organization. Enter the part of your Gladly URL before .gladly.com. "
            "For myorg.gladly.com enter myorg. For myorg.us-1.gladly.com enter myorg.us-1."
        )
    return org


def _clean_domain(domain: str) -> str:
    value = domain.strip().lower()
    if value not in ALLOWED_DOMAINS:
        raise ValueError(f"Invalid Gladly domain. Choose one of: {', '.join(ALLOWED_DOMAINS)}.")
    return value


def _host(organization: str, domain: str = DEFAULT_DOMAIN) -> str:
    return f"{_clean_organization(organization)}.{_clean_domain(domain)}"


def _base_url(organization: str, domain: str = DEFAULT_DOMAIN) -> str:
    return f"https://{_host(organization, domain)}/api/v1"


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def _normalize_report_column(name: str) -> str:
    """Turn a report CSV header like "Assigned Agent ID" into a stable warehouse
    column name ("assigned_agent_id"). Output is limited to [a-z0-9_] so the
    pipeline's own identifier normalization leaves it unchanged, keeping the
    declared primary key and incremental field aligned with the data.
    """
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _report_csv_lines(stream: io.TextIOBase) -> Iterator[str]:
    """Yield the report body with any blank lines before the header removed.

    csv.DictReader takes the first line it reads as the header, so a leading blank
    line becomes a single empty field name and every real column is then dropped
    from the rows that follow. Lines keep their terminators, so csv still
    reassembles values that contain a newline inside quotes.
    """
    header_seen = False
    for line in stream:
        if not header_seen:
            if not line.strip():
                continue
            header_seen = True
        yield line


def _report_row_id(row: dict[str, Any]) -> str:
    """Deterministic id for report rows that carry no natural key.

    Timestamps-report rows are immutable events with no event id column, so the
    id is a hash of the whole normalized row: the same row re-read from an
    overlapping window merges onto itself, while rows differing in any field
    stay distinct.
    """
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _report_start_date(
    today: date,
    incremental_last_value: Any,
    resume_window_end: str | None,
    window_days: int,
    backfill_days: int,
    logger: FilteringBoundLogger,
) -> date:
    start = today - timedelta(days=backfill_days)

    if incremental_last_value is not None:
        try:
            watermark = date.fromisoformat(_format_timestamp(incremental_last_value)[:10])
        except ValueError:
            logger.warning(
                f"Gladly: could not parse incremental watermark {incremental_last_value!r}; "
                f"re-reading the full report history"
            )
        else:
            # Rows inside a window arrive in no guaranteed order and report data
            # trails live activity, so a crashed sync can leave the watermark past
            # rows it never loaded. Starting one full window behind covers them;
            # merge dedupes the overlap.
            start = max(start, watermark - timedelta(days=window_days))

    if resume_window_end is not None:
        try:
            # The saved window is re-read rather than skipped: its endAt day was
            # still accumulating rows when the window was first processed.
            start = max(start, date.fromisoformat(resume_window_end))
        except ValueError:
            logger.warning(f"Gladly: ignoring malformed resume state {resume_window_end!r}")

    return min(start, today)


def validate_credentials(
    organization: str, agent_email: str, api_token: str, domain: str = DEFAULT_DOMAIN
) -> tuple[bool, str | None]:
    """Confirm the credentials are valid with a cheap agents probe.

    A wrong subdomain, an agent missing the API User permission, and a bad token each
    need a different fix, so they are reported separately. Returning one generic
    message for every outcome leaves the user nothing to act on, and hides an
    unreachable host or a Gladly outage behind a credentials error.
    """
    try:
        base_url = _base_url(organization, domain)
        host = _host(organization, domain)
    except ValueError as e:
        return False, str(e)

    try:
        response = _get_session(agent_email, api_token).get(
            f"{base_url}/agents",
            timeout=15,
        )
    except Exception:
        # The tracked session already logs the URL and exception class, so the message
        # stays readable instead of surfacing urllib3 retry and TLS internals.
        return False, f"Could not connect to Gladly at {host}. Check your organization subdomain."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Gladly authentication failed. Check your agent email and API token."
    if response.status_code == 403:
        return False, (
            "Gladly denied access. Check that the agent has the API User permission, "
            "under Settings > API Tokens in Gladly."
        )
    if response.status_code == 404:
        return False, f"No Gladly organization found at {host}. Check your organization subdomain."
    return False, f"Gladly returned an unexpected status: {response.status_code}"


def get_rows(
    organization: str,
    agent_email: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GladlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    domain: str = DEFAULT_DOMAIN,
) -> Iterator[list[dict[str, Any]]]:
    config = GLADLY_ENDPOINTS[endpoint]
    session = _get_session(agent_email, api_token)
    base_url = _base_url(organization, domain)

    if config.report_metric_set is not None:
        yield from _report_rows(
            session=session,
            base_url=base_url,
            config=config,
            metric_set=config.report_metric_set,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
        return

    filename = config.filename
    if filename is None:
        raise ValueError(f"Gladly endpoint {endpoint} declares neither an export filename nor a report metric set")

    @retry(
        retry=retry_if_exception_type((GladlyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def fetch(url: str) -> requests.Response:
        # stream=True keeps the large JSONL export files off the heap — iter_lines()
        # then streams them. The small jobs-list call still works with .json().
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)

        if response.status_code == 429 or response.status_code >= 500:
            raise GladlyRetryableError(f"Gladly API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Gladly API error: status={response.status_code}, body={response.text[:500]}, url={url}")
            response.raise_for_status()

        return response

    # The cutoff is the later of the incremental watermark and the resume
    # state, so retried syncs skip already-processed jobs either way.
    cutoff: Optional[str] = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        cutoff = _format_timestamp(db_incremental_field_last_value)
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if (
        resume_config is not None
        and resume_config.last_job_updated_at is not None
        and (cutoff is None or resume_config.last_job_updated_at > cutoff)
    ):
        cutoff = resume_config.last_job_updated_at
        logger.debug(f"Gladly: resuming {endpoint} after job updatedAt {cutoff}")

    jobs_body = fetch(f"{base_url}/export/jobs?{urlencode({'status': 'COMPLETED'})}").json()
    jobs = jobs_body if isinstance(jobs_body, list) else []
    jobs = [job for job in jobs if job.get("updatedAt")]
    jobs.sort(key=lambda job: job["updatedAt"])

    for job in jobs:
        job_updated_at = job["updatedAt"]
        # Strict less-than: jobs sharing the cutoff timestamp are re-yielded rather
        # than skipped, so a late-arriving job with the same updatedAt as the
        # watermark isn't lost. Merge-on-id dedupes the boundary job's re-yielded rows.
        if cutoff is not None and job_updated_at < cutoff:
            continue

        files = job.get("files") or []
        if filename not in files:
            continue

        # id is required per the export contract and is needed for the download
        # URL — a missing one is a broken API response, so fail loud.
        job_id = job["id"]

        response = fetch(f"{base_url}/export/jobs/{quote(job_id)}/files/{quote(filename)}")
        chunk: list[dict[str, Any]] = []
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"Gladly: skipping malformed JSONL line in job {job_id} {filename}")
                continue
            chunk.append({**row, "_job_id": job_id, "_job_updated_at": job_updated_at})
            if len(chunk) >= CHUNK_SIZE:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

        # Save state AFTER the job's file is fully yielded so a crash re-yields
        # this job (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(GladlyResumeConfig(last_job_updated_at=job_updated_at))


def _report_rows(
    session: requests.Session,
    base_url: str,
    config: GladlyEndpointConfig,
    metric_set: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GladlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    @retry(
        retry=retry_if_exception_type((GladlyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def generate_report(payload: dict[str, str]) -> requests.Response:
        # stream=True so the CSV body is parsed off the wire instead of loaded whole.
        response = session.post(f"{base_url}/reports", json=payload, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)

        if response.status_code == 429 or response.status_code >= 500:
            raise GladlyRetryableError(
                f"Gladly API error (retryable): status={response.status_code}, metricSet={metric_set}"
            )

        if not response.ok:
            logger.error(
                f"Gladly API error: status={response.status_code}, body={response.text[:500]}, metricSet={metric_set}"
            )
            response.raise_for_status()

        return response

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    today = datetime.now(UTC).date()
    window_start = _report_start_date(
        today=today,
        incremental_last_value=db_incremental_field_last_value if should_use_incremental_field else None,
        resume_window_end=resume_config.last_report_window_end if resume_config is not None else None,
        window_days=config.report_window_days,
        backfill_days=config.report_backfill_days,
        logger=logger,
    )
    inject_row_id = config.primary_key == REPORT_ROW_ID_COLUMN
    # The columns the stream is keyed on. An injected `_row_id` is built from the row
    # rather than read from the report, so it is never required of the header.
    required_columns = {incremental_field["field"] for incremental_field in config.incremental_fields}
    if not inject_row_id:
        required_columns.add(config.primary_key)

    is_first_request = True
    while window_start <= today:
        window_end = min(window_start + timedelta(days=config.report_window_days - 1), today)
        if not is_first_request:
            time.sleep(REPORT_REQUEST_INTERVAL_SECONDS)
        is_first_request = False
        response = generate_report(
            {
                "metricSet": metric_set,
                # Explicit UTC keeps window boundaries and rendered timestamps
                # stable even if the organization's default timezone changes.
                "timezone": "UTC",
                # endAt is inclusive: the report covers through the end of that day.
                "startAt": window_start.isoformat(),
                "endAt": window_end.isoformat(),
            }
        )

        # Wrap the byte stream rather than iterating lines: CSV values can contain
        # newlines inside quoted fields, which line-splitting would tear apart.
        text_stream = io.TextIOWrapper(
            io.BufferedReader(_ResponseByteStream(response, REPORT_CHUNK_BYTES)), encoding="utf-8-sig", newline=""
        )
        reader = csv.DictReader(_report_csv_lines(text_stream))
        columns = {name: _normalize_report_column(name) for name in reader.fieldnames or []}
        present = sorted({column for column in columns.values() if column})
        missing = sorted(required_columns.difference(present))
        # An empty body has no header at all and is a legitimately empty window, so only
        # a header that parsed and came back wrong is a contract break. Log it before
        # raising: the exception message is replaced by user guidance on the way to the
        # customer, so this is the only place the real shape is recorded.
        if reader.fieldnames and missing:
            logger.error(
                f"Gladly: {config.name} report window {window_start} - {window_end} returned a header "
                f"missing {missing}. Header row: {reader.fieldnames!r:.500}"
            )
            raise GladlyReportHeaderError(metric_set, missing, present)

        row_count = 0
        chunk: list[dict[str, Any]] = []
        for csv_row in reader:
            row: dict[str, Any] = {}
            for raw_name, column in columns.items():
                if not column:
                    continue
                value = csv_row.get(raw_name)
                # Blank CSV cells become NULL (e.g. topic columns of non-topic events).
                row[column] = None if value == "" else value
            if inject_row_id:
                row[REPORT_ROW_ID_COLUMN] = _report_row_id(row)
            chunk.append(row)
            row_count += 1
            if len(chunk) >= CHUNK_SIZE:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

        if row_count >= REPORT_ROW_WARNING_THRESHOLD:
            logger.warning(
                f"Gladly: {config.name} report window {window_start} - {window_end} returned {row_count} rows "
                f"and may have been truncated at Gladly's report row cap"
            )

        # Save state AFTER the window is fully yielded so a crash re-reads this
        # window (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(GladlyResumeConfig(last_report_window_end=window_end.isoformat()))
        window_start = window_end + timedelta(days=1)


def gladly_source(
    organization: str,
    agent_email: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GladlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    domain: str = DEFAULT_DOMAIN,
) -> SourceResponse:
    config = GLADLY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            organization=organization,
            agent_email=agent_email,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            domain=domain,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        # Jobs are processed oldest-first, so the injected job watermark only
        # moves forward.
        sort_mode="asc",
    )
