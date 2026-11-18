import os
import hmac
import time
import hashlib
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    interruptible_wait,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.veracode.settings import (
    FAN_OUT_PARENTS,
    PAGE_SIZE,
    VERACODE_ENDPOINTS,
    VeracodeEndpointConfig,
)

# Region -> REST API host. Veracode isolates data per region, and the signing host must match the
# host the request is actually sent to, so the region choice picks both.
REGION_HOSTS: dict[str, str] = {
    "com": "api.veracode.com",  # US commercial (default)
    "eu": "api.veracode.eu",  # European region
    "us": "api.veracode.us",  # US federal (FedRAMP)
}
DEFAULT_REGION = "com"

_HMAC_VERSION = b"vcode_request_version_1"
_AUTH_SCHEME = "VERACODE-HMAC-SHA-256"

# Applications API modified_after filter is day-granular; re-pull the whole day around the watermark
# and let merge dedupe on the primary key so nothing is missed at the day boundary.
MODIFIED_AFTER_LOOKBACK_DAYS = 1

REQUEST_TIMEOUT_SECONDS = 60

# The Reporting API rejects a `last_updated_start_date` more than six months back. 180 days is
# inside six calendar months from any date.
REPORT_MAX_LOOKBACK_DAYS = 180
REPORT_POLL_INTERVAL_SECONDS = 15
REPORT_POLL_BUDGET_SECONDS = 60 * 60
REPORT_PENDING_STATUSES = frozenset({"QUEUED", "SUBMITTED", "PROCESSING"})


class VeracodeRetryableError(Exception):
    pass


class VeracodeReportError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class VeracodeResumeConfig:
    # Next zero-based HAL page to fetch. For fan-out endpoints this is the page within `app_guid`.
    page: int = 0
    # Fan-out only: the parent currently being processed (an application GUID, or an SCA workspace id).
    # None for top-level endpoints. The name predates workspace fan-out and is kept for saved states.
    app_guid: str | None = None
    # Reporting API only: the submitted report that `page` reads from.
    report_id: str | None = None


def _strip_region_prefix(credential: str) -> str:
    """Strip the region prefix from a Veracode credential.

    Newer credentials are issued as `<prefix>-<hex>` (e.g. `vera01ei-abc123...`); the prefix is not
    part of the signing material and must be removed from both the id and the secret before use.
    Legacy credentials have no `-` and pass through unchanged.
    """
    return credential.rsplit("-", 1)[-1]


def _calculate_signature(api_secret: str, signing_data: str, timestamp_ms: int, nonce_hex: str) -> str:
    """Compute the Veracode HMAC-SHA-256 request signature via the documented key-derivation chain."""
    key = bytes.fromhex(_strip_region_prefix(api_secret))
    nonce = bytes.fromhex(nonce_hex)
    key_nonce = hmac.new(key, nonce, hashlib.sha256).digest()
    key_date = hmac.new(key_nonce, str(timestamp_ms).encode(), hashlib.sha256).digest()
    signature_key = hmac.new(key_date, _HMAC_VERSION, hashlib.sha256).digest()
    return hmac.new(signature_key, signing_data.encode(), hashlib.sha256).hexdigest()


class VeracodeHMACAuth(requests.auth.AuthBase):
    """Signs each request with a per-request `VERACODE-HMAC-SHA-256` Authorization header.

    Applied at the session level so every attempt re-signs with a fresh timestamp and nonce — the
    signed timestamp expires, so retries must not reuse a stale signature.
    """

    def __init__(self, api_id: str, api_secret: str):
        self._api_id = _strip_region_prefix(api_id)
        self._api_secret = api_secret

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        parsed = urlparse(request.url or "")
        host = (parsed.hostname or "").lower()
        url = parsed.path or "/"
        if parsed.query:
            url = f"{url}?{parsed.query}"
        timestamp_ms = int(round(time.time() * 1000))
        nonce = os.urandom(16).hex()
        signing_data = f"id={self._api_id.lower()}&host={host}&url={url}&method={(request.method or 'GET').upper()}"
        signature = _calculate_signature(self._api_secret, signing_data, timestamp_ms, nonce)
        request.headers["Authorization"] = (
            f"{_AUTH_SCHEME} id={self._api_id},ts={timestamp_ms},nonce={nonce},sig={signature}"
        )
        return request


def resolve_host(region: str | None) -> str:
    return REGION_HOSTS.get(region or DEFAULT_REGION, REGION_HOSTS[DEFAULT_REGION])


def _base_url(region: str | None) -> str:
    return f"https://{resolve_host(region)}"


def _make_session(api_id: str, api_secret: str) -> requests.Session:
    # Disable urllib3-level retries so tenacity owns retry (it re-signs each attempt); a urllib3 retry
    # would resend the same prepared request with an expired signature.
    # capture=False: Veracode response bodies carry customers' vulnerability inventory (finding
    # locations, components, procedure names). The generic scrubber can't recognise those, so keep
    # them out of HTTP sample capture entirely rather than leak them outside the warehouse table.
    session = make_tracked_session(retry=Retry(total=0), redact_values=(api_id, api_secret), capture=False)
    session.auth = VeracodeHMACAuth(api_id, api_secret)
    session.headers.update({"Accept": "application/json"})
    return session


def validate_credentials(api_id: str, api_secret: str, region: str | None) -> tuple[bool, int | None]:
    """Probe the token with one cheap request. Returns (ok, status_code)."""
    url = f"{_base_url(region)}/appsec/v1/applications?size=1"
    try:
        response = _make_session(api_id, api_secret).get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code


def _fetch_page_once(
    session: requests.Session, url: str, logger: FilteringBoundLogger, json_body: dict[str, Any] | None = None
) -> dict:
    if json_body is None:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    else:
        response = session.post(url, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise VeracodeRetryableError(f"Veracode API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Veracode API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


@retry_with_deadline(
    retry=retry_if_exception_type(
        (
            VeracodeRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, logger: FilteringBoundLogger, json_body: dict[str, Any] | None = None
) -> dict:
    return _fetch_page_once(session, url, logger, json_body)


def _total_pages(data: dict) -> int:
    return int(data.get("page", {}).get("total_pages", 0) or 0)


def _build_url(region: str | None, path: str, params: dict[str, Any]) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
    return f"{_base_url(region)}{path}?{query}"


def _modified_after(db_incremental_field_last_value: Any) -> str | None:
    """Format the incremental watermark as a `modified_after` date, minus the day-granular lookback."""
    value = db_incremental_field_last_value
    if isinstance(value, datetime):
        as_date = value.astimezone(UTC).date() if value.tzinfo else value.date()
    elif isinstance(value, date):
        as_date = value
    else:
        return None
    return (as_date - timedelta(days=MODIFIED_AFTER_LOOKBACK_DAYS)).isoformat()


def _application_params(
    config: VeracodeEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"size": PAGE_SIZE, **config.extra_params}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        modified_after = _modified_after(db_incremental_field_last_value)
        if modified_after:
            params["modified_after"] = modified_after
    return params


def _iter_parent_ids(
    session: requests.Session, region: str | None, logger: FilteringBoundLogger, parent: str
) -> Iterator[str]:
    """Page through a parent endpoint and yield the id of each row (drives fan-out endpoints)."""
    parent_config = VERACODE_ENDPOINTS[parent]
    id_field = FAN_OUT_PARENTS[parent].id_field
    page = 0
    while True:
        url = _build_url(region, parent_config.path, {"size": PAGE_SIZE, **parent_config.extra_params, "page": page})
        data = _fetch_page(session, url, logger)
        for item in data.get("_embedded", {}).get(parent_config.embedded_key, []):
            parent_id = item.get(id_field)
            if parent_id:
                yield str(parent_id)
        page += 1
        if page >= _total_pages(data):
            break


def _iter_top_level_rows(
    session: requests.Session,
    region: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VeracodeResumeConfig],
    config: VeracodeEndpointConfig,
    params: dict[str, Any],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None and resume.app_guid is None else 0

    while True:
        url = _build_url(region, config.path, {**params, "page": page})
        data = _fetch_page(session, url, logger)
        rows = data.get("_embedded", {}).get(config.embedded_key, [])

        page += 1
        has_more = page < _total_pages(data)

        if rows:
            yield rows
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
            # dedupes on the primary key.
            if has_more:
                resumable_source_manager.save_state(VeracodeResumeConfig(page=page))

        if not has_more:
            break


def _iter_fan_out_rows(
    session: requests.Session,
    region: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VeracodeResumeConfig],
    config: VeracodeEndpointConfig,
    parent: str,
    params: dict[str, Any],
) -> Iterator[list[dict[str, Any]]]:
    """Iterate every parent row and page through the per-parent child endpoint.

    Each child row is stamped with the parent id (`application_guid` or `workspace_id`) so the
    composite primary key is unique across the whole table (child ids are only unique within their
    parent).
    """
    child_key = FAN_OUT_PARENTS[parent].child_key
    app_guids = list(_iter_parent_ids(session, region, logger, parent))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = app_guids
    resume_page = 0
    if resume is not None and resume.app_guid is not None and resume.app_guid in app_guids:
        remaining = app_guids[app_guids.index(resume.app_guid) :]
        resume_page = resume.page
        logger.debug(f"Veracode: resuming {config.name} from app_guid={resume.app_guid}, page={resume_page}")

    for index, app_guid in enumerate(remaining):
        path = config.path.format(**{child_key: app_guid})
        page = resume_page
        resume_page = 0  # only the resumed-into application uses the saved page

        try:
            while True:
                url = _build_url(region, path, {**params, "page": page})
                data = _fetch_page(session, url, logger)
                items = [data] if config.single_object else data.get("_embedded", {}).get(config.embedded_key, [])
                rows = [{**row, child_key: app_guid} for row in items]

                page += 1
                has_more = not config.single_object and page < _total_pages(data)

                if rows:
                    yield rows
                    if has_more:
                        resumable_source_manager.save_state(VeracodeResumeConfig(page=page, app_guid=app_guid))

                if not has_more:
                    break
        except requests.HTTPError as exc:
            # A parent deleted between enumeration and this fetch 404s. Skip it rather than failing the
            # whole sync. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Veracode: {parent} row {app_guid} not found while fetching {config.name}, skipping")
            else:
                raise

        # Advance the bookmark to the next application so a crash between apps resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(VeracodeResumeConfig(page=0, app_guid=remaining[index + 1]))


def _report_start_date(should_use_incremental_field: bool, db_incremental_field_last_value: Any, today: date) -> str:
    start = (today - timedelta(days=REPORT_MAX_LOOKBACK_DAYS)).isoformat()
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        modified_after = _modified_after(db_incremental_field_last_value)
        if modified_after and modified_after > start:
            start = modified_after
    return start


def _report_total_pages(data: dict) -> int:
    metadata = data.get("_embedded", {}).get("page_metadata") or data.get("page_metadata") or {}
    return int(metadata.get("total_pages", 0) or 0)


def _get_report_page(
    session: requests.Session,
    region: str | None,
    config: VeracodeEndpointConfig,
    report_id: str,
    page: int,
    logger: FilteringBoundLogger,
) -> dict:
    return _fetch_page(session, _build_url(region, f"{config.path}/{report_id}", {"page": page}), logger)


def _submit_report(
    session: requests.Session,
    region: str | None,
    config: VeracodeEndpointConfig,
    body: dict[str, Any],
    logger: FilteringBoundLogger,
) -> str:
    data = _fetch_page(session, f"{_base_url(region)}{config.path}", logger, json_body=body)
    report_id = data.get("_embedded", {}).get("id")
    if not report_id:
        raise VeracodeReportError(f"Veracode did not return a report id for the {config.name} report")
    return str(report_id)


def _await_report(
    session: requests.Session,
    region: str | None,
    config: VeracodeEndpointConfig,
    report_id: str,
    page: int,
    logger: FilteringBoundLogger,
    safe_point: Callable[[], None],
) -> dict:
    """Poll the report until it completes and return the requested page of results."""
    waited = 0
    while True:
        data = _get_report_page(session, region, config, report_id, page, logger)
        safe_point()
        status = data.get("_embedded", {}).get("status")
        if status == "COMPLETED":
            return data
        if status not in REPORT_PENDING_STATUSES:
            raise VeracodeReportError(
                f"Veracode could not generate the {config.name} report {report_id} (status {status})"
            )
        if waited >= REPORT_POLL_BUDGET_SECONDS:
            raise VeracodeReportError(
                f"Veracode {config.name} report {report_id} is still {status} after {waited} seconds"
            )
        interruptible_wait(REPORT_POLL_INTERVAL_SECONDS, safe_point=safe_point)
        waited += REPORT_POLL_INTERVAL_SECONDS


def _iter_report_rows(
    session: requests.Session,
    region: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VeracodeResumeConfig],
    config: VeracodeEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    manager = resumable_source_manager
    resume = manager.load_state() if manager.can_resume() else None

    data: dict | None = None
    report_id: str | None = None
    page = 0
    if resume is not None and resume.report_id:
        try:
            data = _await_report(session, region, config, resume.report_id, resume.page, logger, manager.safe_point)
            report_id, page = resume.report_id, resume.page
        except (requests.HTTPError, VeracodeRetryableError, VeracodeReportError):
            logger.warning(
                f"Veracode: saved {config.name} report {resume.report_id} is unreadable, requesting a new one"
            )

    if report_id is None or data is None:
        body = {
            "last_updated_start_date": _report_start_date(
                should_use_incremental_field, db_incremental_field_last_value, datetime.now(UTC).date()
            )
        }
        report_id = _submit_report(session, region, config, body, logger)
        page = 0
        # Commit the report id before polling, so a resumed attempt reads this report instead of
        # requesting another one.
        with manager.committing():
            manager.save_state(VeracodeResumeConfig(page=0, report_id=report_id))
        data = _await_report(session, region, config, report_id, page, logger, manager.safe_point)

    while True:
        rows = data.get("_embedded", {}).get(config.embedded_key) or []
        page += 1
        has_more = page < _report_total_pages(data)

        if has_more:
            manager.save_state(VeracodeResumeConfig(page=page, report_id=report_id))
        if rows:
            yield rows
        elif has_more:
            manager.safe_point()

        if not has_more:
            break
        data = _get_report_page(session, region, config, report_id, page, logger)


def get_rows(
    api_id: str,
    api_secret: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VeracodeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = VERACODE_ENDPOINTS[endpoint]
    session = _make_session(api_id, api_secret)

    if config.async_report:
        yield from _iter_report_rows(
            session,
            region,
            logger,
            resumable_source_manager,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    if config.fan_out_parent is not None:
        yield from _iter_fan_out_rows(
            session,
            region,
            logger,
            resumable_source_manager,
            config,
            config.fan_out_parent,
            {"size": PAGE_SIZE, **config.extra_params},
        )
        return

    params = _application_params(config, should_use_incremental_field, db_incremental_field_last_value)
    yield from _iter_top_level_rows(session, region, logger, resumable_source_manager, config, params)


def veracode_source(
    api_id: str,
    api_secret: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VeracodeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = VERACODE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_id=api_id,
            api_secret=api_secret,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # HAL pagination is deterministic and resumed by page number, so ordering doesn't gate resume;
        # ascending is the safe default for the day-granular applications watermark (paired with the
        # lookback above). Fan-out endpoints are full refresh.
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
