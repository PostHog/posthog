import io
import re
import csv
import time
import dataclasses
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import IO, Any, Optional, cast

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.settings import (
    ASSET_MAX_RETURN,
    BULK_WINDOW_DAYS,
    MARKETO_ENDPOINTS,
    REST_BATCH_SIZE,
    MarketoEndpointConfig,
)

# Every Marketo instance is reachable at <munchkin id>.mktorest.com — the host is not
# customer-supplied, so there is no credential-retargeting surface here.
MARKETO_DOMAIN_SUFFIX = ".mktorest.com"
MARKETO_HOST_TEMPLATE = "https://{munchkin_id}" + MARKETO_DOMAIN_SUFFIX
MUNCHKIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")

REQUEST_TIMEOUT_SECONDS = 120
# Access tokens live an hour; re-mint a minute early so a long page fetch can't straddle expiry.
TOKEN_EXPIRY_SAFETY_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# Marketo asks callers to check bulk export status no more than once a minute.
BULK_POLL_INTERVAL_SECONDS = 60
BULK_MAX_POLL_ATTEMPTS = 120
BULK_CHUNK_ROWS = 2000
# Bulk lead exports name every column explicitly; keep the request body bounded on instances
# with thousands of custom fields.
MAX_LEAD_EXPORT_FIELDS = 300

DEFAULT_BULK_LOOKBACK_DAYS = 365

# Body-level codes Marketo returns with HTTP 200. These are transient: rate/concurrency limits,
# request timeouts, and "too many bulk jobs queued".
RETRYABLE_ERROR_CODES = frozenset({"604", "606", "608", "615", "1029"})
# The token went stale mid-sync — re-mint once and replay the request.
TOKEN_ERROR_CODES = frozenset({"601", "602"})


class MarketoAPIError(Exception):
    pass


class MarketoRetryableError(MarketoAPIError):
    pass


class MarketoTokenError(MarketoAPIError):
    pass


class MarketoAuthError(MarketoAPIError):
    pass


@dataclasses.dataclass
class MarketoResumeConfig:
    """Cursor for whichever transport the endpoint uses.

    Only one of the three is populated per endpoint; they are kept on one dataclass because the
    resume manager stores a single dataclass type per source.
    """

    next_page_token: Optional[str] = None
    offset: Optional[int] = None
    window_start: Optional[str] = None


def build_base_url(munchkin_id: str) -> str:
    munchkin = (munchkin_id or "").strip()
    # People paste the whole endpoint from Admin → Web Services, so accept that shape too.
    if munchkin.startswith("https://"):
        munchkin = munchkin[len("https://") :]
    munchkin = munchkin.rstrip("/")
    if munchkin.endswith(MARKETO_DOMAIN_SUFFIX):
        munchkin = munchkin[: -len(MARKETO_DOMAIN_SUFFIX)]
    if not MUNCHKIN_ID_PATTERN.match(munchkin):
        raise ValueError(f"Invalid Marketo Munchkin account ID: {munchkin_id!r}")
    return MARKETO_HOST_TEMPLATE.format(munchkin_id=munchkin)


def format_datetime(value: Any) -> str:
    """Render a cursor value as the ISO 8601 instant Marketo's filters expect."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        return value
    else:
        return str(value)

    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_datetime(value: Any) -> Optional[datetime]:
    """Best-effort parse of a stored cursor value back into an aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def raise_for_marketo_errors(body: Mapping[str, Any]) -> None:
    """Marketo reports failures in a 200 body: ``{"success": false, "errors": [...]}``."""
    if body.get("success", True):
        return

    errors = body.get("errors") or []
    first = errors[0] if errors else {}
    code = str(first.get("code", ""))
    message = first.get("message", "Unknown Marketo error")
    text = f"Marketo API error {code}: {message}"

    if code in RETRYABLE_ERROR_CODES:
        raise MarketoRetryableError(text)
    if code in TOKEN_ERROR_CODES:
        raise MarketoTokenError(text)
    raise MarketoAPIError(text)


class MarketoClient:
    """Minimal Marketo transport: one host, one client-credentials token, three request shapes."""

    def __init__(self, munchkin_id: str, client_id: str, client_secret: str) -> None:
        self._base_url = build_base_url(munchkin_id)
        self._client_id = client_id
        self._client_secret = client_secret
        # The identity endpoint takes the credentials as query params, so redact both literals
        # from tracked-transport logs and sampled bodies. capture=False keeps every Marketo
        # response — lead emails and arbitrary customer campaign/form fields the generic
        # scrubber can't recognise — out of HTTP sample storage while still metering and logging.
        self._session = make_tracked_session(redact_values=(client_id, client_secret), capture=False)
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def base_url(self) -> str:
        return self._base_url

    def _redact(self, text: str) -> str:
        """Strip credential literals from text bound for logs or a persisted error."""
        for secret in (self._client_secret, self._client_id):
            if secret:
                text = text.replace(secret, "***")
        return text

    def _mint_token(self) -> str:
        try:
            response = self._session.get(
                f"{self._base_url}/identity/oauth/token",
                params={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            # Connection/timeout errors carry the prepared URL, which here embeds the client
            # secret as a query param. That string is persisted as the import's latest_error,
            # so scrub the credentials before it can leak to anyone viewing failed imports.
            raise MarketoAuthError(f"Could not reach Marketo identity endpoint: {self._redact(str(e))}") from None
        if not response.ok:
            raise MarketoAuthError(
                f"Marketo authentication failed: status={response.status_code}, body={response.text[:500]}"
            )

        body = response.json()
        token = body.get("access_token")
        if not token:
            raise MarketoAuthError(f"Marketo authentication failed: no access token in response ({body})")

        raw_expires_in = body.get("expires_in")
        expires_in = int(raw_expires_in) if raw_expires_in is not None else 3600
        self._token = token
        self._token_expires_at = time.monotonic() + max(expires_in - TOKEN_EXPIRY_SAFETY_SECONDS, 0)
        return token

    def access_token(self, force_refresh: bool = False) -> str:
        if force_refresh or self._token is None or time.monotonic() >= self._token_expires_at:
            return self._mint_token()
        return self._token

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        stream: bool = False,
    ) -> requests.Response:
        """Issue one request, re-minting the token once on an HTTP 401."""

        def _send(token: str) -> requests.Response:
            return self._session.request(
                method,
                f"{self._base_url}{path}",
                params=dict(params) if params else None,
                json=dict(json_body) if json_body is not None else None,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                stream=stream,
            )

        response = _send(self.access_token())
        if response.status_code == 401:
            response = _send(self.access_token(force_refresh=True))

        if response.status_code in (401, 403):
            raise MarketoAuthError(
                f"Marketo authentication failed: status={response.status_code}, path={path}, body={response.text[:500]}"
            )
        response.raise_for_status()
        return response

    # Only body-level transient codes are retried here. HTTP-level 429/5xx retries already
    # happen inside the tracked session, so the two layers never stack.
    @retry(
        retry=retry_if_exception_type(MarketoRetryableError),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        try:
            body = self.request(method, path, params=params, json_body=json_body).json()
            raise_for_marketo_errors(body)
        except MarketoTokenError:
            # A stale token surfaces as a 200 body error rather than a 401; re-mint and replay once.
            self.access_token(force_refresh=True)
            body = self.request(method, path, params=params, json_body=json_body).json()
            raise_for_marketo_errors(body)
        return cast(dict[str, Any], body)


def validate_credentials(munchkin_id: str, client_id: str, client_secret: str) -> tuple[bool, Optional[str]]:
    try:
        client = MarketoClient(munchkin_id, client_id, client_secret)
    except ValueError as e:
        return False, str(e)

    try:
        client.access_token(force_refresh=True)
    except MarketoAuthError:
        return False, "Invalid Marketo client ID or client secret"
    except Exception:
        return False, "Could not reach Marketo — check your Munchkin account ID"
    return True, None


def _normalize_row(row: Mapping[Any, Any], int_columns: tuple[str, ...]) -> dict[str, Any]:
    """Blank CSV cells become NULL, and known numeric columns come back as integers."""
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        # csv.DictReader files any surplus columns under a `None` key; drop them.
        if key is None:
            continue
        if value == "" or value is None:
            normalized[key] = None
            continue
        if key in int_columns and isinstance(value, str):
            try:
                normalized[key] = int(value)
                continue
            except ValueError:
                pass
        normalized[key] = value
    return normalized


def bulk_windows(
    start: datetime, end: datetime, window_days: int = BULK_WINDOW_DAYS
) -> list[tuple[datetime, datetime]]:
    """Split [start, end) into windows Marketo's 31-day export filter cap will accept."""
    windows: list[tuple[datetime, datetime]] = []
    cursor = start
    step = timedelta(days=window_days)
    while cursor < end:
        window_end = min(cursor + step, end)
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


def _lead_export_fields(client: MarketoClient) -> list[str]:
    body = client.request_json("GET", "/rest/v1/leads/describe.json")
    names: list[str] = []
    for entry in body.get("result") or []:
        rest = entry.get("rest") or {}
        name = rest.get("name")
        if name:
            names.append(name)
    return names[:MAX_LEAD_EXPORT_FIELDS]


def _create_bulk_export(
    client: MarketoClient,
    obj: str,
    window: tuple[datetime, datetime],
    fields: Optional[list[str]],
) -> str:
    body: dict[str, Any] = {
        "format": "CSV",
        "filter": {"createdAt": {"startAt": format_datetime(window[0]), "endAt": format_datetime(window[1])}},
    }
    if fields:
        body["fields"] = fields

    created = client.request_json("POST", f"/bulk/v1/{obj}/export/create.json", json_body=body)
    results = created.get("result") or []
    if not results or not results[0].get("exportId"):
        raise MarketoAPIError(f"Marketo bulk export create returned no export id for {obj}")
    return str(results[0]["exportId"])


def _await_bulk_export(client: MarketoClient, obj: str, export_id: str, logger: FilteringBoundLogger) -> None:
    for _ in range(BULK_MAX_POLL_ATTEMPTS):
        # Sleep before the first poll: Marketo never completes a job instantly and polling
        # faster than once a minute is rejected.
        time.sleep(BULK_POLL_INTERVAL_SECONDS)
        body = client.request_json("GET", f"/bulk/v1/{obj}/export/{export_id}/status.json")
        results = body.get("result") or []
        status = results[0].get("status") if results else None

        if status == "Completed":
            return
        if status in ("Failed", "Cancelled"):
            reason = results[0].get("errorMsg") or "no reason given"
            raise MarketoAPIError(f"Marketo bulk export {export_id} ended as {status}: {reason}")
        logger.debug(f"Marketo bulk export {export_id} status={status}")

    raise MarketoAPIError(
        f"Marketo bulk export {export_id} did not complete within "
        f"{BULK_MAX_POLL_ATTEMPTS * BULK_POLL_INTERVAL_SECONDS} seconds"
    )


def _download_bulk_export(
    client: MarketoClient,
    obj: str,
    export_id: str,
    int_columns: tuple[str, ...],
) -> Iterator[list[dict[str, Any]]]:
    response = client.request("GET", f"/bulk/v1/{obj}/export/{export_id}/file.json", stream=True)

    if "application/json" in (response.headers.get("Content-Type") or ""):
        # A failed download comes back as a Marketo error envelope instead of CSV.
        raise_for_marketo_errors(response.json())
        return

    response.raw.decode_content = True
    # Wrap the raw stream rather than iterating lines: exported text columns can contain
    # newlines inside quoted fields, which line-splitting would tear apart.
    stream = io.TextIOWrapper(cast(IO[bytes], response.raw), encoding="utf-8", newline="")
    batch: list[dict[str, Any]] = []
    for row in csv.DictReader(stream):
        batch.append(_normalize_row(row, int_columns))
        if len(batch) >= BULK_CHUNK_ROWS:
            yield batch
            batch = []
    if batch:
        yield batch


def _bulk_rows(
    client: MarketoClient,
    config: MarketoEndpointConfig,
    start: datetime,
    end: datetime,
    resumable_source_manager: ResumableSourceManager[MarketoResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    fields = _lead_export_fields(client) if config.needs_field_list else None

    for window_start, window_end in bulk_windows(start, end):
        export_id = _create_bulk_export(client, config.path, (window_start, window_end), fields)
        client.request_json("POST", f"/bulk/v1/{config.path}/export/{export_id}/enqueue.json")
        _await_bulk_export(client, config.path, export_id, logger)

        yield from _download_bulk_export(client, config.path, export_id, config.int_columns)

        # Checkpoint on the window boundary only once the whole window has been yielded, so a
        # resumed attempt re-exports the window it died in rather than skipping its tail.
        resumable_source_manager.save_state(MarketoResumeConfig(window_start=format_datetime(window_end)))


def _rest_token_rows(
    client: MarketoClient,
    config: MarketoEndpointConfig,
    resumable_source_manager: ResumableSourceManager[MarketoResumeConfig],
    start_token: Optional[str],
) -> Iterator[list[dict[str, Any]]]:
    next_token = start_token
    while True:
        params: dict[str, Any] = {"batchSize": REST_BATCH_SIZE, **config.extra_params}
        if next_token:
            params["nextPageToken"] = next_token

        body = client.request_json("GET", config.path, params=params)
        rows = body.get("result") or []
        if rows:
            yield rows

        next_token = body.get("nextPageToken")
        # `moreResult` is absent on endpoints that return everything in one shot (activity types).
        if not body.get("moreResult") or not next_token:
            break

        resumable_source_manager.save_state(MarketoResumeConfig(next_page_token=next_token))


def _asset_offset_rows(
    client: MarketoClient,
    config: MarketoEndpointConfig,
    resumable_source_manager: ResumableSourceManager[MarketoResumeConfig],
    start_offset: int,
) -> Iterator[list[dict[str, Any]]]:
    offset = start_offset
    while True:
        params: dict[str, Any] = {"offset": offset, "maxReturn": ASSET_MAX_RETURN, **config.extra_params}
        body = client.request_json("GET", config.path, params=params)
        rows = body.get("result") or []
        if rows:
            yield rows

        # A short page is the API's end-of-collection signal; there is no total count.
        if len(rows) < ASSET_MAX_RETURN:
            break

        offset += len(rows)
        resumable_source_manager.save_state(MarketoResumeConfig(offset=offset))


def _resume_state(
    resumable_source_manager: ResumableSourceManager[MarketoResumeConfig],
) -> Optional[MarketoResumeConfig]:
    if not resumable_source_manager.can_resume():
        return None
    return resumable_source_manager.load_state()


def resolve_bulk_start(
    resume: Optional[MarketoResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    start_date: Optional[str],
    now: Optional[datetime] = None,
) -> datetime:
    """Pick where a bulk export run begins: resume cursor > incremental watermark > start date."""
    now = now or datetime.now(UTC)

    if resume is not None and resume.window_start:
        resumed = parse_datetime(resume.window_start)
        if resumed is not None:
            return resumed

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        watermark = parse_datetime(db_incremental_field_last_value)
        if watermark is not None:
            return watermark

    configured = parse_datetime(start_date) if start_date else None
    return configured or now - timedelta(days=DEFAULT_BULK_LOOKBACK_DAYS)


def get_rows(
    munchkin_id: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[MarketoResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    start_date: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = MARKETO_ENDPOINTS[endpoint]
    client = MarketoClient(munchkin_id, client_id, client_secret)
    resume = _resume_state(resumable_source_manager)

    if config.transport == "bulk":
        start = resolve_bulk_start(resume, should_use_incremental_field, db_incremental_field_last_value, start_date)
        yield from _bulk_rows(client, config, start, datetime.now(UTC), resumable_source_manager, logger)
    elif config.transport == "asset_offset":
        start_offset = resume.offset if resume is not None and resume.offset is not None else 0
        yield from _asset_offset_rows(client, config, resumable_source_manager, start_offset)
    else:
        start_token = resume.next_page_token if resume is not None else None
        yield from _rest_token_rows(client, config, resumable_source_manager, start_token)

    resumable_source_manager.clear_state()


def marketo_source(
    munchkin_id: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[MarketoResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    start_date: Optional[str] = None,
) -> SourceResponse:
    config = MARKETO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            munchkin_id=munchkin_id,
            client_id=client_id,
            client_secret=client_secret,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            start_date=start_date,
        ),
        primary_keys=config.primary_key,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
