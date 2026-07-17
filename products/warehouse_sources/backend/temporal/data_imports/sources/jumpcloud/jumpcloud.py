import json
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.settings import (
    JUMPCLOUD_ENDPOINTS,
    JumpcloudEndpointConfig,
)

# JumpCloud hosts its EU tenants on separate regional bases.
CONSOLE_BASE_URLS: dict[str, str] = {
    "us": "https://console.jumpcloud.com",
    "eu": "https://console.eu.jumpcloud.com",
}
INSIGHTS_BASE_URLS: dict[str, str] = {
    "us": "https://api.jumpcloud.com",
    "eu": "https://api.eu.jumpcloud.com",
}

# Both the v1 and v2 console list endpoints cap `limit` at 100.
REST_PAGE_SIZE = 100
# Directory Insights allows up to 10,000 events per page; keep pages smaller since each
# event is a sizeable JSON document and pages are yielded whole.
EVENTS_PAGE_SIZE = 1000
# Directory Insights retention is plan-gated (up to 90 days), so reaching back further on
# the first sync can never return more data.
DEFAULT_EVENTS_LOOKBACK_DAYS = 90
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60


class JumpcloudRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class JumpcloudResumeConfig:
    # Offset of the next page for the limit/skip REST entity endpoints.
    skip: int = 0
    # Directory Insights deep-paging cursor (the X-Search_After response header), only valid
    # against an identical query, so the time window it was issued for is persisted with it.
    search_after: list[Any] | None = None
    start_time: str | None = None
    end_time: str | None = None


def _get_headers(api_key: str, org_id: str | None = None) -> dict[str, str]:
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    # MSP/MTP admin keys act on a sub-organization selected via x-org-id.
    if org_id:
        headers["x-org-id"] = org_id
    return headers


def _make_session(api_key: str, org_id: str | None = None, capture: bool = True) -> requests.Session:
    # `redact_values` masks the API key in logged URLs and captured HTTP samples so a failed
    # or sampled request can never persist the raw JumpCloud credential in HTTP telemetry.
    # `capture=False` is used for secret-bearing endpoints: HTTP sample capture writes the raw
    # response body during `send()`, before row-level `redact_keys` runs, and the generic sampler
    # doesn't recognize JumpCloud's camel-case secret fields (e.g. `config.idpPrivateKey`). Keeping
    # those responses out of sample storage is the only place the SAML signing key can be stopped.
    return make_tracked_session(headers=_get_headers(api_key, org_id), redact_values=(api_key,), capture=capture)


def _console_base_url(region: str) -> str:
    return CONSOLE_BASE_URLS.get(region, CONSOLE_BASE_URLS["us"])


def _insights_base_url(region: str) -> str:
    return INSIGHTS_BASE_URLS.get(region, INSIGHTS_BASE_URLS["us"])


def _format_rfc3339(value: Any) -> str:
    """Directory Insights wants RFC 3339 timestamps with a literal ``Z`` suffix."""
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return _format_rfc3339(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _parse_retry_after(response: requests.Response) -> float | None:
    """JumpCloud sends ``Retry-After`` in whole seconds on 429. Ignore HTTP-date forms."""
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, JumpcloudRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


@retry(
    retry=retry_if_exception_type((JumpcloudRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)
def _request(
    session: requests.Session,
    method: str,
    url: str,
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
) -> requests.Response:
    # Don't follow redirects: the session carries the API key in the x-api-key header, which
    # requests would replay to a cross-origin redirect target (only the standard Authorization
    # header is stripped), leaking the credential.
    response = session.request(method, url, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

    if response.status_code == 429 or response.status_code >= 500:
        retry_after = _parse_retry_after(response) if response.status_code == 429 else None
        raise JumpcloudRetryableError(
            f"JumpCloud API error (retryable): status={response.status_code}, url={url}",
            retry_after=retry_after,
        )

    # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather than
    # silently parsing the redirect body as data.
    if response.is_redirect or response.is_permanent_redirect:
        raise ValueError(
            f"JumpCloud API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
        )

    if not response.ok:
        # Don't log the response body: JumpCloud error payloads can echo request details.
        logger.error(f"JumpCloud API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response


def _redact_key(row: dict[str, Any], dotted_key: str) -> dict[str, Any]:
    """Return ``row`` with a possibly-nested field removed. ``"config"`` drops a top-level field;
    ``"config.idpPrivateKey"`` walks into ``config`` and drops its ``idpPrivateKey``. Only the nodes
    on the path are copied, so the upstream row is left unmodified; a missing or non-dict node is a
    no-op."""
    head, _, rest = dotted_key.partition(".")
    if head not in row:
        return row
    if not rest:
        return {k: v for k, v in row.items() if k != head}
    nested = row[head]
    if not isinstance(nested, dict):
        return row
    return {**row, head: _redact_key(nested, rest)}


def _redact_row(row: Any, redact_keys: list[str]) -> Any:
    if not isinstance(row, dict):
        return row
    for key in redact_keys:
        row = _redact_key(row, key)
    return row


def _parse_search_after(raw: str | None, logger: FilteringBoundLogger) -> list[Any] | None:
    """Decode the ``X-Search_After`` response header (a JSON-encoded array) into the cursor
    to send as ``search_after`` in the next query body."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(f"JumpCloud: could not parse X-Search_After header: {raw!r}")
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    return parsed


def _get_rest_rows(
    session: requests.Session,
    base_url: str,
    config: JumpcloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JumpcloudResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Page through a v1/v2 console list endpoint with limit/skip pagination."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    skip = resume.skip if resume else 0
    if resume:
        logger.debug(f"JumpCloud: resuming {config.name} from skip={skip}")

    while True:
        params: dict[str, Any] = {"limit": REST_PAGE_SIZE, "skip": skip}
        if config.sort:
            params["sort"] = config.sort
        url = f"{base_url}{config.path}?{urlencode(params)}"

        response = _request(session, "GET", url, logger)
        data = response.json()

        # v1 wraps rows as {"totalCount": n, "results": [...]}; v2 returns a bare array. Any
        # other 200 payload is a permanent API-contract violation, not a transient failure.
        if config.api == "v1":
            rows = data.get("results") if isinstance(data, dict) else None
        else:
            rows = data if isinstance(data, list) else None
        if not isinstance(rows, list):
            raise ValueError(f"JumpCloud API returned an unexpected response shape: url={url}")

        if not rows:
            break

        yield rows

        # A short page means we've reached the end of the resource.
        if len(rows) < REST_PAGE_SIZE:
            break

        skip += len(rows)
        # Save AFTER yielding so a crash re-runs from the last persisted offset rather than
        # skipping ahead; the merge dedupes any re-pulled rows on the primary key.
        resumable_source_manager.save_state(JumpcloudResumeConfig(skip=skip))


def _get_event_rows(
    session: requests.Session,
    base_url: str,
    config: JumpcloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JumpcloudResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Page through Directory Insights events with the search_after deep-paging cursor.

    The query window is [watermark (or the 90-day retention cap on the first sync), sync
    start]. The window is server-side, so pagination terminates at the window edge without
    any client-side watermark checks.
    """
    url = f"{base_url}{config.path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.start_time and resume.end_time:
        # A search_after cursor is only valid against an identical query, so a resumed
        # attempt re-uses the exact window the cursor was issued for.
        start_time = resume.start_time
        end_time = resume.end_time
        search_after = resume.search_after
        logger.debug(f"JumpCloud: resuming events from search_after={search_after}")
    else:
        start_value = db_incremental_field_last_value if should_use_incremental_field else None
        if not start_value:
            start_value = datetime.now(UTC) - timedelta(days=DEFAULT_EVENTS_LOOKBACK_DAYS)
        start_time = _format_rfc3339(start_value)
        # Pin the window's end at sync start so every page (and any resumed attempt) queries
        # the same immutable window.
        end_time = _format_rfc3339(datetime.now(UTC))
        search_after = None

    while True:
        body: dict[str, Any] = {
            "service": ["all"],
            "start_time": start_time,
            "end_time": end_time,
            "limit": EVENTS_PAGE_SIZE,
        }
        if search_after:
            body["search_after"] = search_after

        response = _request(session, "POST", url, logger, json_body=body)
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError(f"JumpCloud Directory Insights returned a non-list response: url={url}")

        if not rows:
            break

        next_search_after = _parse_search_after(response.headers.get("X-Search_After"), logger)

        yield rows

        if len(rows) < EVENTS_PAGE_SIZE or not next_search_after:
            break

        search_after = next_search_after
        # Save AFTER yielding so a crash re-fetches the last page rather than skipping it;
        # the merge dedupes re-pulled events on `id`.
        resumable_source_manager.save_state(
            JumpcloudResumeConfig(search_after=search_after, start_time=start_time, end_time=end_time)
        )


def validate_credentials(
    api_key: str,
    org_id: str | None = None,
    region: str = "us",
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Probe a cheap endpoint to confirm the API key is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the key is valid but the
    admin's role may simply lack access to this particular probe. A scoped probe
    (``schema_name`` set) treats 403 as a hard failure.
    """
    endpoint = JUMPCLOUD_ENDPOINTS.get(schema_name) if schema_name else None
    # A scoped probe against a secret-bearing endpoint returns rows too, so keep its response out
    # of HTTP sample capture as well.
    session = _make_session(api_key, org_id, capture=not (endpoint is not None and endpoint.redact_keys))

    try:
        if endpoint is not None and endpoint.api == "insights":
            now = datetime.now(UTC)
            response = session.post(
                f"{_insights_base_url(region)}{endpoint.path}",
                json={
                    "service": ["all"],
                    "start_time": _format_rfc3339(now - timedelta(days=1)),
                    "end_time": _format_rfc3339(now),
                    "limit": 1,
                },
                timeout=10,
                allow_redirects=False,
            )
        else:
            path = endpoint.path if endpoint is not None else "/api/systemusers"
            response = session.get(f"{_console_base_url(region)}{path}?limit=1", timeout=10, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    # Never follow a redirect with the credentialed session (see _request).
    if response.is_redirect or response.is_permanent_redirect:
        return False, "JumpCloud API returned an unexpected redirect"

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid JumpCloud API key"

    if response.status_code == 403:
        if schema_name is None:
            # Valid key, missing access for this probe — let source creation through.
            return True, None
        return False, "Your JumpCloud API key does not have permission to read this data"

    try:
        body = response.json()
        return False, body.get("message", response.text)
    except Exception:
        return False, response.text


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JumpcloudResumeConfig],
    org_id: str | None = None,
    region: str = "us",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = JUMPCLOUD_ENDPOINTS[endpoint]
    # One session reused across every page so urllib3 keeps the connection alive. Endpoints that
    # redact secret-bearing fields opt out of HTTP sample capture entirely, since capture records
    # the raw body before those fields can be stripped.
    session = _make_session(api_key, org_id, capture=not config.redact_keys)

    if config.api == "insights":
        pages = _get_event_rows(
            session,
            _insights_base_url(region),
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        pages = _get_rest_rows(session, _console_base_url(region), config, logger, resumable_source_manager)

    # Strip secret-bearing fields (e.g. an SSO app's SAML private key) before any row reaches the
    # warehouse. Redaction happens here, outside the paginators, so state checkpointing still runs
    # on the raw upstream response shape.
    if config.redact_keys:
        for page in pages:
            yield [_redact_row(row, config.redact_keys) for row in page]
    else:
        yield from pages


def jumpcloud_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JumpcloudResumeConfig],
    org_id: str | None = None,
    region: str = "us",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = JUMPCLOUD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            org_id=org_id,
            region=region,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[endpoint_config.primary_key],
        # Directory Insights doesn't document a guaranteed response ordering for the events
        # query, so "desc" keeps the incremental watermark safe: it's persisted once, as the
        # run's max, only after the whole window has been walked. The REST endpoints are
        # full refresh, where sort_mode has no watermark to corrupt.
        sort_mode="desc" if endpoint_config.api == "insights" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
