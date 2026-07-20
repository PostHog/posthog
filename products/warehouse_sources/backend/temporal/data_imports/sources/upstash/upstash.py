from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.settings import (
    UPSTASH_API_BASE_URL,
    UPSTASH_ENDPOINTS,
    UpstashEndpointConfig,
)

# Upstash does not document rate limits on the management API, but a 429 or a transient 5xx should
# still back off rather than fail the sync. Auth failures (401/403) are surfaced via raise_for_status
# and matched by get_non_retryable_errors() so the sync stops instead of retrying forever.
_MAX_ATTEMPTS = 5


class UpstashRetryableError(Exception):
    pass


def _auth(email: str, api_key: str) -> tuple[str, str]:
    """HTTP Basic auth: account email as username, management API key as password."""
    return (email, api_key)


@retry(
    retry=retry_if_exception_type((UpstashRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(_MAX_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, auth: tuple[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, auth=auth, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise UpstashRetryableError(f"Upstash API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Log only status and the (credential-free) URL. Response bodies can carry account data
        # (e.g. audit-log error payloads), which must not be copied into broadly-readable logs.
        logger.error(f"Upstash API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(email: str, api_key: str) -> tuple[bool, str | None]:
    """Confirm the email + management API key are genuine via GET /v2/teams.

    /v2/teams is the cheapest authenticated probe available to any native Upstash account regardless
    of which resources exist, and it needs no path parameters. Only a definitive 401/403 rejects the
    credentials; a 429, a 5xx, or an unreachable API is transient and must not block source creation,
    since the same statuses are retried during the sync itself and a genuine auth failure still
    surfaces at sync time via get_non_retryable_errors().
    """
    url = f"{UPSTASH_API_BASE_URL}/teams"
    try:
        response = make_tracked_session().get(url, auth=_auth(email, api_key), timeout=10)
    except requests.exceptions.RequestException:
        return True, None

    if response.status_code in (401, 403):
        return False, "Invalid Upstash email or management API key"
    return True, None


def _fetch_list(session: requests.Session, url: str, auth: tuple[str, str], logger: FilteringBoundLogger) -> list[Any]:
    """Fetch an endpoint that must return a JSON array. A non-list body is a hard error, not an empty
    result: silently yielding nothing would replace the warehouse table with zero rows on an API-shape
    mismatch or a transient proxy body, hiding the failure instead of surfacing it."""
    data = _fetch(session, url, auth, logger)
    if not isinstance(data, list):
        raise ValueError(f"Upstash API returned a non-list response for {url}")
    return data


def _strip_sensitive(row: dict[str, Any], sensitive_fields: frozenset[str]) -> dict[str, Any]:
    """Drop credential-bearing fields (e.g. vector index tokens) before a row reaches the warehouse."""
    if not sensitive_fields:
        return row
    return {key: value for key, value in row.items() if key not in sensitive_fields}


def _iter_database_ids(session: requests.Session, auth: tuple[str, str], logger: FilteringBoundLogger) -> list[str]:
    """List every Redis database id, used to fan out the per-database stats endpoint. A database row
    missing its `database_id` is an invalid response and raises rather than being silently dropped:
    the stats sync depends on every id, so a partial list would produce partial usage/billing data."""
    data = _fetch_list(session, f"{UPSTASH_API_BASE_URL}/redis/databases", auth, logger)
    return [db["database_id"] for db in data if isinstance(db, dict)]


def _fan_out_stats_rows(
    session: requests.Session,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
    config: UpstashEndpointConfig,
) -> Iterator[dict[str, Any]]:
    """Yield one stats row per Redis database, stamping each with its `database_id`.

    The stats object itself carries no id, so we inject `database_id` (the fan-out parent key) to make
    the primary key unique table-wide. A database deleted between enumeration and its stats fetch 404s;
    skip it rather than failing the whole sync.
    """
    for database_id in _iter_database_ids(session, auth, logger):
        url = f"{config.base_url}{config.path.format(database_id=database_id)}"
        try:
            stats = _fetch(session, url, auth, logger)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Upstash: database {database_id} not found while fetching stats, skipping")
                continue
            raise
        if isinstance(stats, dict):
            yield _strip_sensitive({**stats, "database_id": database_id}, config.sensitive_fields)


def get_rows(
    email: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[Any]:
    config = UPSTASH_ENDPOINTS[endpoint]
    auth = _auth(email, api_key)
    # One session reused across every request so urllib3 keeps the connection alive. Endpoints whose
    # responses carry secrets are kept out of HTTP sample capture (the scrubber does not redact tokens).
    session = make_tracked_session(capture=not config.sensitive_fields)

    if config.fan_out_over_databases:
        yield from _fan_out_stats_rows(session, auth, logger, config)
        return

    # Every non-fan-out endpoint returns a raw JSON array in one request (no pagination).
    data = _fetch_list(session, f"{config.base_url}{config.path}", auth, logger)
    for item in data:
        if isinstance(item, dict):
            yield _strip_sensitive(item, config.sensitive_fields)


def upstash_source(
    email: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config = UPSTASH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(email=email, api_key=api_key, endpoint=endpoint, logger=logger),
        primary_keys=endpoint_config.primary_keys,
        # Full refresh with no server-side ordering guarantee; asc is the pipeline default and the
        # tables are replaced wholesale each sync, so no incremental watermark depends on the order.
        sort_mode="asc",
    )
