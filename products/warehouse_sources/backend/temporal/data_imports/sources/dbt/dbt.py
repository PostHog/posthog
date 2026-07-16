import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.settings import (
    DBT_ENDPOINTS,
    DBT_PAGE_LIMIT,
    DBT_REGION_BASE_URLS,
    DbtEndpointConfig,
)

HOST_NOT_ALLOWED_ERROR = "The dbt base URL is not allowed"


class DbtRetryableError(Exception):
    pass


class DbtHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class DbtResumeConfig:
    # Row offset of the next page to fetch. Resuming mid-list is safe against rows landing between
    # attempts: runs are walked newest-first, so inserts shift already-read rows deeper and a resume
    # at the saved offset re-reads them (merge dedupes on the primary key) rather than skipping.
    offset: int = 0


def get_base_url(region: str, custom_base_url: str | None) -> str:
    """Resolve the API base URL from the region select, or a custom cell-based/single-tenant URL."""
    if custom_base_url and custom_base_url.strip():
        url = custom_base_url.strip().rstrip("/")
        if not url.startswith("https://"):
            raise DbtHostNotAllowedError("Custom dbt base URL must start with https://")
        return url
    return DBT_REGION_BASE_URLS.get(region, DBT_REGION_BASE_URLS["us"])


def _check_host_safety(base_url: str, custom_base_url: str | None, team_id: int) -> tuple[bool, str | None]:
    """Block custom base URLs that resolve to private/internal addresses (SSRF).

    The regional hosts are fixed dbt Labs domains, so only a user-supplied custom URL needs the
    check. Only enforced on cloud — see _is_host_safe.
    """
    if not (custom_base_url and custom_base_url.strip()):
        return True, None
    host = urlparse(base_url).hostname or ""
    if not host:
        return False, HOST_NOT_ALLOWED_ERROR
    return _is_host_safe(host, team_id)


def _get_headers(api_token: str) -> dict[str, str]:
    # dbt Cloud accepts both `Token` and `Bearer` schemes for service account tokens and PATs.
    return {
        "Authorization": f"Token {api_token}",
        "Accept": "application/json",
    }


def _status_message(response: requests.Response) -> str | None:
    """Pull the human-readable message out of the dbt envelope ({"status": {"user_message": ...}})."""
    try:
        body = response.json()
        return body.get("status", {}).get("user_message") or response.text
    except Exception:
        return response.text or None


def validate_credentials(
    api_token: str,
    account_id: str,
    region: str,
    custom_base_url: str | None,
    team_id: Optional[int] = None,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Probe the account endpoint to confirm the token is genuine and can reach the account.

    At source-create (``schema_name is None``) a 403 is accepted: the token authenticated but may
    lack the permission set for this particular probe. A scoped probe treats 403 as a failure.
    """
    try:
        base_url = get_base_url(region, custom_base_url)
    except DbtHostNotAllowedError as e:
        return False, str(e)

    if team_id is not None:
        host_ok, host_err = _check_host_safety(base_url, custom_base_url, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{base_url}/api/v2/accounts/{account_id}/"
    try:
        # Don't follow redirects: a custom host could 3xx to an internal address, defeating the
        # host check above (SSRF).
        response = make_tracked_session().get(url, headers=_get_headers(api_token), timeout=10, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid dbt API token"

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing permission for this probe — let source creation through.
            return True, None
        return False, "Your dbt API token lacks the required permissions for this endpoint"

    if response.status_code == 404:
        return False, f"dbt account {account_id} not found — check the account ID and region"

    return False, _status_message(response)


def get_endpoint_permissions(
    api_token: str,
    account_id: str,
    region: str,
    custom_base_url: str | None,
    team_id: int,
    endpoints: list[str],
) -> dict[str, str | None]:
    """Probe each endpoint with limit=1 so the schema picker can flag tables the token can't read.

    Only a real denial (401/403/404) counts as unreachable — throttles, 5xx, and network blips go
    through the retryable sync path instead, so they report the endpoint as reachable here.
    """
    try:
        base_url = get_base_url(region, custom_base_url)
    except DbtHostNotAllowedError as e:
        return dict.fromkeys(endpoints, str(e))

    # These probes are separate outbound requests from credential validation, so re-check the host
    # here too — otherwise a custom host could be re-pointed at an internal address after validation.
    host_ok, host_err = _check_host_safety(base_url, custom_base_url, team_id)
    if not host_ok:
        return dict.fromkeys(endpoints, host_err or HOST_NOT_ALLOWED_ERROR)

    session = make_tracked_session()
    headers = _get_headers(api_token)
    results: dict[str, str | None] = {}
    for endpoint in endpoints:
        config = DBT_ENDPOINTS.get(endpoint)
        if config is None:
            results[endpoint] = None
            continue
        url = f"{base_url}/api{config.path.format(account_id=account_id)}?limit=1"
        try:
            response = session.get(url, headers=headers, timeout=10, allow_redirects=False)
        except requests.exceptions.RequestException:
            results[endpoint] = None
            continue
        if response.status_code in (401, 403, 404):
            results[endpoint] = (
                _status_message(response) or "Your dbt API token lacks the permissions to read this table"
            )
        else:
            results[endpoint] = None
    return results


def _coerce_datetime(value: Any) -> datetime | None:
    """Normalize a watermark or row value to an aware UTC datetime for comparison."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


@retry(
    retry=retry_if_exception_type(
        (
            DbtRetryableError,
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
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60, allow_redirects=False)

    if response.is_redirect or response.is_permanent_redirect:
        raise DbtHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)

    if response.status_code == 429 or response.status_code >= 500:
        raise DbtRetryableError(f"dbt API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"dbt API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _build_params(config: DbtEndpointConfig, incremental_field: str | None, walking_desc: bool) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": DBT_PAGE_LIMIT}
    # runs is the only endpoint with a documented order_by; the other lists come back in stable
    # id order by default, which offset pagination is safe against.
    if walking_desc:
        params["order_by"] = f"-{incremental_field or config.default_incremental_field}"
    return params


def get_rows(
    api_token: str,
    account_id: str,
    region: str,
    custom_base_url: str | None,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DbtResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = DBT_ENDPOINTS[endpoint]
    base_url = get_base_url(region, custom_base_url)

    # Re-check at run time (not just at source-create) in case the URL was edited or now resolves
    # to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _check_host_safety(base_url, custom_base_url, team_id)
    if not host_ok:
        raise DbtHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    session = make_tracked_session()
    headers = _get_headers(api_token)
    path = config.path.format(account_id=account_id)
    cursor_field = incremental_field or config.default_incremental_field

    watermark: datetime | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        watermark = _coerce_datetime(db_incremental_field_last_value)
        if watermark is not None and config.incremental_lookback is not None:
            watermark -= config.incremental_lookback

    walking_desc = config.sort_mode == "desc" and cursor_field is not None
    params = _build_params(config, incremental_field, walking_desc)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0
    if resume is not None:
        logger.debug(f"dbt: resuming {endpoint} from offset={offset}")

    while True:
        url = f"{base_url}/api{path}?{urlencode({**params, 'offset': offset})}"
        data = _fetch_page(session, url, headers, logger)

        rows = data.get("data") or []
        if not rows:
            break

        if watermark is not None and cursor_field is not None:
            # Newest-first walk: keep rows above the watermark and stop as soon as the page dips
            # below it — everything past that point was synced by a previous run. Rows with a
            # missing/unparseable cursor value are kept to stay on the safe side.
            kept = [
                row
                for row in rows
                if (row_value := _coerce_datetime(row.get(cursor_field))) is None or row_value > watermark
            ]
            if kept:
                yield kept
            if len(kept) < len(rows):
                break
        else:
            yield rows

        pagination = (data.get("extra") or {}).get("pagination") or {}
        count = pagination.get("count", len(rows))
        total_count = pagination.get("total_count")
        offset += count

        if count < DBT_PAGE_LIMIT or (total_count is not None and offset >= total_count):
            break

        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last page
        # rather than skipping it — merge dedupes on the primary key.
        resumable_source_manager.save_state(DbtResumeConfig(offset=offset))


def dbt_source(
    api_token: str,
    account_id: str,
    region: str,
    custom_base_url: str | None,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DbtResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = DBT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            account_id=account_id,
            region=region,
            custom_base_url=custom_base_url,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Runs are walked newest-first (order_by=-created_at), so the incremental watermark only
        # persists at successful job end.
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
