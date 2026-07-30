import json
import time
import hashlib
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.settings import (
    CHECKMARX_ENDPOINTS,
    CHECKMARX_REGION_HOSTS,
    CheckmarxEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

REQUEST_TIMEOUT = 60
TOKEN_REQUEST_TIMEOUT = 30
# Re-exchange the API key this many seconds before the current access token expires, so a request
# never goes out with a token that dies mid-flight. Checkmarx One access tokens are short-lived
# (~30 minutes) and syncs can run much longer.
TOKEN_REFRESH_LEEWAY = 120
# The OAuth client id Checkmarx One assigns to API-key (refresh token) exchanges.
TOKEN_CLIENT_ID = "ast-app"

AUTH_ERROR_PREFIX = "Checkmarx One authentication failed"


class CheckmarxRetryableError(Exception):
    pass


class CheckmarxAuthError(Exception):
    pass


@dataclasses.dataclass
class CheckmarxResumeConfig:
    # Row offset to resume the current page loop from.
    offset: int = 0
    # For fan-out endpoints: the scan currently being processed. A stable scan-id bookmark (not a
    # positional index) so scans created between a crash and the retry can't shift the resume point.
    scan_id: str | None = None


def _make_session(api_key: str) -> requests.Session:
    """Tracked session hardened for this source's traffic.

    Sample capture is disabled: responses carry customer vulnerability findings, repository URLs,
    and attack-vector details that the name-based scrubbers can't sanitise, so they must never
    reach the HTTP sample bucket. The API key is registered for value-based redaction, and
    redirects are refused so the token POST body (which carries the key) can never be re-sent to
    a redirect target — no Checkmarx One endpoint we call legitimately redirects.
    """
    return make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False)


def get_region_hosts(region: str) -> tuple[str, str]:
    """Return (api_base_url, iam_base_url) for a Checkmarx One region."""
    hosts = CHECKMARX_REGION_HOSTS.get(region)
    if hosts is None:
        raise ValueError(f"Unknown Checkmarx One region: {region}")
    return hosts


def _format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


class CheckmarxAuth:
    """Exchanges a Checkmarx One API key (an IAM refresh token) for a short-lived JWT bearer token,
    re-exchanging automatically as the token approaches expiry."""

    def __init__(self, session: requests.Session, iam_base_url: str, tenant_name: str, api_key: str) -> None:
        self._session = session
        self._token_url = (
            f"{iam_base_url}/auth/realms/{quote(tenant_name.strip(), safe='')}/protocol/openid-connect/token"
        )
        self._api_key = api_key
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        now = time.monotonic()
        if self._token is not None and now < self._expires_at - TOKEN_REFRESH_LEEWAY:
            return self._token

        response = self._session.post(
            self._token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": TOKEN_CLIENT_ID,
                "refresh_token": self._api_key,
            },
            timeout=TOKEN_REQUEST_TIMEOUT,
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise CheckmarxRetryableError(
                f"Checkmarx One IAM error (retryable): status={response.status_code}, url={self._token_url}"
            )
        if not response.ok:
            # Keycloak reports bad credentials as 400/401 with an error/error_description body
            # (e.g. invalid_grant for a revoked API key, "Realm does not exist" for a bad tenant).
            detail = ""
            try:
                payload = response.json()
                detail = payload.get("error_description") or payload.get("error") or ""
            except Exception:
                pass
            raise CheckmarxAuthError(
                f"{AUTH_ERROR_PREFIX}: status={response.status_code}"
                + (f", {detail}" if detail else "")
                + ". Check your tenant name, region, and API key."
            )

        payload = response.json()
        self._token = payload["access_token"]
        self._expires_at = time.monotonic() + float(payload.get("expires_in", 1800))
        return self._token


@retry(
    retry=retry_if_exception_type(
        (
            CheckmarxRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(
    session: requests.Session,
    auth: CheckmarxAuth,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    # The token is fetched inside the retried function so a transient IAM failure is retried too.
    headers = {
        "Authorization": f"Bearer {auth.get_token()}",
        # Checkmarx One versions its REST endpoints through the Accept header.
        "Accept": "application/json; version=1.0",
    }
    response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)

    if response.status_code == 429 or response.status_code >= 500:
        raise CheckmarxRetryableError(f"Checkmarx One API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Checkmarx One API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_pages(
    session: requests.Session,
    auth: CheckmarxAuth,
    url: str,
    params: dict[str, Any],
    data_key: str,
    page_size: int,
    logger: FilteringBoundLogger,
    start_offset: int = 0,
) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
    """Walk an offset/limit paginated endpoint, yielding (rows, next_offset) per page.

    next_offset is None on the terminal page. Termination is by short page: Checkmarx One list
    responses wrap rows under `data_key` alongside totalCount/filteredTotalCount, and a page with
    fewer than `limit` rows is the last one.
    """
    offset = start_offset
    while True:
        data = _fetch_json(session, auth, url, {**params, "offset": offset, "limit": page_size}, logger)
        items = data.get(data_key) or []
        if not items:
            break

        next_offset: int | None = offset + len(items) if len(items) >= page_size else None
        yield items, next_offset

        if next_offset is None:
            break
        offset = next_offset


def _build_incremental_value(
    config: CheckmarxEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str | None:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return None

    value = db_incremental_field_last_value
    if config.incremental_lookback is not None:
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
        if isinstance(value, datetime):
            value = value - config.incremental_lookback

    return _format_datetime(value)


def _result_id(item: dict[str, Any]) -> str:
    """A per-scan-unique identifier for a finding.

    The unified results API documents an `id` per result; `similarityId` is the fallback for
    engines that omit it, and a content hash guards against rows with neither (unverified against
    a live tenant, hence the defensive chain). Prefixed with the engine type since ids are only
    documented unique within their engine.
    """
    raw = item.get("id") or item.get("similarityId")
    if raw is None:
        raw = hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()
    return f"{item.get('type', 'unknown')}:{raw}"


def _shape_fan_out_row(item: dict[str, Any], scan_id: str, scan_created_at: Any, endpoint: str) -> dict[str, Any]:
    row = dict(item)
    if endpoint == "scan_results":
        row["result_id"] = _result_id(item)
    row["scan_id"] = scan_id
    row["scan_created_at"] = scan_created_at
    return row


def _enumerate_scans(
    session: requests.Session,
    auth: CheckmarxAuth,
    api_base_url: str,
    from_date: str | None,
    page_size: int,
    logger: FilteringBoundLogger,
) -> list[tuple[str, Any]]:
    params: dict[str, Any] = {}
    if from_date:
        params["from-date"] = from_date

    scans: list[tuple[str, Any]] = []
    for items, _next_offset in _iter_pages(
        session, auth, f"{api_base_url}/api/scans", params, "scans", page_size, logger
    ):
        scans.extend((item["id"], item.get("createdAt")) for item in items)
    return scans


def _get_fan_out_rows(
    session: requests.Session,
    auth: CheckmarxAuth,
    api_base_url: str,
    endpoint: str,
    config: CheckmarxEndpointConfig,
    resumable_source_manager: ResumableSourceManager[CheckmarxResumeConfig],
    from_date: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Fetch `config.path` once per scan, stamping each row with the parent scan's id and creation time.

    Each request targets a single scan id — the summary endpoint accepts multiple ids per call, but
    the batching syntax isn't verifiable without a live tenant, so one-id-per-request keeps the
    behavior unambiguous at the cost of extra calls.
    """
    scans = _enumerate_scans(session, auth, api_base_url, from_date, config.page_size, logger)

    # Resolve the saved scan-id bookmark to the slice of scans still to process. If the bookmarked
    # scan no longer exists (deleted between runs), start over — merge dedupes on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = scans
    resume_offset = 0
    if resume is not None and resume.scan_id is not None:
        scan_ids = [scan_id for scan_id, _created_at in scans]
        if resume.scan_id in scan_ids:
            remaining = scans[scan_ids.index(resume.scan_id) :]
            resume_offset = resume.offset
            logger.debug(f"Checkmarx: resuming {endpoint} from scan_id={resume.scan_id}, offset={resume_offset}")

    assert config.scan_id_param is not None
    url = f"{api_base_url}{config.path}"

    for index, (scan_id, scan_created_at) in enumerate(remaining):
        start_offset = resume_offset
        resume_offset = 0  # only the resumed-into scan starts mid-way; the rest start fresh

        for items, next_offset in _iter_pages(
            session,
            auth,
            url,
            {config.scan_id_param: scan_id},
            config.data_key,
            config.page_size,
            logger,
            start_offset=start_offset,
        ):
            yield [_shape_fan_out_row(item, scan_id, scan_created_at, endpoint) for item in items]
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
            # page rather than skipping it — merge dedupes on the primary key.
            if next_offset is not None:
                resumable_source_manager.save_state(CheckmarxResumeConfig(offset=next_offset, scan_id=scan_id))

        # Advance the bookmark to the next scan so a crash between scans resumes correctly.
        if index + 1 < len(remaining):
            next_scan_id = remaining[index + 1][0]
            resumable_source_manager.save_state(CheckmarxResumeConfig(offset=0, scan_id=next_scan_id))


def get_rows(
    tenant_name: str,
    region: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CheckmarxResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CHECKMARX_ENDPOINTS[endpoint]
    api_base_url, iam_base_url = get_region_hosts(region)
    # One session reused across every page (and, for fan-out, every scan) so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = _make_session(api_key)
    auth = CheckmarxAuth(session, iam_base_url, tenant_name, api_key)

    from_date = _build_incremental_value(config, should_use_incremental_field, db_incremental_field_last_value)

    if config.fan_out_over_scans:
        yield from _get_fan_out_rows(
            session, auth, api_base_url, endpoint, config, resumable_source_manager, from_date, logger
        )
        return

    params: dict[str, Any] = {}
    if from_date:
        params["from-date"] = from_date

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_offset = resume.offset if resume is not None else 0
    if start_offset:
        logger.debug(f"Checkmarx: resuming {endpoint} from offset={start_offset}")

    for items, next_offset in _iter_pages(
        session,
        auth,
        f"{api_base_url}{config.path}",
        params,
        config.data_key,
        config.page_size,
        logger,
        start_offset=start_offset,
    ):
        yield items
        if next_offset is not None:
            resumable_source_manager.save_state(CheckmarxResumeConfig(offset=next_offset))


def validate_credentials(tenant_name: str, region: str, api_key: str) -> tuple[bool, str | None]:
    try:
        api_base_url, iam_base_url = get_region_hosts(region)
    except ValueError as e:
        return False, str(e)

    session = _make_session(api_key)
    auth = CheckmarxAuth(session, iam_base_url, tenant_name, api_key)

    try:
        token = auth.get_token()
        response = session.get(
            f"{api_base_url}/api/projects",
            params={"offset": 0, "limit": 1},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json; version=1.0"},
            timeout=TOKEN_REQUEST_TIMEOUT,
        )
        if response.ok:
            return True, None
        return False, f"Checkmarx One API returned status {response.status_code} when listing projects"
    except CheckmarxAuthError as e:
        return False, str(e)
    except Exception:
        return False, "Could not connect to Checkmarx One. Check your tenant name, region, and API key."


def checkmarx_source(
    tenant_name: str,
    region: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CheckmarxResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CHECKMARX_ENDPOINTS[endpoint]
    has_incremental = len(config.incremental_fields) > 0

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            tenant_name=tenant_name,
            region=region,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # The scans list returns newest-first by default and the fan-outs follow its order, so the
        # incremental watermark is finalized at successful job end rather than checkpointed per batch.
        sort_mode="desc" if has_incremental else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
