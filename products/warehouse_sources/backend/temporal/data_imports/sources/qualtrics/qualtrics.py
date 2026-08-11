import re
import json
import time
import base64
import zipfile
import tempfile
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import IO, Any, Literal, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics.settings import (
    QUALTRICS_DEFAULT_DOMAIN_SUFFIX,
    QUALTRICS_ENDPOINTS,
    VALIDATION_PATHS,
    QualtricsEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

# The brand host is customer-supplied, so no response body is ever buffered unbounded. JSON
# collection pages are small (Qualtrics caps them at 100 elements), so this leaves ample room.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
_RESPONSE_CHUNK_BYTES = 64 * 1024
_ERROR_BODY_PREVIEW_BYTES = 2 * 1024
# Wall-clock budget for one body. `requests`' timeout only bounds each socket read, so a host
# dribbling bytes under that timeout could otherwise hold a worker open indefinitely.
MAX_DOWNLOAD_SECONDS = 900

# Response exports are the one large payload: the archive is spooled to disk past this size
# and refused past the hard cap, and the decompressed stream is capped separately so a
# zip bomb can't amplify a small download into unbounded memory.
EXPORT_SPOOL_MAX_BYTES = 32 * 1024 * 1024
MAX_EXPORT_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_EXPORT_DECOMPRESSED_BYTES = 16 * 1024 * 1024 * 1024
# Cap a single NDJSON line so a newline-free member can't buffer unbounded before the byte
# budget is checked. A real Qualtrics response row is far smaller than this.
MAX_EXPORT_LINE_BYTES = 16 * 1024 * 1024
# Flush a batch once its accumulated rows reach this many serialized bytes, so a run of large
# rows can't pin far more than this in memory before the row-count batch size is hit.
MAX_EXPORT_BATCH_BYTES = 32 * 1024 * 1024
# A real export is a single NDJSON member; `zipfile` builds a `ZipInfo` per entry as soon as it
# reads the central directory, so cap the declared member count before that memory is spent.
MAX_EXPORT_ARCHIVE_MEMBERS = 1024

# Export jobs are asynchronous: create, then poll until Qualtrics reports `complete`.
EXPORT_POLL_INTERVAL_SECONDS = 3.0
MAX_EXPORT_POLL_SECONDS = 60 * 60

# Rows are yielded to the pipeline in batches of this many.
EXPORT_BATCH_SIZE = 1000

# A server that keeps returning a `nextPage` forever would pin the (up to week-long) activity
# in an endless fetch loop. At 100 elements per page this is far beyond any real brand.
MAX_PAGES = 50_000

# The fan-out survey-id list is held whole in memory, so bound both the per-id length (real
# Qualtrics ids are ~18 chars) and the total count (far beyond any real brand) so a custom host
# streaming endless over-long ids can't exhaust the worker.
MAX_SURVEY_ID_LENGTH = 64
MAX_SURVEY_COUNT = 200_000

# OAuth2 client-credentials tokens last ~1h; re-mint before the deadline so no request rides
# a token that expires mid-flight.
TOKEN_REFRESH_MARGIN_SECONDS = 60
DEFAULT_TOKEN_LIFETIME_SECONDS = 60 * 60

HOST_NOT_ALLOWED_ERROR = "Qualtrics host is not allowed"
INCOMPLETE_CREDENTIALS_ERROR = "Qualtrics credentials are incomplete"
EXPORT_FAILED_ERROR = "Qualtrics response export failed"

_HOST_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")
_SURVEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


class QualtricsRetryableError(Exception):
    pass


class QualtricsHostNotAllowedError(Exception):
    pass


class QualtricsConfigurationError(Exception):
    pass


class QualtricsResponseTooLargeError(Exception):
    pass


class QualtricsResponseTooSlowError(Exception):
    pass


class QualtricsPaginationLimitError(Exception):
    pass


class QualtricsExportFailedError(Exception):
    pass


@dataclasses.dataclass
class QualtricsResumeConfig:
    # Full URL of the next collection page to fetch (top-level list endpoints).
    next_page: str | None = None
    # Number of parent surveys already walked to completion (fan-out endpoints). Restarting
    # the in-flight survey is intentional — merge dedupes its rows on the primary key.
    parent_index: int = 0


@dataclasses.dataclass
class QualtricsCredentials:
    method: Literal["api_token", "oauth_client_credentials"]
    api_token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.api_token, self.client_secret) if value)


def normalize_host(datacenter_id: str) -> str:
    """Turn whatever the user typed into a bare Qualtrics host.

    Accepts a datacenter id (``iad1``), a full host (``iad1.qualtrics.com``), or a pasted URL
    (``https://iad1.qualtrics.com/API/v3/``). A bare id gains the default Qualtrics domain;
    anything already carrying a dot is treated as a host so brands on a custom domain work.
    """
    host = datacenter_id.strip()
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE)
    host = host.split("/")[0].strip().rstrip("/").lower()
    if host and "." not in host:
        host = f"{host}{QUALTRICS_DEFAULT_DOMAIN_SUFFIX}"
    return host


def validate_host(datacenter_id: str) -> str:
    host = normalize_host(datacenter_id)
    if not host or not _HOST_PATTERN.match(host):
        raise QualtricsConfigurationError("Invalid Qualtrics datacenter ID")
    return host


def base_url(host: str, api_version: str) -> str:
    return f"https://{host}/API/{api_version}"


def _format_datetime_z(value: datetime) -> str:
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_incremental_value(value: Any) -> str:
    """Qualtrics export filters take ISO 8601 instants (``2026-01-01T00:00:00Z``)."""
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _read_capped(response: requests.Response, max_bytes: int) -> bytes:
    """Read a streamed body, refusing one past ``max_bytes`` or ``MAX_DOWNLOAD_SECONDS``.

    ``iter_content`` decodes any content-encoding, so the cap bounds the decompressed body and a
    compressed one cannot slip past it. Both caps are permanent failures — re-fetching the same
    URL returns the same oversized or slow body.
    """
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=_RESPONSE_CHUNK_BYTES):
            if time.monotonic() > deadline:
                raise QualtricsResponseTooSlowError(
                    f"Qualtrics response exceeded the {MAX_DOWNLOAD_SECONDS}s download budget; aborting"
                )
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise QualtricsResponseTooLargeError(
                    f"Qualtrics response exceeded the {max_bytes}-byte limit; refusing to buffer it"
                )
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks)


def _read_capped_json(response: requests.Response) -> Any:
    return json.loads(_read_capped(response, MAX_RESPONSE_BYTES))


def _read_body_preview(response: requests.Response) -> str:
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    for chunk in response.iter_content(chunk_size=_RESPONSE_CHUNK_BYTES):
        if time.monotonic() > deadline:
            break
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total >= _ERROR_BODY_PREVIEW_BYTES:
            break
    return b"".join(chunks)[:_ERROR_BODY_PREVIEW_BYTES].decode("utf-8", errors="replace")


def _guard_response(response: requests.Response, url: str, logger: FilteringBoundLogger | None = None) -> None:
    """Classify a response before its body is read: retryable, redirect, or hard error."""
    if response.status_code == 429 or response.status_code >= 500:
        raise QualtricsRetryableError(f"Qualtrics API error (retryable): status={response.status_code}, url={url}")

    # A 3xx is not an error status, so reject it explicitly rather than following it to a
    # potentially internal Location (SSRF).
    if response.is_redirect or response.is_permanent_redirect:
        raise QualtricsHostNotAllowedError(
            f"Qualtrics API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
        )

    if not response.ok:
        if logger is not None:
            logger.error(
                f"Qualtrics API error: status={response.status_code}, body={_read_body_preview(response)}, url={url}"
            )
        response.raise_for_status()


_retry_write = retry(
    retry=retry_if_exception_type((QualtricsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)


class QualtricsAuthManager:
    """Builds the auth header for both Qualtrics auth paths.

    An API token rides the ``X-API-TOKEN`` header verbatim. OAuth2 client credentials are
    exchanged at ``POST /oauth2/token`` for a ~1h bearer token, cached and re-minted before it
    expires so a long sync never rides a dead token.
    """

    def __init__(self, session: requests.Session, host: str, credentials: QualtricsCredentials) -> None:
        self._session = session
        self._host = host
        self._credentials = credentials
        self._token: str | None = None
        self._deadline: float = 0.0

    def headers(self) -> dict[str, str]:
        if self._credentials.method == "api_token":
            if not self._credentials.api_token:
                raise QualtricsConfigurationError(f"{INCOMPLETE_CREDENTIALS_ERROR}: API token required")
            return {"X-API-TOKEN": self._credentials.api_token, "Accept": "application/json"}
        return {"Authorization": f"Bearer {self._get_token()}", "Accept": "application/json"}

    def _get_token(self) -> str:
        if self._token is None or time.monotonic() >= self._deadline - TOKEN_REFRESH_MARGIN_SECONDS:
            self._mint()
        assert self._token is not None
        return self._token

    @_retry_write
    def _mint(self) -> None:
        if not self._credentials.client_id or not self._credentials.client_secret:
            raise QualtricsConfigurationError(f"{INCOMPLETE_CREDENTIALS_ERROR}: client ID and client secret required")

        basic = base64.b64encode(f"{self._credentials.client_id}:{self._credentials.client_secret}".encode()).decode()
        url = f"https://{self._host}/oauth2/token"
        # The transport's Retry policy only covers idempotent methods, so token mints (POST)
        # carry their own bounded retry via `_retry_write` rather than a second status layer.
        response = self._session.post(
            url,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )
        try:
            _guard_response(response, url)
            payload = _read_capped_json(response)
        finally:
            response.close()

        if not isinstance(payload, dict):
            raise QualtricsConfigurationError(f"{INCOMPLETE_CREDENTIALS_ERROR}: unexpected OAuth token response")
        token = payload.get("access_token")
        if not token:
            raise QualtricsConfigurationError(f"{INCOMPLETE_CREDENTIALS_ERROR}: OAuth token endpoint returned no token")
        self._token = token
        expires_in = payload.get("expires_in")
        self._deadline = time.monotonic() + (
            float(expires_in) if expires_in is not None else DEFAULT_TOKEN_LIFETIME_SECONDS
        )


class QualtricsClient:
    """Thin request layer over the Qualtrics v3 API, sharing one auth manager per sync."""

    def __init__(
        self,
        host: str,
        credentials: QualtricsCredentials,
        api_version: str,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        self.host = host
        self.api_version = api_version
        self._logger = logger
        # Token responses carry the bearer credential in their body, which the name-based
        # sample scrubbers can't recognise — keep auth exchanges out of sample capture.
        self._auth = QualtricsAuthManager(
            make_tracked_session(capture=False, redact_values=credentials.secret_values()),
            host,
            credentials,
        )
        self._session = make_tracked_session(redact_values=credentials.secret_values())

    @property
    def base_url(self) -> str:
        return base_url(self.host, self.api_version)

    def url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = f"{self.base_url}{path}"
        return f"{url}?{urlencode(params, doseq=True)}" if params else url

    def _assert_same_host(self, url: str) -> None:
        """Follow-on URLs from the API body must stay on the configured brand host (SSRF)."""
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != self.host:
            raise QualtricsHostNotAllowedError(f"{HOST_NOT_ALLOWED_ERROR}: {url}")

    def get(self, url: str) -> requests.Response:
        self._assert_same_host(url)
        return self._session.get(
            url,
            headers=self._auth.headers(),
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )

    def get_json(self, url: str) -> Any:
        response = self.get(url)
        try:
            _guard_response(response, url, self._logger)
            return _read_capped_json(response)
        finally:
            response.close()

    @_retry_write
    def post_json(self, url: str, body: dict[str, Any]) -> Any:
        self._assert_same_host(url)
        response = self._session.post(
            url,
            json=body,
            headers={**self._auth.headers(), "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )
        try:
            _guard_response(response, url, self._logger)
            return _read_capped_json(response)
        finally:
            response.close()


def _result(payload: Any) -> dict[str, Any]:
    """Pull the `result` object out of a Qualtrics envelope, tolerating any non-dict shape.

    Every Qualtrics v3 response nests its payload under `result`, but a misbehaving or custom
    host could return valid JSON that isn't a dict — treat anything unexpected as empty rather
    than letting `.get()` raise mid-sync.
    """
    result = payload.get("result") if isinstance(payload, dict) else None
    return result if isinstance(result, dict) else {}


def _elements(payload: Any) -> list[dict[str, Any]]:
    elements = _result(payload).get("elements")
    return elements if isinstance(elements, list) else []


def _next_page(payload: Any) -> str | None:
    next_page = _result(payload).get("nextPage")
    return next_page if isinstance(next_page, str) and next_page else None


def _iter_collection(
    client: QualtricsClient,
    first_url: str,
    resumable_source_manager: ResumableSourceManager[QualtricsResumeConfig] | None,
    start_url: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk a `result.elements` collection, following `result.nextPage` until it runs out."""
    url = start_url or first_url
    pages = 0

    while True:
        if pages >= MAX_PAGES:
            raise QualtricsPaginationLimitError(
                f"Qualtrics pagination exceeded {MAX_PAGES} pages without terminating: {first_url}"
            )

        payload = client.get_json(url)
        elements = _elements(payload)
        if elements:
            yield elements

        next_url = _next_page(payload)
        if not next_url:
            break

        # Saved AFTER yielding so a crash re-yields the last page rather than skipping it.
        if resumable_source_manager is not None:
            resumable_source_manager.save_state(QualtricsResumeConfig(next_page=next_url))
        url = next_url
        pages += 1


def _survey_ids(client: QualtricsClient) -> list[str]:
    """Collect the survey ids the fan-out endpoints iterate.

    Ids go straight into request paths, so anything that isn't a plain Qualtrics id
    (`SV_...`) is dropped rather than allowed to steer the URL. The list is fully materialized —
    resuming the fan-out addresses surveys by index — so an id-length cap and a total-count cap
    keep a host that streams endless over-long ids from exhausting worker memory.
    """
    ids: list[str] = []
    for page in _iter_collection(client, client.url("/surveys"), resumable_source_manager=None):
        for element in page:
            raw = element.get("id")
            if not raw:
                continue
            survey_id = str(raw)
            if len(survey_id) > MAX_SURVEY_ID_LENGTH or not _SURVEY_ID_PATTERN.match(survey_id):
                continue
            ids.append(survey_id)
            if len(ids) > MAX_SURVEY_COUNT:
                raise QualtricsResponseTooLargeError(
                    f"Qualtrics returned more than {MAX_SURVEY_COUNT} surveys; refusing to buffer them all"
                )
    return ids


class _DecompressionBudget:
    """One decompressed-byte budget, shared across every member of an export archive.

    A single counter across the whole archive stops a multi-member zip from bypassing the cap:
    each member could stay under the limit while their aggregate decompressed size blows past it.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._total = 0

    def charge(self, n: int) -> None:
        self._total += n
        if self._total > self._limit:
            raise QualtricsResponseTooLargeError(f"Qualtrics export exceeded the {self._limit}-byte decompressed limit")


def _parse_ndjson_line(line: bytes) -> Iterator[dict[str, Any]]:
    stripped = line.strip()
    if not stripped:
        return
    parsed = json.loads(stripped.decode("utf-8", errors="replace"))
    if isinstance(parsed, dict):
        yield parsed


def _iter_ndjson(stream: IO[bytes], budget: _DecompressionBudget) -> Iterator[dict[str, Any]]:
    """Parse an NDJSON stream from bounded binary chunks, charging bytes to a shared budget.

    Reading raw chunks (rather than `TextIOWrapper` line iteration) keeps a single newline-free
    member from allocating an unbounded line before the byte budget is ever consulted.
    """
    buffer = bytearray()
    while True:
        chunk = stream.read(_RESPONSE_CHUNK_BYTES)
        if not chunk:
            break
        budget.charge(len(chunk))
        buffer.extend(chunk)
        newline = buffer.rfind(b"\n")
        if newline != -1:
            complete = bytes(buffer[: newline + 1])
            del buffer[: newline + 1]
            for line in complete.splitlines():
                yield from _parse_ndjson_line(line)
        if len(buffer) > MAX_EXPORT_LINE_BYTES:
            raise QualtricsResponseTooLargeError(
                f"Qualtrics export line exceeded the {MAX_EXPORT_LINE_BYTES}-byte limit"
            )
    if buffer:
        yield from _parse_ndjson_line(bytes(buffer))


_EOCD_SIGNATURE = b"PK\x05\x06"
# The zip end-of-central-directory record is 22 bytes plus a comment of up to 65535 bytes.
_EOCD_MAX_SCAN_BYTES = 22 + 65535
# Fixed size of a central-directory file header; the real header is this plus name/extra/comment.
_CENTRAL_DIR_HEADER_MIN_BYTES = 46


def _guard_zip_central_directory(buffer: IO[bytes]) -> None:
    """Reject an archive whose central directory is large enough to materialize too many members.

    `zipfile` reads the whole central directory and builds a `ZipInfo` per file header (each at
    least `_CENTRAL_DIR_HEADER_MIN_BYTES`), looping until it consumes the size-of-central-directory
    field of the trailing end-of-central-directory record — the same record it selects. Bounding
    that byte length before construction caps the entry count at `MAX_EXPORT_ARCHIVE_MEMBERS` no
    matter what the record's untrusted entry-count field claims, so a spoofed trailing EOCD
    declaring one member can't smuggle a huge directory past the guard. The ZIP64 sentinel
    (0xFFFFFFFF) reads well past the cap and is rejected here too — a real Qualtrics export stays
    well under 4 GiB with a single member.
    """
    max_central_directory_bytes = MAX_EXPORT_ARCHIVE_MEMBERS * _CENTRAL_DIR_HEADER_MIN_BYTES
    buffer.seek(0, 2)
    size = buffer.tell()
    scan = min(size, len(_EOCD_SIGNATURE) + _EOCD_MAX_SCAN_BYTES)
    buffer.seek(size - scan)
    tail = buffer.read(scan)
    marker = tail.rfind(_EOCD_SIGNATURE)
    # A missing/short record isn't our concern — `zipfile` raises its own BadZipFile for that.
    if marker == -1 or marker + 16 > len(tail):
        return
    central_directory_bytes = int.from_bytes(tail[marker + 12 : marker + 16], "little")
    if central_directory_bytes > max_central_directory_bytes:
        raise QualtricsResponseTooLargeError(
            f"Qualtrics export archive central directory is {central_directory_bytes} bytes, "
            f"exceeding the {max_central_directory_bytes}-byte limit"
        )


def _iter_export_file(response: requests.Response) -> Iterator[dict[str, Any]]:
    """Stream the export download, transparently unpacking Qualtrics' zip envelope.

    `compress=true` is the API default and yields a zip holding one NDJSON member, but the flag
    is advisory — an uncompressed body is parsed directly. The archive is spooled (memory, then
    disk) because `zipfile` needs a seekable file, while the decompressed member is read as a
    stream so a large export never materializes whole.
    """
    with tempfile.SpooledTemporaryFile(max_size=EXPORT_SPOOL_MAX_BYTES) as buffer:
        total = 0
        deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
        try:
            for chunk in response.iter_content(chunk_size=_RESPONSE_CHUNK_BYTES):
                if time.monotonic() > deadline:
                    raise QualtricsResponseTooSlowError(
                        f"Qualtrics export exceeded the {MAX_DOWNLOAD_SECONDS}s download budget; aborting"
                    )
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_EXPORT_ARCHIVE_BYTES:
                    raise QualtricsResponseTooLargeError(
                        f"Qualtrics export exceeded the {MAX_EXPORT_ARCHIVE_BYTES}-byte archive limit"
                    )
                buffer.write(chunk)
        finally:
            response.close()

        # One budget for the whole download so multi-member archives can't bypass the cap.
        budget = _DecompressionBudget(MAX_EXPORT_DECOMPRESSED_BYTES)

        buffer.seek(0)
        if buffer.read(4) != b"PK\x03\x04":
            buffer.seek(0)
            yield from _iter_ndjson(buffer, budget)
            return

        _guard_zip_central_directory(buffer)
        buffer.seek(0)
        with zipfile.ZipFile(buffer) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                with archive.open(info) as member:
                    yield from _iter_ndjson(member, budget)


def _normalize_response_row(survey_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """Flatten one exported response into a stable, survey-independent column set.

    Every survey answers different questions, so `values`/`labels`/`displayedValues` carry a
    different key set per survey. They're stored as JSON text: a struct column would otherwise
    have to reconcile every survey's question set in one table.
    """
    raw_values = row.get("values")
    values: dict[str, Any] = raw_values if isinstance(raw_values, dict) else {}
    return {
        "responseId": row.get("responseId") or values.get("_recordId"),
        "surveyId": survey_id,
        "recordedDate": values.get("recordedDate"),
        "startDate": values.get("startDate"),
        "endDate": values.get("endDate"),
        "status": values.get("status"),
        "progress": values.get("progress"),
        "duration": values.get("duration"),
        "finished": values.get("finished"),
        "distributionChannel": values.get("distributionChannel"),
        "userLanguage": values.get("userLanguage"),
        "values": json.dumps(values),
        "labels": json.dumps(row.get("labels") or {}),
        "displayedFields": json.dumps(row.get("displayedFields") or []),
        "displayedValues": json.dumps(row.get("displayedValues") or {}),
    }


def _approx_row_bytes(row: dict[str, Any]) -> int:
    """Rough in-memory size of a normalized row, dominated by its JSON-encoded blob columns."""
    return sum(len(row[key]) for key in ("values", "labels", "displayedFields", "displayedValues"))


def _export_responses(
    client: QualtricsClient,
    survey_id: str,
    start_date: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Run one survey through the async export: create the job, poll it, stream the file."""
    export_url = client.url(f"/surveys/{survey_id}/export-responses")
    body: dict[str, Any] = {"format": "ndjson", "compress": True}
    if start_date:
        body["startDate"] = start_date

    created = client.post_json(export_url, body)
    progress_id = _result(created).get("progressId")
    if not progress_id:
        raise QualtricsExportFailedError(f"{EXPORT_FAILED_ERROR}: no progressId returned for survey {survey_id}")

    deadline = time.monotonic() + MAX_EXPORT_POLL_SECONDS
    file_id: str | None = None
    while True:
        progress = _result(client.get_json(f"{export_url}/{progress_id}"))
        status = progress.get("status")
        if status == "complete":
            file_id = progress.get("fileId")
            break
        if status == "failed":
            raise QualtricsExportFailedError(f"{EXPORT_FAILED_ERROR}: survey {survey_id} reported status 'failed'")
        if time.monotonic() > deadline:
            raise QualtricsExportFailedError(
                f"{EXPORT_FAILED_ERROR}: survey {survey_id} did not finish within {MAX_EXPORT_POLL_SECONDS}s"
            )
        logger.debug(f"Qualtrics: export for {survey_id} at {progress.get('percentComplete')}%")
        time.sleep(EXPORT_POLL_INTERVAL_SECONDS)

    if not file_id:
        raise QualtricsExportFailedError(f"{EXPORT_FAILED_ERROR}: survey {survey_id} completed without a fileId")

    download_url = f"{export_url}/{file_id}/file"
    response = client.get(download_url)
    try:
        _guard_response(response, download_url, logger)
    except Exception:
        response.close()
        raise

    batch: list[dict[str, Any]] = []
    batch_bytes = 0
    for row in _iter_export_file(response):
        normalized = _normalize_response_row(survey_id, row)
        batch.append(normalized)
        batch_bytes += _approx_row_bytes(normalized)
        # Flush on either bound so a run of large rows can't outgrow memory before the count limit.
        if len(batch) >= EXPORT_BATCH_SIZE or batch_bytes >= MAX_EXPORT_BATCH_BYTES:
            yield batch
            batch = []
            batch_bytes = 0
    if batch:
        yield batch


def get_rows(
    host: str,
    credentials: QualtricsCredentials,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[QualtricsResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = QUALTRICS_ENDPOINTS[endpoint]

    # Re-check at run time (not just at source-create) in case the host was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(host, team_id)
    if not host_ok:
        raise QualtricsHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    client = QualtricsClient(host, credentials, api_version, logger)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if not config.fans_out_over_surveys:
        yield from _iter_collection(
            client,
            client.url(config.path),
            resumable_source_manager,
            start_url=resume.next_page if resume else None,
        )
        return

    survey_ids = _survey_ids(client)
    start_index = resume.parent_index if resume else 0
    if start_index:
        logger.debug(f"Qualtrics: resuming {endpoint} from survey {start_index} of {len(survey_ids)}")

    start_date = (
        format_incremental_value(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value is not None
        else None
    )

    for index in range(start_index, len(survey_ids)):
        survey_id = survey_ids[index]
        yield from _rows_for_survey(client, config, survey_id, start_date, logger)
        # Saved AFTER the survey's rows are yielded, so a crash replays that survey instead
        # of skipping it — merge dedupes on the composite primary key.
        resumable_source_manager.save_state(QualtricsResumeConfig(parent_index=index + 1))


def _rows_for_survey(
    client: QualtricsClient,
    config: QualtricsEndpointConfig,
    survey_id: str,
    start_date: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    if config.fetch_mode == "survey_export":
        yield from _export_responses(client, survey_id, start_date, logger)
        return

    if config.fetch_mode == "survey_query":
        url = client.url(config.path, {"surveyId": survey_id})
        for page in _iter_collection(client, url, resumable_source_manager=None):
            yield [{**row, "surveyId": survey_id} for row in page]
        return

    payload = client.get_json(client.url(config.path.format(survey_id=survey_id)))
    elements = _elements(payload)
    if elements:
        yield [{**row, "surveyId": survey_id} for row in elements]


def validate_credentials(
    datacenter_id: str,
    credentials: QualtricsCredentials,
    api_version: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Confirm the credentials are genuine, and (when scoped) that the endpoint is reachable.

    Qualtrics grants permissions per resource, so at source-create a working `whoami` is
    enough — a user may legitimately lack access to endpoints they never intend to sync. A
    scoped probe additionally requests that endpoint and treats 403 as a hard failure.
    """
    try:
        host = validate_host(datacenter_id)
    except QualtricsConfigurationError as e:
        return False, str(e)

    # The host is customer-supplied, so block ones resolving to private/internal addresses.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    client = QualtricsClient(host, credentials, api_version)

    probe_path = VALIDATION_PATHS.get(schema_name or "", "/whoami")
    try:
        client.get_json(client.url(probe_path))
    except QualtricsConfigurationError as e:
        return False, str(e)
    except QualtricsHostNotAllowedError:
        return False, HOST_NOT_ALLOWED_ERROR
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 401:
            return False, "Invalid Qualtrics credentials"
        if status == 403:
            if schema_name is None:
                # A valid credential that can't read `whoami` is still valid; scope problems
                # surface per table rather than blocking the whole source.
                return True, None
            return False, f"Your Qualtrics credentials lack permission to read {schema_name}"
        return False, str(e)
    except (QualtricsRetryableError, requests.exceptions.RequestException) as e:
        return False, str(e)

    return True, None


def qualtrics_source(
    datacenter_id: str,
    credentials: QualtricsCredentials,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[QualtricsResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = QUALTRICS_ENDPOINTS[endpoint]
    host = validate_host(datacenter_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            credentials=credentials,
            endpoint=endpoint,
            api_version=api_version,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Fan-out endpoints arrive grouped by survey, not globally ascending by the cursor —
        # `desc` defers the watermark to the end of the run instead of advancing it past
        # surveys a crashed run still owes.
        sort_mode="desc" if config.fans_out_over_surveys else "asc",
    )
