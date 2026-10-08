import json
import time
import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.settings import (
    CHECKMARX_ENDPOINTS,
    CHECKMARX_REGION_HOSTS,
    CheckmarxEndpointConfig,
    CheckmarxFanOutConfig,
    RegionHosts,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

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


@frozen
class CheckmarxResumeConfig:
    # Row offset to resume the current page loop from.
    offset: int = 0
    # For fan-out endpoints: the parent row currently being processed. A stable id bookmark (not a
    # positional index) so parents created between a crash and the retry can't shift the resume point.
    parent_id: str | None = None


def _make_session(api_key: str) -> requests.Session:
    """Tracked session hardened for this source's traffic.

    Sample capture is disabled: responses carry customer vulnerability findings, repository URLs,
    and attack-vector details that the name-based scrubbers can't sanitise, so they must never
    reach the HTTP sample bucket. The API key is registered for value-based redaction, and
    redirects are refused so the token POST body (which carries the key) can never be re-sent to
    a redirect target — no Checkmarx One endpoint we call legitimately redirects.
    """
    return make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False)


def get_region_hosts(region: str) -> RegionHosts:
    """Return the API and IAM base URLs for a Checkmarx One region."""
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
) -> Any:
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


def _extract_rows(data: Any, config: CheckmarxEndpointConfig) -> list[dict[str, Any]]:
    """Rows out of a response body, which is either a bare JSON array or wrapped under `data_key`."""
    if config.data_key is None:
        items = data if isinstance(data, list) else []
    else:
        items = data.get(config.data_key) or []

    if config.scalar_row_field is not None:
        return [{config.scalar_row_field: item} for item in items]
    return items


def _iter_pages(
    session: requests.Session,
    auth: CheckmarxAuth,
    url: str,
    params: dict[str, Any],
    config: CheckmarxEndpointConfig,
    logger: FilteringBoundLogger,
    start_offset: int = 0,
) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
    """Walk an endpoint's rows, yielding (rows, next_offset) per page.

    next_offset is None on the terminal page. Termination is by short page: Checkmarx One list
    responses wrap rows under `data_key` alongside totalCount/filteredTotalCount, and a page with
    fewer than `limit` rows is the last one. The lookup endpoints return their whole collection in
    one unpaginated response, so they are fetched without offset/limit.
    """
    if not config.paginated:
        rows = _extract_rows(_fetch_json(session, auth, url, params, logger), config)
        if rows:
            yield rows, None
        return

    offset = start_offset
    while True:
        data = _fetch_json(session, auth, url, {**params, "offset": offset, "limit": config.page_size}, logger)
        items = _extract_rows(data, config)
        if not items:
            break

        next_offset: int | None = offset + len(items) if len(items) >= config.page_size else None
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


def _change_id(item: dict[str, Any]) -> str:
    """A stable identifier for a predicate change, which the changelog returns without one.

    Hashed from the whole row so every sync merges onto the same key instead of appending a
    duplicate. Two changes identical in action, timestamp, user and origin collapse into one row.
    """
    return hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()


def _shape_fan_out_row(
    item: dict[str, Any],
    parent_id: str,
    parent_created_at: Any,
    endpoint: str,
    fan_out: CheckmarxFanOutConfig,
) -> dict[str, Any]:
    row = dict(item)
    if endpoint == "scan_results":
        row["result_id"] = _result_id(item)
    elif endpoint == "sast_predicates_changelog":
        row["change_id"] = _change_id(item)
    row[fan_out.parent_id_field] = parent_id
    row[fan_out.parent_created_at_field] = parent_created_at
    return row


def _enumerate_parents(
    session: requests.Session,
    auth: CheckmarxAuth,
    api_base_url: str,
    parent_config: CheckmarxEndpointConfig,
    from_date: str | None,
    logger: FilteringBoundLogger,
) -> list[tuple[str, Any]]:
    params: dict[str, Any] = dict(parent_config.params)
    if from_date and parent_config.from_date_param:
        params[parent_config.from_date_param] = from_date

    parents: list[tuple[str, Any]] = []
    for items, _next_offset in _iter_pages(
        session, auth, f"{api_base_url}{parent_config.path}", params, parent_config, logger
    ):
        parents.extend((item["id"], item.get("createdAt")) for item in items)
    return parents


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
    """Fetch `config.path` once per parent row, stamping each row with the parent's id and creation time.

    Each request targets a single parent id — the scan summary endpoint accepts multiple ids per
    call, but the batching syntax isn't verifiable without a live tenant, so one-id-per-request
    keeps the behavior unambiguous at the cost of extra calls.
    """
    fan_out = config.fan_out
    assert fan_out is not None
    parents = _enumerate_parents(session, auth, api_base_url, CHECKMARX_ENDPOINTS[fan_out.parent], from_date, logger)

    # Resolve the saved parent-id bookmark to the slice of parents still to process. If the
    # bookmarked parent no longer exists (deleted between runs), start over — merge dedupes on the
    # primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = parents
    resume_offset = 0
    if resume is not None and resume.parent_id is not None:
        parent_ids = [parent_id for parent_id, _created_at in parents]
        if resume.parent_id in parent_ids:
            remaining = parents[parent_ids.index(resume.parent_id) :]
            resume_offset = resume.offset
            logger.debug(f"Checkmarx: resuming {endpoint} from parent_id={resume.parent_id}, offset={resume_offset}")

    for index, (parent_id, parent_created_at) in enumerate(remaining):
        start_offset = resume_offset
        resume_offset = 0  # only the resumed-into parent starts mid-way; the rest start fresh

        url = f"{api_base_url}{config.path}".replace("{parent_id}", quote(parent_id, safe=""))
        params: dict[str, Any] = dict(config.params)
        if fan_out.id_param is not None:
            params[fan_out.id_param] = parent_id

        for items, next_offset in _iter_pages(
            session,
            auth,
            url,
            params,
            config,
            logger,
            start_offset=start_offset,
        ):
            yield [_shape_fan_out_row(item, parent_id, parent_created_at, endpoint, fan_out) for item in items]
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
            # page rather than skipping it — merge dedupes on the primary key.
            if next_offset is not None:
                resumable_source_manager.save_state(CheckmarxResumeConfig(offset=next_offset, parent_id=parent_id))

        # Advance the bookmark to the next parent so a crash between parents resumes correctly.
        if index + 1 < len(remaining):
            next_parent_id = remaining[index + 1][0]
            resumable_source_manager.save_state(CheckmarxResumeConfig(offset=0, parent_id=next_parent_id))


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
    hosts = get_region_hosts(region)
    # One session reused across every page (and, for fan-out, every scan) so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = _make_session(api_key)
    auth = CheckmarxAuth(session, hosts.iam_base_url, tenant_name, api_key)

    from_date = _build_incremental_value(config, should_use_incremental_field, db_incremental_field_last_value)

    if config.fan_out is not None:
        yield from _get_fan_out_rows(
            session, auth, hosts.api_base_url, endpoint, config, resumable_source_manager, from_date, logger
        )
        return

    params: dict[str, Any] = dict(config.params)
    if from_date and config.from_date_param:
        params[config.from_date_param] = from_date

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_offset = resume.offset if resume is not None else 0
    if start_offset:
        logger.debug(f"Checkmarx: resuming {endpoint} from offset={start_offset}")

    for items, next_offset in _iter_pages(
        session,
        auth,
        f"{hosts.api_base_url}{config.path}",
        params,
        config,
        logger,
        start_offset=start_offset,
    ):
        yield items
        if next_offset is not None:
            resumable_source_manager.save_state(CheckmarxResumeConfig(offset=next_offset))


def validate_credentials(tenant_name: str, region: str, api_key: str) -> tuple[bool, str | None]:
    try:
        hosts = get_region_hosts(region)
    except ValueError as e:
        return False, str(e)

    session = _make_session(api_key)
    auth = CheckmarxAuth(session, hosts.iam_base_url, tenant_name, api_key)

    try:
        token = auth.get_token()
        response = session.get(
            f"{hosts.api_base_url}/api/projects",
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
