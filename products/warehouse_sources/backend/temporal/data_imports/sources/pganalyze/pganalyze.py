from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen
from posthog.security.url_validation import is_url_allowed

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.queries import (
    ISSUE_DATABASE_IDS_QUERY,
    ISSUES_QUERY,
    QUERY_STATS_QUERY,
    SERVERS_QUERY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.settings import (
    PGANALYZE_API_URL,
    PGANALYZE_ENDPOINTS,
    PGANALYZE_MAX_RETRY_ATTEMPTS,
    PGANALYZE_REQUEST_TIMEOUT_SECONDS,
    QUERY_STATS_MAX_CATCHUP_DAYS,
    QUERY_STATS_SETTLE_HOURS,
)


class PgAnalyzeRetryableError(Exception):
    pass


def _resolve_api_url(api_url: str | None) -> str:
    """Resolve the optional user-supplied api_url to a validated URL.

    Why: api_url is a free-text input on the source config, so without validation any
    authenticated user could point pganalyze sync at internal-network targets (cloud
    metadata services, private IPs, RFC1918 hosts) and use PostHog as an SSRF gadget.
    """
    candidate = (api_url or "").strip() or PGANALYZE_API_URL
    allowed, reason = is_url_allowed(candidate)
    if not allowed:
        raise ValueError(f"pganalyze API URL is not allowed: {reason}")
    return candidate


def _build_session(api_key: str):
    return make_tracked_session(
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }
    )


def _post_graphql(
    session: Any,
    api_url: str,
    query: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
    @retry(
        retry=retry_if_exception_type((PgAnalyzeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(PGANALYZE_MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=30),
        reraise=True,
    )
    def _execute() -> dict[str, Any]:
        response = session.post(
            api_url,
            json={"query": query, "variables": variables},
            timeout=PGANALYZE_REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code >= 500:
            raise PgAnalyzeRetryableError(f"pganalyze: server error {response.status_code}")
        if response.status_code == 429:
            raise PgAnalyzeRetryableError("pganalyze: rate limited (429)")

        try:
            payload = response.json()
        except Exception:
            if not response.ok:
                raise Exception(
                    f"{response.status_code} Client Error: {response.reason} (pganalyze API: {response.text})"
                )
            raise Exception(f"Unexpected pganalyze response: {response.text}")

        if "errors" in payload:
            error_messages = "; ".join(e.get("message", "") for e in payload["errors"])
            if not response.ok:
                raise Exception(f"{response.status_code} Client Error: {response.reason} (pganalyze: {error_messages})")
            raise Exception(f"pganalyze GraphQL error: {error_messages}")

        if not response.ok:
            raise Exception(f"{response.status_code} Client Error: {response.reason} (pganalyze: {payload})")

        if "data" not in payload:
            raise Exception(f"Unexpected pganalyze response format. Keys: {list(payload.keys())}")

        return payload["data"]

    return _execute()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _fetch_servers(session: Any, api_url: str, organization_slug: str) -> list[dict[str, Any]]:
    data = _post_graphql(session, api_url, SERVERS_QUERY, {"organizationSlug": organization_slug})
    return data.get("getServers") or []


def _iter_servers(session: Any, api_url: str, organization_slug: str) -> Iterator[dict[str, Any]]:
    synced_at = _utc_now_iso()
    for server in _fetch_servers(session, api_url, organization_slug):
        yield {**server, "synced_at": synced_at}


def _iter_issues(
    session: Any,
    api_url: str,
    servers: list[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    logger.debug(f"pganalyze: fetched {len(servers)} servers for issues fan-out")

    for server in servers:
        server_human_id = server.get("humanId")
        if not server_human_id:
            continue

        synced_at = _utc_now_iso()
        issues_payload = _post_graphql(session, api_url, ISSUES_QUERY, {"serverId": server_human_id})
        for issue in issues_payload.get("getIssues") or []:
            yield {
                **issue,
                "serverHumanId": server_human_id,
                "serverName": server.get("name"),
                "synced_at": synced_at,
            }


@frozen
class QueryStatsWindow:
    start: datetime
    end: datetime


def _start_of_day(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _query_stats_windows(watermark: Any | None, now: datetime) -> list[QueryStatsWindow]:
    finished_until = _start_of_day(now - timedelta(hours=QUERY_STATS_SETTLE_HOURS))
    start = finished_until - timedelta(days=1)
    parsed_watermark = parse_datetime_value(watermark)
    if parsed_watermark is not None:
        start = _start_of_day(parsed_watermark) + timedelta(days=1)
    start = max(start, finished_until - timedelta(days=QUERY_STATS_MAX_CATCHUP_DAYS))

    windows: list[QueryStatsWindow] = []
    while start < finished_until:
        windows.append(QueryStatsWindow(start=start, end=start + timedelta(days=1)))
        start += timedelta(days=1)
    return windows


def _discover_databases(session: Any, api_url: str, servers: list[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    databases: dict[Any, dict[str, Any]] = {}
    for server in servers:
        server_human_id = server.get("humanId")
        if not server_human_id:
            continue

        payload = _post_graphql(session, api_url, ISSUE_DATABASE_IDS_QUERY, {"serverId": server_human_id})
        for issue in payload.get("getIssues") or []:
            database_id = issue.get("databaseId")
            if database_id is not None:
                databases.setdefault(database_id, server)
    return databases


def _iter_query_stats(
    session: Any,
    api_url: str,
    servers: list[dict[str, Any]],
    watermark: Any | None,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    databases = _discover_databases(session, api_url, servers)
    windows = _query_stats_windows(watermark, datetime.now(UTC))
    logger.debug(f"pganalyze: fetching query stats for {len(databases)} databases over {len(windows)} windows")

    for window in windows:
        for database_id, server in databases.items():
            payload = _post_graphql(
                session,
                api_url,
                QUERY_STATS_QUERY,
                {
                    "databaseId": str(database_id),
                    "startTs": int(window.start.timestamp()),
                    "endTs": int(window.end.timestamp()),
                },
            )
            for stat in payload.get("getQueryStats") or []:
                yield {
                    **stat,
                    "databaseId": database_id,
                    "serverHumanId": server.get("humanId"),
                    "serverName": server.get("name"),
                    "window_start": window.start.isoformat(),
                    "window_end": window.end.isoformat(),
                }


def pganalyze_source(
    api_key: str,
    api_url: str | None,
    organization_slug: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
) -> SourceResponse:
    endpoint_config = PGANALYZE_ENDPOINTS.get(endpoint_name)
    if endpoint_config is None:
        raise ValueError(f"Unknown pganalyze endpoint: {endpoint_name}")

    resolved_api_url = _resolve_api_url(api_url)

    def get_rows() -> Iterator[dict[str, Any]]:
        session = _build_session(api_key)
        try:
            if endpoint_name == "servers":
                yield from _iter_servers(session, resolved_api_url, organization_slug)
                return

            if endpoint_name == "issues":
                servers = _fetch_servers(session, resolved_api_url, organization_slug)
                yield from _iter_issues(session, resolved_api_url, servers, logger)
                return

            if endpoint_name == "query_stats":
                servers = _fetch_servers(session, resolved_api_url, organization_slug)
                yield from _iter_query_stats(
                    session, resolved_api_url, servers, db_incremental_field_last_value, logger
                )
                return

            raise ValueError(f"Unhandled pganalyze endpoint: {endpoint_name}")
        finally:
            session.close()

    return SourceResponse(
        items=get_rows,
        primary_keys=endpoint_config.primary_keys,
        name=endpoint_name,
        partition_count=endpoint_config.partition_count,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def validate_credentials(api_key: str, organization_slug: str, api_url: str | None) -> tuple[bool, str | None]:
    try:
        resolved_api_url = _resolve_api_url(api_url)
    except ValueError as e:
        return False, str(e)

    try:
        session = _build_session(api_key)
        try:
            response = session.post(
                resolved_api_url,
                json={
                    "query": SERVERS_QUERY,
                    "variables": {"organizationSlug": organization_slug},
                },
                timeout=10,
            )
        finally:
            session.close()

        if response.status_code in (401, 403):
            return False, "Invalid pganalyze API token. Please check your API key and organization slug."

        try:
            payload = response.json()
        except Exception:
            return False, f"Unexpected pganalyze response: {response.text[:200]}"

        if "errors" in payload:
            messages = "; ".join(e.get("message", "") for e in payload["errors"])
            return False, f"pganalyze API error: {messages}"

        if "data" in payload and "getServers" in payload["data"]:
            return True, None

        return False, "Could not verify pganalyze credentials"
    except Exception as e:
        return False, str(e)
