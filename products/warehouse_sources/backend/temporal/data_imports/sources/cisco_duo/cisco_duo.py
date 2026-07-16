import re
import hmac
import base64
import hashlib
import dataclasses
import email.utils
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.settings import (
    CISCO_DUO_ENDPOINTS,
    DEFAULT_LOOKBACK_DAYS,
    CiscoDuoEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60

# Duo caps the v2 log endpoints at 1000 records per request; the v1 log endpoints return a
# fixed maximum of 1000 records with no limit param. The v1 resource lists default to 100.
LOG_V2_PAGE_SIZE = 1000
LOG_V1_PAGE_SIZE = 1000
LIST_V1_PAGE_SIZE = 100

# Duo Admin API hostnames are always vendor-issued (api-XXXXXXXX on one of these zones), so
# anything else is a mistyped or hostile host — reject rather than send signed requests to it.
ALLOWED_HOST_SUFFIXES = (".duosecurity.com", ".duofederal.com")

HOST_NOT_ALLOWED_ERROR = "Cisco Duo API hostname is not allowed"


class CiscoDuoRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class CiscoDuoHostNotAllowedError(Exception):
    pass


class CiscoDuoLogSaturationError(Exception):
    """More events share a single second than the v1 log API can page through, so the sync
    cannot advance without silently dropping audit records."""

    pass


@dataclasses.dataclass
class CiscoDuoResumeConfig:
    # v2 logs: opaque cursor within a fixed [mintime, maxtime] window (both ms).
    next_offset: str | None = None
    # v2 logs: window bounds (ms). v1 admin log: advancing mintime cursor (seconds).
    mintime: int | None = None
    maxtime: int | None = None
    # v1 resource lists: integer pagination offset.
    offset: int | None = None


def normalize_hostname(hostname: str) -> str:
    """Turn whatever the user typed into a bare Duo API host.

    Accepts values like ``api-xxxxxxxx.duosecurity.com``, ``https://api-xxxxxxxx.duosecurity.com/``,
    or ``api-xxxxxxxx.duosecurity.com/admin/v1`` and returns ``api-xxxxxxxx.duosecurity.com``.
    """
    hostname = hostname.strip()
    hostname = re.sub(r"^https?://", "", hostname, flags=re.IGNORECASE)
    hostname = hostname.split("/")[0]
    return hostname.strip().rstrip(".").lower()


def is_allowed_hostname(hostname: str) -> bool:
    return bool(re.match(r"^[a-z0-9.\-]+$", hostname)) and hostname.endswith(ALLOWED_HOST_SUFFIXES)


def _canonicalize_params(params: dict[str, str]) -> str:
    """Sort and percent-encode params exactly as Duo's signature scheme requires (RFC 3986,
    only unreserved characters left bare). The same string doubles as the request query string
    so what we sign is byte-for-byte what we send."""
    return "&".join(
        f"{quote(str(key), safe='~')}={quote(str(value), safe='~')}" for key, value in sorted(params.items())
    )


def sign_request(
    method: str, hostname: str, path: str, params: dict[str, str], integration_key: str, secret_key: str, date_str: str
) -> dict[str, str]:
    """Build the Date + Authorization headers for a Duo Admin API request.

    Duo authenticates every request with an HMAC-SHA1 signature over a canonical string of the
    date, method, host, path, and sorted params, sent as HTTP Basic auth with the integration
    key as the username.
    """
    canon = "\n".join([date_str, method.upper(), hostname.lower(), path, _canonicalize_params(params)])
    # Duo's Admin API mandates HMAC-SHA1 request signing — not used for secrecy or collision resistance.
    # nosemgrep: python.lang.security.insecure-hash-algorithms-sha1.insecure-hash-algorithm-sha1
    signature = hmac.new(secret_key.encode("utf-8"), canon.encode("utf-8"), hashlib.sha1).hexdigest()
    basic = base64.b64encode(f"{integration_key}:{signature}".encode()).decode()
    return {"Date": date_str, "Authorization": f"Basic {basic}", "Accept": "application/json"}


def _build_url(hostname: str, path: str, params: dict[str, str]) -> str:
    canon = _canonicalize_params(params)
    return f"https://{hostname}{path}" + (f"?{canon}" if canon else "")


def _parse_retry_after(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, CiscoDuoRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def _fetch_json_once(
    session: requests.Session,
    hostname: str,
    path: str,
    params: dict[str, str],
    integration_key: str,
    secret_key: str,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    # The Date header is part of the signature and Duo rejects requests with too much clock
    # skew, so re-sign with a fresh date on every attempt (retries can back off for minutes).
    headers = sign_request("GET", hostname, path, params, integration_key, secret_key, email.utils.formatdate())
    url = _build_url(hostname, path, params)

    # Don't follow redirects: the customer-controlled host could 3xx at an internal address,
    # defeating the host validation done before the request (SSRF).
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

    if response.status_code == 429 or response.status_code >= 500:
        retry_after = _parse_retry_after(response) if response.status_code == 429 else None
        raise CiscoDuoRetryableError(
            f"Cisco Duo API error (retryable): status={response.status_code}, path={path}", retry_after=retry_after
        )

    if response.is_redirect or response.is_permanent_redirect:
        raise CiscoDuoHostNotAllowedError(
            f"Cisco Duo API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
        )

    if not response.ok:
        logger.error(f"Cisco Duo API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    return response.json()


_fetch_json = retry(
    retry=retry_if_exception_type((CiscoDuoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)(_fetch_json_once)


def _to_epoch_seconds(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Cannot interpret incremental value as a timestamp: {value!r}")
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, str) and value.strip():
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
        parsed = dateutil_parser.parse(stripped)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    raise ValueError(f"Cannot interpret incremental value as a timestamp: {value!r}")


def _to_epoch_ms(value: Any) -> int:
    # Second-precision inputs (the common case: a `timestamp` watermark) land on the start of
    # their second, so the boundary second is re-pulled inclusively and merge dedupes it.
    return _to_epoch_seconds(value) * 1000


def _normalize_next_offset(raw: Any) -> str | None:
    """Duo's v2 `metadata.next_offset` is opaque: a two-element list on the authentication log,
    a string elsewhere. It is passed back verbatim as a comma-joined query param."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return ",".join(str(part) for part in raw) if raw else None
    text = str(raw)
    return text or None


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _get_log_v2_rows(
    session: requests.Session,
    hostname: str,
    integration_key: str,
    secret_key: str,
    config: CiscoDuoEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CiscoDuoResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Page a v2 log endpoint over a fixed [mintime, maxtime] window with the opaque
    next_offset cursor. The window is pinned at sync start (and preserved across resumes) so
    pagination stays deterministic while new events keep arriving."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume is not None and resume.mintime is not None and resume.maxtime is not None:
        mintime, maxtime, next_offset = resume.mintime, resume.maxtime, resume.next_offset
        logger.debug(f"Cisco Duo: resuming {config.name} window=[{mintime}, {maxtime}] next_offset={next_offset}")
    else:
        maxtime = _now_ms()
        if db_incremental_field_last_value is not None:
            # mintime is inclusive (>=): the boundary rows are re-fetched and merge dedupes
            # them on the primary key.
            mintime = min(_to_epoch_ms(db_incremental_field_last_value), maxtime)
        else:
            mintime = maxtime - DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60 * 1000
        next_offset = None

    while True:
        params: dict[str, str] = {
            "mintime": str(mintime),
            "maxtime": str(maxtime),
            "limit": str(LOG_V2_PAGE_SIZE),
            "sort": "ts:asc",
        }
        if next_offset:
            params["next_offset"] = next_offset

        data = _fetch_json(session, hostname, config.path, params, integration_key, secret_key, logger)
        wrapped = data.get("response") or {}
        items = wrapped.get(config.data_key) or []
        metadata = wrapped.get("metadata") or {}

        if items:
            yield items

        next_offset = _normalize_next_offset(metadata.get("next_offset"))
        if not next_offset:
            break

        # Save AFTER yielding so a crash re-yields the last page instead of skipping it.
        resumable_source_manager.save_state(
            CiscoDuoResumeConfig(next_offset=next_offset, mintime=mintime, maxtime=maxtime)
        )


def _row_timestamp(item: dict[str, Any]) -> int:
    try:
        return int(item.get("timestamp") or 0)
    except (TypeError, ValueError):
        return 0


def _get_log_v1_rows(
    session: requests.Session,
    hostname: str,
    integration_key: str,
    secret_key: str,
    config: CiscoDuoEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CiscoDuoResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Page the v1 administrator log by advancing `mintime` (seconds) past the last yielded row.

    The endpoint returns up to 1000 records ascending with no other cursor, and rows carry no
    unique id (the table is append-only), so boundary rows already yielded are dropped
    client-side instead of being re-merged. On a full page the trailing rows that share the
    final second are held back and re-fetched on the next page, so a page cut inside one second
    cannot skip that second's remaining events.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    cursor: int | None
    if resume is not None and resume.mintime is not None:
        cursor = resume.mintime
        logger.debug(f"Cisco Duo: resuming {config.name} from mintime={cursor}")
    elif db_incremental_field_last_value is not None:
        cursor = _to_epoch_seconds(db_incremental_field_last_value)
    else:
        cursor = None

    while True:
        params = {"mintime": str(cursor if cursor is not None else 0)}
        data = _fetch_json(session, hostname, config.path, params, integration_key, secret_key, logger)
        items = data.get("response") or []
        full_page = len(items) >= LOG_V1_PAGE_SIZE

        # Duo's docs are ambiguous on whether mintime is inclusive, so drop already-yielded
        # boundary rows here — harmless if the server already excluded them.
        fresh = [item for item in items if cursor is None or _row_timestamp(item) > cursor]

        if not fresh:
            if full_page:
                # A full page with no rows past the cursor second means more than one page of
                # events share that second. The v1 admin log can only page by mintime (seconds),
                # so advancing would silently drop the remaining same-second audit records.
                # Fail loudly instead — for an audit table, a missing record is worse than a
                # stalled sync.
                raise CiscoDuoLogSaturationError(
                    f"Cisco Duo {config.name}: more than {LOG_V1_PAGE_SIZE} events at timestamp {cursor}. "
                    f"The v1 log API cannot paginate within a single second, so the sync cannot advance "
                    f"without dropping audit records."
                )
            break

        if full_page:
            last_timestamp = _row_timestamp(fresh[-1])
            kept = [item for item in fresh if _row_timestamp(item) < last_timestamp]
            # If the whole fresh page shares one second there is nothing safe to hold back;
            # yield it all. The next iteration re-fetches from that second and either finishes
            # (fewer than a full page there) or raises the saturation error above.
            to_yield = kept or fresh
        else:
            to_yield = fresh

        yield to_yield
        cursor = _row_timestamp(to_yield[-1])
        resumable_source_manager.save_state(CiscoDuoResumeConfig(mintime=cursor))

        if not full_page:
            break


def _get_list_v1_rows(
    session: requests.Session,
    hostname: str,
    integration_key: str,
    secret_key: str,
    config: CiscoDuoEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CiscoDuoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Page a v1 resource list with limit/offset, following the integer `next_offset` from the
    top-level response metadata until it is absent."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None and resume.offset is not None else 0
    if offset:
        logger.debug(f"Cisco Duo: resuming {config.name} from offset={offset}")

    while True:
        params = {"limit": str(LIST_V1_PAGE_SIZE), "offset": str(offset)}
        data = _fetch_json(session, hostname, config.path, params, integration_key, secret_key, logger)
        items = data.get("response") or []
        metadata = data.get("metadata") or {}

        if items:
            if config.redact_fields:
                for item in items:
                    for field_name in config.redact_fields:
                        item.pop(field_name, None)
            yield items

        raw_next_offset = metadata.get("next_offset")
        if raw_next_offset is None or raw_next_offset in ("", []):
            break
        offset = int(raw_next_offset)
        resumable_source_manager.save_state(CiscoDuoResumeConfig(offset=offset))


def get_rows(
    api_hostname: str,
    integration_key: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CiscoDuoResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CISCO_DUO_ENDPOINTS[endpoint]
    hostname = normalize_hostname(api_hostname)

    if not is_allowed_hostname(hostname):
        raise CiscoDuoHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)

    # Re-check at run time (not just at source-create) in case the hostname was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        raise CiscoDuoHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    last_value = db_incremental_field_last_value if should_use_incremental_field else None

    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request. HTTP sample capture records the raw response before
    # redact_fields is applied, so disable it for endpoints whose responses carry secrets the
    # name-based sample scrubbers can't recognise (e.g. an integration's secret_key).
    session = make_tracked_session(capture=not bool(config.redact_fields))

    if config.api_style == "log_v2":
        yield from _get_log_v2_rows(
            session, hostname, integration_key, secret_key, config, logger, resumable_source_manager, last_value
        )
    elif config.api_style == "log_v1":
        yield from _get_log_v1_rows(
            session, hostname, integration_key, secret_key, config, logger, resumable_source_manager, last_value
        )
    else:
        yield from _get_list_v1_rows(
            session, hostname, integration_key, secret_key, config, logger, resumable_source_manager
        )


def validate_credentials(
    api_hostname: str,
    integration_key: str,
    secret_key: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Probe a cheap signed request to confirm the integration + secret key pair is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: Duo Admin API permissions are
    granular (read information / read log / read resource), so a valid key pair may lack the
    permission for this particular probe. A scoped probe (``schema_name`` set) treats 403 as a
    hard failure.
    """
    hostname = normalize_hostname(api_hostname)
    if not hostname or not is_allowed_hostname(hostname):
        return False, "Invalid Cisco Duo API hostname — it should look like api-XXXXXXXX.duosecurity.com"

    # The hostname is customer-controlled, so block hosts that resolve to private/internal
    # addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    path = "/admin/v1/users"
    params = {"limit": "1"}
    headers = sign_request("GET", hostname, path, params, integration_key, secret_key, email.utils.formatdate())
    try:
        # Don't follow redirects: the validated host could 3xx at an internal address,
        # defeating the host check above (SSRF).
        response = make_tracked_session().get(
            _build_url(hostname, path, params), headers=headers, timeout=10, allow_redirects=False
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, (
            "Invalid Cisco Duo credentials. Check the integration key, secret key, and API hostname "
            "of your Admin API application — a large clock skew can also cause this."
        )

    if response.status_code == 403:
        if schema_name is None:
            # Valid key pair, missing permission for this probe — let source creation through.
            return True, None
        return False, "Your Duo Admin API application lacks the required permission for this endpoint"

    try:
        body = response.json()
        return False, str(body.get("message", response.text))
    except Exception:
        return False, response.text


def cisco_duo_source(
    api_hostname: str,
    integration_key: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CiscoDuoResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = CISCO_DUO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_hostname=api_hostname,
            integration_key=integration_key,
            secret_key=secret_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # The v2 log endpoints are requested with sort=ts:asc and the v1 admin log returns
        # ascending from mintime. The resource lists aren't time-ordered, but they are
        # full-refresh only so no watermark depends on their ordering.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format=endpoint_config.partition_format if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
