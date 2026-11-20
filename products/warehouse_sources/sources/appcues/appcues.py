import io
import re
import gzip
import json
import time
import base64
import tempfile
import itertools
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import IO, Any
from urllib.parse import quote, urlsplit

import requests

from products.warehouse_sources.sources.appcues._config import AppcuesSourceConfig
from products.warehouse_sources.sources.appcues.settings import (
    BASE_URLS,
    ENDPOINTS,
    EVENTS_EXPORT_END_LAG,
    EVENTS_EXPORT_PAGE_SIZE,
    EVENTS_EXPORT_WINDOW,
    EVENTS_INITIAL_LOOKBACK,
    EXPORT_BATCH_SIZE,
    EXPORT_POLL_BUDGET_SECONDS,
    EXPORT_POLL_INTERVAL_SECONDS,
)
from products.warehouse_sources.sources.sdk import (
    HttpBasicAuth,
    JobStatus,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceInputs,
    SourceResponse,
    format_datetime,
    frozen,
    make_tracked_session,
    parse_datetime_or_epoch,
    parse_datetime_value,
    poll_until_done,
    raise_for_retryable_status,
    raise_for_status_redacted,
    resolve_incremental_start,
    rest_api_resource,
    schema_for_resource,
    vendor_retry,
)

REQUEST_TIMEOUT_SECONDS = 30
DOWNLOAD_TIMEOUT_SECONDS = 300
# A slow file host must not hold the worker past this, also while it keeps sending bytes.
DOWNLOAD_BUDGET_SECONDS = 30 * 60
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
PARSE_CHUNK_CHARS = 1024 * 1024
JSON_SEPARATORS = frozenset(" \t\r\n,")
RETRY_BUDGET_SECONDS = 240

JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


@dataclasses.dataclass(frozen=True)
class AppcuesResumeConfig:
    """The export job in progress and how many rows of its file are already written.

    Events keep the job's time window and page offset; segment membership keeps the segment the job exports.
    """

    job_id: str | None = None
    rows_done: int = 0
    window_start: str | None = None
    window_end: str | None = None
    offset: int = 0
    segment_id: str | None = None


class AppcuesExportError(Exception):
    pass


class AppcuesExportFailedError(AppcuesExportError):
    pass


def account_url(config: AppcuesSourceConfig, api_version: str) -> str:
    if config.region not in BASE_URLS:
        raise ValueError("Select the US or EU region for your Appcues account.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", config.account_id):
        raise ValueError("Enter the Appcues account ID from your account settings.")
    if not config.api_key or not config.api_secret or not (config.api_key.isascii() and config.api_secret.isascii()):
        raise ValueError("Enter a valid Appcues API key and secret.")
    if ":" in config.api_key:
        raise ValueError("Enter the Appcues API key and secret in separate fields.")
    if api_version != "v2":
        raise ValueError("This Appcues API version is not supported. Reconnect the source with version v2.")
    return f"{BASE_URLS[config.region]}/{api_version}/accounts/{config.account_id}/"


def probe_credentials(config: AppcuesSourceConfig, endpoint: str, api_version: str) -> None:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    client = RESTClient(
        base_url=account_url(config, api_version),
        auth=HttpBasicAuth(username=config.api_key, password=config.api_secret),
        headers={"Accept": "application/json"},
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=10,
        retry_budget_seconds=RETRY_BUDGET_SECONDS,
        retry_after_max_seconds=RETRY_BUDGET_SECONDS,
    )
    with client.session:
        next(client.paginate(settings.credential_probe_path, data_selector_required=settings.kind != "rules"), None)


def normalize_created_at(item: dict[str, Any]) -> dict[str, Any]:
    created_at = item.get("created_at")
    # Experience endpoints use Unix milliseconds; older catalogs use ISO 8601 strings.
    if isinstance(created_at, int | float) and not isinstance(created_at, bool):
        item["created_at"] = datetime.fromtimestamp(created_at / 1000, tz=UTC)
    return item


class AppcuesExportClient:
    def __init__(self, config: AppcuesSourceConfig, api_version: str) -> None:
        self.base_url = account_url(config, api_version)
        token = base64.b64encode(f"{config.api_key}:{config.api_secret}".encode()).decode()
        # Job status bodies carry the signed file URL, so they stay out of sample capture.
        self.session = make_tracked_session(
            headers={"Accept": "application/json", "Authorization": f"Basic {token}"},
            redact_values=(config.api_key, config.api_secret, token),
            capture=False,
        )

    def get(self, path: str) -> requests.Response:
        url = self.base_url + path
        response = self.session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)
        raise_for_status_redacted(response, url=url)
        return response

    def get_json(self, path: str) -> Any:
        return self.get(path).json()

    @vendor_retry()
    def create_job(self, path: str, body: dict[str, Any]) -> str:
        url = self.base_url + path
        response = self.session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)
        raise_for_retryable_status(response, vendor="Appcues", url=url)
        raise_for_status_redacted(response, url=url)
        payload = response.json()
        job_id = payload.get("job_id") if isinstance(payload, dict) else None
        if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
            raise AppcuesExportError(f"Appcues returned no job ID for the {path} export")
        return job_id

    def wait_for_file(self, job_id: str, manager: ResumableSourceManager[AppcuesResumeConfig]) -> str:
        def check() -> JobStatus[str]:
            job = self.get_json(f"jobs/{quote(job_id, safe='')}")
            status = str(job.get("status") or "").upper() if isinstance(job, dict) else ""
            if status == "COMPLETED":
                url = signed_file_url(job)
                if url is None:
                    raise AppcuesExportError(f"Appcues export job {job_id} completed without a signed_s3_url")
                return JobStatus(done=True, result=url)
            if status == "FAILED":
                return JobStatus(failed=True, message=status)
            return JobStatus(message=status or "pending")

        return poll_until_done(
            check,
            interval=EXPORT_POLL_INTERVAL_SECONDS,
            budget_seconds=EXPORT_POLL_BUDGET_SECONDS,
            safe_point=manager.safe_point,
            failed_error=lambda status: AppcuesExportFailedError(f"Appcues export job {job_id} failed"),
            timeout_error=lambda status: AppcuesExportError(
                f"Appcues export job {job_id} is still {status.message} after the polling budget"
            ),
        )


def signed_file_url(job: dict[str, Any]) -> str | None:
    # Appcues documents a signed_s3_url on the job status but not where in the body it sits, so
    # look at the top level and in the attributes of each job event, newest first.
    candidates: list[Any] = [job.get("signed_s3_url")]
    events = job.get("events")
    if isinstance(events, list):
        for event in reversed(events):
            attributes = event.get("attributes") if isinstance(event, dict) else None
            if isinstance(attributes, dict):
                candidates.append(attributes.get("signed_s3_url"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            if urlsplit(candidate).scheme.lower() != "https":
                raise AppcuesExportError("The Appcues export file URL is not HTTPS")
            return candidate
    return None


def _iter_json_objects(text: IO[str]) -> Iterator[dict[str, Any]]:
    """Stream the objects of a JSON array, or of one object per line, without loading the file.

    The docs do not say which of the two shapes a JSON export has.
    """
    decoder = json.JSONDecoder()
    buffer = ""
    position = 0
    at_end = False
    in_array = False

    def refill() -> None:
        nonlocal buffer, position, at_end
        chunk = text.read(PARSE_CHUNK_CHARS)
        at_end = not chunk
        buffer = buffer[position:] + chunk
        position = 0

    while True:
        while position < len(buffer) and buffer[position] in JSON_SEPARATORS:
            position += 1
        if position >= len(buffer):
            if at_end:
                return
            refill()
            continue
        if buffer[position] == "[" and not in_array:
            in_array = True
            position += 1
            continue
        if buffer[position] == "]" and in_array:
            in_array = False
            position += 1
            continue
        try:
            value, position = decoder.raw_decode(buffer, position)
        except json.JSONDecodeError:
            if at_end:
                raise AppcuesExportError("The Appcues export file is not valid JSON") from None
            refill()
            continue
        if not isinstance(value, dict):
            raise AppcuesExportError("The Appcues export file holds a value that is not an event object")
        yield value


def _download(url: str, file: IO[bytes], safe_point: Callable[[], None]) -> None:
    # The file sits on a pre-signed storage URL, so the download must not carry the API key.
    download_session = make_tracked_session(redact_values=(url,), capture=False)
    deadline = time.monotonic() + DOWNLOAD_BUDGET_SECONDS
    try:
        with download_session.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as download:
            raise_for_status_redacted(download, url=url)
            for chunk in download.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                file.write(chunk)
                safe_point()
                if time.monotonic() > deadline:
                    raise AppcuesExportError("The Appcues export file download took longer than 30 minutes")
    except requests.RequestException as error:
        # The exception text holds the signed URL, so it must not reach logs or job errors.
        status = error.response.status_code if error.response is not None else None
        reason = f"HTTP {status}" if status is not None else type(error).__name__
        raise AppcuesExportError(f"The Appcues export file download failed ({reason})") from None


def iter_export_file(url: str, safe_point: Callable[[], None]) -> Iterator[dict[str, Any]]:
    with tempfile.TemporaryFile() as file:
        _download(url, file, safe_point)
        file.seek(0)
        compressed = file.read(2) == b"\x1f\x8b"
        file.seek(0)
        binary = gzip.GzipFile(fileobj=file) if compressed else file
        yield from _iter_json_objects(io.TextIOWrapper(binary, encoding="utf-8"))


def normalize_event(row: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_datetime_or_epoch(row.get("timestamp"))
    if parsed is not None:
        row["timestamp"] = parsed
    return row


def _in_window(row: dict[str, Any], start: datetime, end: datetime) -> bool:
    timestamp = row.get("timestamp")
    return not isinstance(timestamp, datetime) or start <= timestamp < end


@dataclasses.dataclass
class _FileProgress:
    rows: int = 0


@frozen
class _ExportWindow:
    start: datetime
    end: datetime


def _export_windows(start: datetime, end: datetime) -> Iterator[_ExportWindow]:
    window_start = start
    while window_start < end:
        window_end = min(window_start + EVENTS_EXPORT_WINDOW, end)
        yield _ExportWindow(start=window_start, end=window_end)
        window_start = window_end


def _stage_new_job(
    manager: ResumableSourceManager[AppcuesResumeConfig], checkpoint: AppcuesResumeConfig, commit: bool
) -> None:
    if commit:
        with manager.committing():
            manager.save_state(checkpoint)
    else:
        # Staged only: committing now would move the cursor past rows not yet written.
        manager.save_state(checkpoint)
        manager.safe_point()


def _read_job_rows(
    client: AppcuesExportClient,
    manager: ResumableSourceManager[AppcuesResumeConfig],
    checkpoint: AppcuesResumeConfig,
    start_job: Callable[[], str],
    yielded_any: bool,
    progress: _FileProgress | None = None,
) -> Iterator[tuple[AppcuesResumeConfig, dict[str, Any]]]:
    """Yield each file row of the checkpoint's job, with the checkpoint that covers it.

    A checkpoint without a job starts one. A saved job that failed would fail every retry, so a
    failed resumed job starts the export again.
    """
    url: str | None = None
    if checkpoint.job_id is not None:
        try:
            url = client.wait_for_file(checkpoint.job_id, manager)
        except AppcuesExportFailedError:
            url = None
    if url is None:
        job_id = start_job()
        checkpoint = dataclasses.replace(checkpoint, job_id=job_id, rows_done=0)
        _stage_new_job(manager, checkpoint, commit=not yielded_any)
        url = client.wait_for_file(job_id, manager)

    for index, row in enumerate(iter_export_file(url, manager.safe_point)):
        if progress is not None:
            progress.rows = index + 1
        if index < checkpoint.rows_done:
            continue
        yield dataclasses.replace(checkpoint, rows_done=index + 1), row


def _batched_rows(
    rows: Iterator[tuple[AppcuesResumeConfig, dict[str, Any]]],
    manager: ResumableSourceManager[AppcuesResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    checkpoint: AppcuesResumeConfig | None = None
    for checkpoint, row in rows:
        batch.append(row)
        if len(batch) >= EXPORT_BATCH_SIZE:
            manager.save_state(checkpoint)
            yield batch
            batch = []
    if batch and checkpoint is not None:
        manager.save_state(checkpoint)
        yield batch


def _to_milliseconds(value: datetime) -> datetime:
    # Requests and checkpoints carry milliseconds, so the row filter must use the same bounds.
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def get_events(
    client: AppcuesExportClient, manager: ResumableSourceManager[AppcuesResumeConfig], inputs: SourceInputs
) -> Iterator[list[dict[str, Any]]]:
    end = _to_milliseconds(datetime.now(UTC) - EVENTS_EXPORT_END_LAG)
    resume = manager.load_state() if manager.can_resume() else None
    resumed_start = parse_datetime_value(resume.window_start) if resume else None
    resumed_end = parse_datetime_value(resume.window_end) if resume else None

    pending: AppcuesResumeConfig | None = None
    windows: Iterator[_ExportWindow]
    if resume is not None and resumed_start is not None and resumed_end is not None:
        # Finish the interrupted window exactly as it was exported before moving on.
        windows = itertools.chain(
            [_ExportWindow(start=resumed_start, end=resumed_end)], _export_windows(resumed_end, end)
        )
        pending = resume
    else:
        # A rebuild has no watermark; the schema's recorded history floor keeps it as deep as the first sync.
        start = resolve_incremental_start(
            bool(inputs.should_use_incremental_field),
            inputs.db_incremental_field_last_value,
            default=inputs.history_start or EVENTS_INITIAL_LOOKBACK,
            now=end,
        )
        if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
            # The export's time range includes its start, so step past the last synced event.
            start += timedelta(milliseconds=1)
        windows = _export_windows(_to_milliseconds(start), end)

    yielded_any = False
    for window in windows:
        checkpoint = pending or AppcuesResumeConfig(
            window_start=format_datetime(window.start, "iso_z_millis"),
            window_end=format_datetime(window.end, "iso_z_millis"),
        )
        pending = None

        # Appcues caps one export, so page through a window until a page comes back short.
        while True:

            def start_job(window: _ExportWindow = window, offset: int = checkpoint.offset) -> str:
                return client.create_job(
                    "export/events",
                    {
                        "format": "json",
                        "conditions": [],
                        "start_time": format_datetime(window.start, "iso_z_millis"),
                        "end_time": format_datetime(window.end, "iso_z_millis"),
                        "time_zone": "+00:00",
                        "limit": EVENTS_EXPORT_PAGE_SIZE,
                        "offset": offset,
                        # Appcues sends no email when this is null, and the file comes from the job status.
                        "email": None,
                    },
                )

            progress = _FileProgress()
            rows = (
                (state, row)
                for state, row in (
                    (state, normalize_event(row))
                    for state, row in _read_job_rows(client, manager, checkpoint, start_job, yielded_any, progress)
                )
                if _in_window(row, window.start, window.end)
            )
            for batch in _batched_rows(rows, manager):
                yield batch
                yielded_any = True

            if progress.rows < EVENTS_EXPORT_PAGE_SIZE:
                break
            checkpoint = AppcuesResumeConfig(
                window_start=checkpoint.window_start,
                window_end=checkpoint.window_end,
                offset=checkpoint.offset + EVENTS_EXPORT_PAGE_SIZE,
            )


def get_segment_membership(
    client: AppcuesExportClient, manager: ResumableSourceManager[AppcuesResumeConfig]
) -> Iterator[list[dict[str, Any]]]:
    segments = client.get_json("segments")
    if not isinstance(segments, list):
        raise AppcuesExportError("Appcues returned an unexpected response for the segment list")
    segment_ids = sorted(
        {str(segment["id"]) for segment in segments if isinstance(segment, dict) and segment.get("id")}
    )

    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.segment_id is not None:
        segment_ids = [segment_id for segment_id in segment_ids if segment_id >= resume.segment_id]

    yielded_any = False
    for segment_id in segment_ids:
        if not JOB_ID_PATTERN.fullmatch(segment_id):
            raise AppcuesExportError("Appcues returned a segment ID that cannot be exported")
        if resume is not None and resume.segment_id == segment_id:
            checkpoint = resume
        else:
            checkpoint = AppcuesResumeConfig(segment_id=segment_id)
        resume = None

        def start_job(segment_id: str = segment_id) -> str:
            return client.create_job(
                f"segments/{segment_id}/segment_membership_export", {"format": "json", "property_names": []}
            )

        rows = (
            (state, {**row, "segment_id": segment_id})
            for state, row in _read_job_rows(client, manager, checkpoint, start_job, yielded_any)
        )
        for batch in _batched_rows(rows, manager):
            yield batch
            yielded_any = True


def get_ingestion_filtering_rules(client: AppcuesExportClient) -> Iterator[dict[str, Any]]:
    try:
        rules = client.get_json("ingestion_filtering_rules")
    except requests.HTTPError as error:
        # Appcues answers 404 when the account has no ingestion filtering rule.
        if error.response is not None and error.response.status_code == 404:
            return
        raise
    if not isinstance(rules, dict):
        raise AppcuesExportError("Appcues returned an unexpected response for the ingestion filtering rules")
    yield rules


def appcues_source(
    config: AppcuesSourceConfig,
    inputs: SourceInputs,
    api_version: str,
    manager: ResumableSourceManager[AppcuesResumeConfig],
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, inputs.schema_name)
    if settings.kind != "list":
        client = AppcuesExportClient(config, api_version)
        if settings.kind == "event_export":
            return SourceResponse(
                name=inputs.schema_name,
                items=lambda: get_events(client, manager, inputs),
                primary_keys=None,
                partition_keys=["timestamp"],
                partition_mode="datetime",
                partition_format="day",
                partition_size=1,
                partition_count=1,
                # Rows inside an export file are unordered.
                sort_mode=None,
            )
        return SourceResponse(
            name=inputs.schema_name,
            items=(
                (lambda: get_segment_membership(client, manager))
                if settings.kind == "segment_export"
                else (lambda: get_ingestion_filtering_rules(client))
            ),
            primary_keys=list(settings.primary_keys),
            sort_mode=None,
        )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": account_url(config, api_version),
            "auth": {"type": "http_basic", "username": config.api_key, "password": config.api_secret},
            "headers": {"Accept": "application/json"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            "retry_budget_seconds": RETRY_BUDGET_SECONDS,
            "retry_after_max_seconds": RETRY_BUDGET_SECONDS,
        },
        "resources": [
            {
                "name": inputs.schema_name,
                "table_name": inputs.schema_name,
                "write_disposition": "replace",
                "columns": {"created_at": {"data_type": "timestamp"}},
                "endpoint": {
                    "path": settings.path,
                    "paginator": "single_page",
                    "data_selector_required": True,
                },
            }
        ],
    }
    resource = rest_api_resource(rest_config, inputs.team_id, inputs.job_id, None).add_map(normalize_created_at)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(settings.primary_keys),
        column_hints=resource.column_hints,
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
        partition_count=1,
        sort_mode=None,
        supports_resume=False,
    )
