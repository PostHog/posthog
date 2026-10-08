import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.queries import (
    DISCOVERY_VALIDATION_QUERY,
    MODEL_UNIQUE_IDS_QUERY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.settings import (
    DBT_DISCOVERY_PAGE_SIZE,
    DBT_DISCOVERY_REGION_URLS,
    DBT_ENDPOINTS,
    DBT_MODEL_HISTORICAL_RUN_COUNT,
    DBT_PAGE_LIMIT,
    DBT_REGION_BASE_URLS,
    DbtEndpointConfig,
    DbtRunFanoutConfig,
)

HOST_NOT_ALLOWED_ERROR = "The dbt base URL is not allowed"

# Prefix of the error raised when the Discovery API refuses the token. The GraphQL service answers
# an auth failure with HTTP 200 and an `errors` body, so there is no status text to match on.
DISCOVERY_TOKEN_ERROR = "dbt Discovery API rejected the token"


class DbtRetryableError(Exception):
    pass


class DbtHostNotAllowedError(Exception):
    pass


@frozen
class DbtResumeConfig:
    # Row offset of the next page to fetch. Resuming mid-list is safe against rows landing between
    # attempts: runs are walked newest-first, so inserts shift already-read rows deeper and a resume
    # at the saved offset re-reads them (merge dedupes on the primary key) rather than skipping.
    offset: int = 0
    # Fan-out progress: the offset into the runs list, or the index into the environment list,
    # whose children were being expanded.
    parent_offset: int = 0
    # Discovery API page cursor within the parent being expanded.
    cursor: Optional[str] = None


def get_base_url(region: str, custom_base_url: str | None) -> str:
    """Resolve the API base URL from the region select, or a custom cell-based/single-tenant URL."""
    if custom_base_url and custom_base_url.strip():
        url = custom_base_url.strip().rstrip("/")
        if not url.startswith("https://"):
            raise DbtHostNotAllowedError("Custom dbt base URL must start with https://")
        return url
    return DBT_REGION_BASE_URLS.get(region, DBT_REGION_BASE_URLS["us"])


def get_discovery_url(region: str, discovery_api_url: str | None) -> str:
    """Resolve the Discovery API (GraphQL) URL from the region select, or a user-supplied URL.

    Cell-based and single-tenant deployments prefix the account onto the metadata hostname
    (``https://ab123.metadata.us1.dbt.com/graphql``), which can't be derived from the Admin API
    base URL, so those users enter it themselves.
    """
    if discovery_api_url and discovery_api_url.strip():
        url = discovery_api_url.strip().rstrip("/")
        if not url.startswith("https://"):
            raise DbtHostNotAllowedError("Custom dbt Discovery API URL must start with https://")
        return url
    return DBT_DISCOVERY_REGION_URLS.get(region, DBT_DISCOVERY_REGION_URLS["us"])


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
    discovery_api_url: str | None = None,
) -> tuple[bool, str | None]:
    """Probe the account endpoint to confirm the token is genuine and can reach the account.

    At source-create (``schema_name is None``) a 403 is accepted: the token authenticated but may
    lack the permission set for this particular probe. A scoped probe treats 403 as a failure.
    """
    try:
        base_url = get_base_url(region, custom_base_url)
        discovery_url = get_discovery_url(region, discovery_api_url)
    except DbtHostNotAllowedError as e:
        return False, str(e)

    if team_id is not None:
        host_ok, host_err = _check_host_safety(base_url, custom_base_url, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR
        discovery_ok, discovery_err = _check_host_safety(discovery_url, discovery_api_url, team_id)
        if not discovery_ok:
            return False, discovery_err or HOST_NOT_ALLOWED_ERROR

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


def _raise_for_graphql_errors(payload: dict[str, Any]) -> None:
    """Classify a Discovery API response body, which reports failures with HTTP 200 + `errors`."""
    errors = payload.get("errors")
    if not errors:
        if "data" not in payload:
            raise Exception(f"Unexpected dbt Discovery API response. Keys: {sorted(payload.keys())}")
        return

    messages = "; ".join(str(error.get("message", "")) for error in errors)
    lowered = messages.lower()
    if "rate limit" in lowered or "too many requests" in lowered:
        raise DbtRetryableError(f"dbt Discovery API rate limited: {messages}")
    if any(word in lowered for word in ("token", "unauthorized", "forbidden", "permission")):
        raise Exception(f"{DISCOVERY_TOKEN_ERROR}: {messages}")
    raise Exception(f"dbt Discovery API error: {messages}")


@retry(
    retry=retry_if_exception_type(DbtRetryableError),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _post_graphql(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    try:
        response = session.post(
            url,
            headers=headers,
            json={"query": query, "variables": variables},
            timeout=60,
            allow_redirects=False,
        )
    except (requests.ConnectionError, requests.Timeout) as e:
        # The session's transport-level retries only cover idempotent methods, so these POSTs get
        # none. Fold transient network failures into this backoff instead.
        raise DbtRetryableError(f"dbt Discovery API: transient network error - {e}")

    if response.is_redirect or response.is_permanent_redirect:
        raise DbtHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)

    if response.status_code == 429 or response.status_code >= 500:
        raise DbtRetryableError(f"dbt Discovery API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"dbt Discovery API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    payload = response.json()
    _raise_for_graphql_errors(payload)
    return payload.get("data") or {}


def _probe_discovery_access(
    session: requests.Session,
    headers: dict[str, str],
    region: str,
    discovery_api_url: str | None,
    team_id: int,
    endpoints: list[str],
) -> str | None:
    """Check once whether the token reaches the Discovery API, for the schema picker.

    Admin API tokens are not automatically accepted by the metadata service, so this catches the
    common case of a token that can list jobs and runs but cannot read project state.
    """
    configs = [DBT_ENDPOINTS[endpoint] for endpoint in endpoints if endpoint in DBT_ENDPOINTS]
    if not any(config.discovery is not None for config in configs):
        return None

    try:
        discovery_url = get_discovery_url(region, discovery_api_url)
    except DbtHostNotAllowedError as e:
        return str(e)

    host_ok, host_err = _check_host_safety(discovery_url, discovery_api_url, team_id)
    if not host_ok:
        return host_err or HOST_NOT_ALLOWED_ERROR

    try:
        response = session.post(
            discovery_url,
            headers=headers,
            json={"query": DISCOVERY_VALIDATION_QUERY},
            timeout=10,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException:
        # A blip is not a denial.
        return None

    if response.status_code in (401, 403):
        return "Your dbt API token cannot read the Discovery API"
    if not response.ok:
        return None

    try:
        payload = response.json()
    except Exception:
        return None

    errors = payload.get("errors") or []
    if errors:
        return errors[0].get("message") or "Your dbt API token cannot read the Discovery API"
    return None


def get_endpoint_permissions(
    api_token: str,
    account_id: str,
    region: str,
    custom_base_url: str | None,
    team_id: int,
    endpoints: list[str],
    discovery_api_url: str | None = None,
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
    discovery_error = _probe_discovery_access(session, headers, region, discovery_api_url, team_id, endpoints)
    for endpoint in endpoints:
        config = DBT_ENDPOINTS.get(endpoint)
        if config is None:
            results[endpoint] = None
            continue
        if config.discovery is not None:
            results[endpoint] = discovery_error
            continue
        # A run fan-out reads the runs list plus a per-run route; the list is the permission that
        # decides whether the table can sync at all.
        probe_path = config.path if config.path is not None else DBT_ENDPOINTS["runs"].path
        assert probe_path is not None
        url = f"{base_url}/api{probe_path.format(account_id=account_id)}?limit=1"
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


@frozen
class _ListPage:
    rows: list[dict[str, Any]]
    next_offset: int
    has_more: bool


def _iter_offset_pages(
    session: requests.Session,
    base_url: str,
    path: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    start_offset: int = 0,
) -> Iterator[_ListPage]:
    """Walk a dbt limit/offset list endpoint."""
    offset = start_offset
    while True:
        url = f"{base_url}/api{path}?{urlencode({**params, 'offset': offset})}"
        data = _fetch_page(session, url, headers, logger)

        rows = data.get("data") or []
        if not rows:
            return

        pagination = (data.get("extra") or {}).get("pagination") or {}
        count = pagination.get("count", len(rows))
        total_count = pagination.get("total_count")
        next_offset = offset + count
        has_more = count >= DBT_PAGE_LIMIT and not (total_count is not None and next_offset >= total_count)

        yield _ListPage(rows=rows, next_offset=next_offset, has_more=has_more)

        if not has_more:
            return
        offset = next_offset


def _rows_above_watermark(rows: list[dict[str, Any]], cursor_field: str, watermark: datetime) -> list[dict[str, Any]]:
    """Keep the rows newer than the watermark. Rows with no parseable cursor value are kept."""
    return [
        row for row in rows if (row_value := _coerce_datetime(row.get(cursor_field))) is None or row_value > watermark
    ]


def _fetch_run_children(
    session: requests.Session,
    base_url: str,
    account_id: str,
    fanout: DbtRunFanoutConfig,
    run: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    run_id = run.get("id")
    if run_id is None:
        return []

    url = f"{base_url}/api{fanout.path.format(account_id=account_id, run_id=run_id)}"
    if fanout.include_related:
        # dbt expects a JSON array literal here, not repeated query params.
        url = f"{url}?{urlencode({'include_related': json.dumps(list(fanout.include_related))})}"

    try:
        data = _fetch_page(session, url, headers, logger)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            # Runs age out and cancelled runs never produce artifacts; skip rather than fail the sync.
            return []
        raise

    payload = data.get("data")
    if fanout.data_selector is not None:
        children = (payload or {}).get(fanout.data_selector) or []
    else:
        children = payload or []

    # run_created_at carries the parent's immutable creation time so the child table has a cursor
    # and a partition key of its own.
    parent_fields = {"run_id": run_id, "run_created_at": run.get("created_at")}
    if fanout.string_row_field is not None:
        return [{**parent_fields, fanout.string_row_field: child} for child in children]
    return [{**child, **parent_fields} for child in children]


def _iter_run_fanout_rows(
    session: requests.Session,
    base_url: str,
    account_id: str,
    config: DbtEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DbtResumeConfig],
    resume: DbtResumeConfig | None,
    watermark: datetime | None,
) -> Iterator[Any]:
    """Expand a child resource of every run in the incremental window.

    The runs list is walked newest-first and stopped at the watermark, so an incremental sync only
    fans out over runs it has not expanded before.
    """
    fanout = config.run_fanout
    assert fanout is not None
    runs_path = DBT_ENDPOINTS["runs"].path
    assert runs_path is not None

    params = {"limit": DBT_PAGE_LIMIT, "order_by": "-created_at"}
    for page in _iter_offset_pages(
        session,
        base_url,
        runs_path.format(account_id=account_id),
        params,
        headers,
        logger,
        start_offset=resume.parent_offset if resume is not None else 0,
    ):
        runs = page.rows
        kept_runs = runs if watermark is None else _rows_above_watermark(runs, "created_at", watermark)

        batch: list[dict[str, Any]] = []
        for run in kept_runs:
            batch.extend(_fetch_run_children(session, base_url, account_id, fanout, run, headers, logger))
        if batch:
            yield batch

        if len(kept_runs) < len(runs):
            break
        if page.has_more:
            resumable_source_manager.save_state(DbtResumeConfig(parent_offset=page.next_offset))


def _deployment_environment_ids(
    session: requests.Session,
    base_url: str,
    account_id: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[int]:
    """List the environments the Discovery API can report applied state for.

    Development environments have no applied state, so querying them would spend a request per
    environment to get nothing back.
    """
    path = DBT_ENDPOINTS["environments"].path
    assert path is not None

    environment_ids: list[int] = []
    for page in _iter_offset_pages(
        session, base_url, path.format(account_id=account_id), {"limit": DBT_PAGE_LIMIT}, headers, logger
    ):
        environment_ids.extend(
            row["id"] for row in page.rows if row.get("id") is not None and row.get("type") == "deployment"
        )
    return environment_ids


def _next_page_cursor(page_info: dict[str, Any], cursor: str | None, context: str) -> str | None:
    """Resolve the cursor of the next page, or None at the end of the connection.

    A connection that claims another page but hands back no cursor, or the same one again, would
    make the caller re-request the page it just read until the activity times out. Fail instead:
    silently ending the walk would write a partial table that reads as complete.
    """
    if not page_info.get("hasNextPage"):
        return None
    next_cursor = page_info.get("endCursor")
    if not next_cursor or next_cursor == cursor:
        raise Exception(f"dbt Discovery API reported another page without advancing the cursor. {context}")
    return next_cursor


def _iter_discovery_pages(
    session: requests.Session,
    discovery_url: str,
    headers: dict[str, str],
    config: DbtEndpointConfig,
    environment_id: int,
    start_cursor: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Walk one environment's applied-state connection, yielding (rows, cursor of the next page)."""
    discovery = config.discovery
    assert discovery is not None

    cursor = start_cursor
    while True:
        data = _post_graphql(
            session,
            discovery_url,
            headers,
            discovery.query,
            {"environmentId": environment_id, "first": DBT_DISCOVERY_PAGE_SIZE, "after": cursor},
            logger,
        )
        applied = ((data.get("environment") or {}).get("applied")) or {}
        connection = applied.get(discovery.applied_field) or {}
        rows = [edge["node"] for edge in (connection.get("edges") or []) if edge.get("node")]

        page_info = connection.get("pageInfo") or {}
        next_cursor = _next_page_cursor(
            page_info, cursor, f"field={discovery.applied_field}, environment={environment_id}"
        )

        yield rows, next_cursor

        if next_cursor is None:
            return
        cursor = next_cursor


def _iter_model_historical_run_pages(
    session: requests.Session,
    discovery_url: str,
    headers: dict[str, str],
    config: DbtEndpointConfig,
    environment_id: int,
    start_cursor: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Walk the environment's models, asking each one for its run history.

    modelHistoricalRuns takes a single model at a time, so the page cursor tracks the model list
    and each page costs one request per model in it.
    """
    discovery = config.discovery
    assert discovery is not None

    cursor = start_cursor
    while True:
        data = _post_graphql(
            session,
            discovery_url,
            headers,
            MODEL_UNIQUE_IDS_QUERY,
            {"environmentId": environment_id, "first": DBT_DISCOVERY_PAGE_SIZE, "after": cursor},
            logger,
        )
        applied = ((data.get("environment") or {}).get("applied")) or {}
        connection = applied.get("models") or {}
        unique_ids = [
            unique_id
            for edge in (connection.get("edges") or [])
            if (unique_id := (edge.get("node") or {}).get("uniqueId"))
        ]

        rows: list[dict[str, Any]] = []
        for unique_id in unique_ids:
            run_data = _post_graphql(
                session,
                discovery_url,
                headers,
                discovery.query,
                {
                    "environmentId": environment_id,
                    "uniqueId": unique_id,
                    "lastRunCount": DBT_MODEL_HISTORICAL_RUN_COUNT,
                },
                logger,
            )
            run_applied = ((run_data.get("environment") or {}).get("applied")) or {}
            rows.extend(run_applied.get(discovery.applied_field) or [])

        page_info = connection.get("pageInfo") or {}
        next_cursor = _next_page_cursor(page_info, cursor, f"field=models, environment={environment_id}")

        yield rows, next_cursor

        if next_cursor is None:
            return
        cursor = next_cursor


def _iter_discovery_rows(
    session: requests.Session,
    base_url: str,
    discovery_url: str,
    account_id: str,
    config: DbtEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DbtResumeConfig],
    resume: DbtResumeConfig | None,
) -> Iterator[Any]:
    discovery = config.discovery
    assert discovery is not None

    environment_ids = _deployment_environment_ids(session, base_url, account_id, headers, logger)
    start_index = resume.parent_offset if resume is not None else 0
    walk = _iter_model_historical_run_pages if discovery.per_model else _iter_discovery_pages

    for index in range(start_index, len(environment_ids)):
        environment_id = environment_ids[index]
        start_cursor = resume.cursor if resume is not None and index == start_index else None

        for rows, next_cursor in walk(session, discovery_url, headers, config, environment_id, start_cursor, logger):
            if rows:
                # environmentId is part of the primary key, so it is stamped from the environment
                # being queried rather than trusted to be resolved on every node type.
                yield [{**row, "environmentId": environment_id} for row in rows]
            if next_cursor is not None:
                resumable_source_manager.save_state(DbtResumeConfig(parent_offset=index, cursor=next_cursor))
        if index + 1 < len(environment_ids):
            resumable_source_manager.save_state(DbtResumeConfig(parent_offset=index + 1))


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
    discovery_api_url: str | None = None,
) -> Iterator[Any]:
    config = DBT_ENDPOINTS[endpoint]
    base_url = get_base_url(region, custom_base_url)
    discovery_url = get_discovery_url(region, discovery_api_url) if config.discovery else None

    # Re-check at run time (not just at source-create) in case the URL was edited or now resolves
    # to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _check_host_safety(base_url, custom_base_url, team_id)
    if not host_ok:
        raise DbtHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
    if discovery_url is not None:
        discovery_ok, discovery_err = _check_host_safety(discovery_url, discovery_api_url, team_id)
        if not discovery_ok:
            raise DbtHostNotAllowedError(discovery_err or HOST_NOT_ALLOWED_ERROR)

    session = make_tracked_session()
    headers = _get_headers(api_token)
    cursor_field = incremental_field or config.default_incremental_field

    watermark: datetime | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        watermark = _coerce_datetime(db_incremental_field_last_value)
        if watermark is not None and config.incremental_lookback is not None:
            watermark -= config.incremental_lookback

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        logger.debug(f"dbt: resuming {endpoint} from {resume}")

    if discovery_url is not None:
        yield from _iter_discovery_rows(
            session,
            base_url,
            discovery_url,
            account_id,
            config,
            headers,
            logger,
            resumable_source_manager,
            resume,
        )
        return

    if config.run_fanout is not None:
        yield from _iter_run_fanout_rows(
            session,
            base_url,
            account_id,
            config,
            headers,
            logger,
            resumable_source_manager,
            resume,
            watermark,
        )
        return

    path = config.path
    assert path is not None
    walking_desc = config.sort_mode == "desc" and cursor_field is not None
    params = _build_params(config, incremental_field, walking_desc)

    for page in _iter_offset_pages(
        session,
        base_url,
        path.format(account_id=account_id),
        params,
        headers,
        logger,
        start_offset=resume.offset if resume is not None else 0,
    ):
        if watermark is not None and cursor_field is not None:
            # Newest-first walk: keep rows above the watermark and stop as soon as the page dips
            # below it — everything past that point was synced by a previous run.
            kept = _rows_above_watermark(page.rows, cursor_field, watermark)
            if kept:
                yield kept
            if len(kept) < len(page.rows):
                break
        else:
            yield page.rows

        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last page
        # rather than skipping it — merge dedupes on the primary key.
        if page.has_more:
            resumable_source_manager.save_state(DbtResumeConfig(offset=page.next_offset))


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
    discovery_api_url: str | None = None,
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
            discovery_api_url=discovery_api_url,
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
