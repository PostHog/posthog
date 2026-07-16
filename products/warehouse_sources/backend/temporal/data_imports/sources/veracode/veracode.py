import os
import hmac
import time
import hashlib
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.veracode.settings import (
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


class VeracodeRetryableError(Exception):
    pass


@dataclasses.dataclass
class VeracodeResumeConfig:
    # Next zero-based HAL page to fetch. For fan-out endpoints this is the page within `app_guid`.
    page: int = 0
    # Fan-out only: the application GUID currently being processed. None for top-level endpoints.
    app_guid: str | None = None


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
    session = make_tracked_session(retry=Retry(total=0))
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


@retry(
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
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise VeracodeRetryableError(f"Veracode API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Veracode API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _total_pages(data: dict) -> int:
    return int(data.get("page", {}).get("total_pages", 0) or 0)


def _build_url(region: str | None, path: str, params: dict[str, Any]) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None})
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


def _iter_application_guids(
    session: requests.Session, region: str | None, logger: FilteringBoundLogger
) -> Iterator[str]:
    """Page through /applications and yield each application GUID (drives fan-out endpoints)."""
    page = 0
    while True:
        url = _build_url(region, VERACODE_ENDPOINTS["applications"].path, {"size": PAGE_SIZE, "page": page})
        data = _fetch_page(session, url, logger)
        for item in data.get("_embedded", {}).get("applications", []):
            guid = item.get("guid")
            if guid:
                yield guid
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
    params: dict[str, Any],
) -> Iterator[list[dict[str, Any]]]:
    """Iterate every application and page through the per-application child endpoint.

    Each child row is stamped with `application_guid` so the composite primary key is unique across
    the whole table (child ids are only unique within their parent application).
    """
    app_guids = list(_iter_application_guids(session, region, logger))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = app_guids
    resume_page = 0
    if resume is not None and resume.app_guid is not None and resume.app_guid in app_guids:
        remaining = app_guids[app_guids.index(resume.app_guid) :]
        resume_page = resume.page
        logger.debug(f"Veracode: resuming {config.name} from app_guid={resume.app_guid}, page={resume_page}")

    for index, app_guid in enumerate(remaining):
        path = config.path.format(application_guid=app_guid)
        page = resume_page
        resume_page = 0  # only the resumed-into application uses the saved page

        try:
            while True:
                url = _build_url(region, path, {**params, "page": page})
                data = _fetch_page(session, url, logger)
                rows = [
                    {**row, "application_guid": app_guid}
                    for row in data.get("_embedded", {}).get(config.embedded_key, [])
                ]

                page += 1
                has_more = page < _total_pages(data)

                if rows:
                    yield rows
                    if has_more:
                        resumable_source_manager.save_state(VeracodeResumeConfig(page=page, app_guid=app_guid))

                if not has_more:
                    break
        except requests.HTTPError as exc:
            # An application deleted between enumeration and this fetch 404s. Skip it rather than
            # failing the whole sync. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Veracode: application {app_guid} not found while fetching {config.name}, skipping")
            else:
                raise

        # Advance the bookmark to the next application so a crash between apps resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(VeracodeResumeConfig(page=0, app_guid=remaining[index + 1]))


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

    if config.fan_out_over_applications:
        yield from _iter_fan_out_rows(
            session, region, logger, resumable_source_manager, config, dict(config.extra_params)
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
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
