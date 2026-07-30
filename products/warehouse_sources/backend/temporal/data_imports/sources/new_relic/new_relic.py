import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
import structlog
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.settings import (
    NEW_RELIC_ENDPOINTS,
    NewRelicEndpointConfig,
)

# NerdGraph is region-scoped: EU-datacenter accounts only answer on the EU host.
NEW_RELIC_GRAPHQL_URLS: dict[str, str] = {
    "US": "https://api.newrelic.com/graphql",
    "EU": "https://api.eu.newrelic.com/graphql",
}

REQUEST_TIMEOUT_SECONDS = 130  # must exceed the 120s server-side NRQL timeout we request
MAX_RETRY_ATTEMPTS = 5

# NRQL returns at most 5,000 rows per query (LIMIT MAX), so event tables are read in
# time windows that are recursively halved whenever a window fills up.
NRQL_ROW_LIMIT = 5000
DEFAULT_WINDOW_MS = int(timedelta(hours=6).total_seconds() * 1000)
MIN_WINDOW_MS = 1000
# Events are queried UNTIL now minus this buffer: New Relic ingests with some lag, and an
# append-only sync would permanently miss events that land after their window was read.
INGEST_LAG_BUFFER_MS = int(timedelta(minutes=5).total_seconds() * 1000)
# First sync / full refresh reaches back this far. New Relic's raw event retention is
# plan-dependent (typically 8-90 days), so older windows simply come back empty.
DEFAULT_LOOKBACK_DAYS = 30

NRQL_QUERY = """
query ($accountId: Int!, $nrql: Nrql!) {
  actor {
    account(id: $accountId) {
      nrql(query: $nrql, timeout: 120) {
        results
      }
    }
  }
}
"""

# Conservative field set: only fields available on every EntityOutline type, so the query
# can't fail on accounts whose entities span domains we didn't anticipate.
ENTITY_SEARCH_QUERY = """
query ($query: String!, $cursor: String) {
  actor {
    entitySearch(query: $query) {
      results(cursor: $cursor) {
        entities {
          guid
          name
          accountId
          domain
          type
          entityType
          reporting
          permalink
          tags {
            key
            values
          }
        }
        nextCursor
      }
    }
  }
}
"""

ALERT_POLICIES_QUERY = """
query ($accountId: Int!, $cursor: String) {
  actor {
    account(id: $accountId) {
      alerts {
        policiesSearch(cursor: $cursor) {
          policies {
            id
            accountId
            name
            incidentPreference
          }
          nextCursor
        }
      }
    }
  }
}
"""

ALERT_CONDITIONS_QUERY = """
query ($accountId: Int!, $cursor: String) {
  actor {
    account(id: $accountId) {
      alerts {
        nrqlConditionsSearch(cursor: $cursor) {
          nrqlConditions {
            id
            name
            policyId
            enabled
            description
            runbookUrl
            type
            nrql {
              query
            }
          }
          nextCursor
        }
      }
    }
  }
}
"""

VALIDATE_QUERY = """
query ($accountId: Int!) {
  actor {
    account(id: $accountId) {
      id
      name
    }
  }
}
"""


class NewRelicRetryableError(Exception):
    pass


class NewRelicGraphQLError(Exception):
    """NerdGraph returned HTTP 200 with an `errors` array (bad query, missing account access, ...)."""


@dataclasses.dataclass
class NewRelicResumeConfig:
    # Start (epoch ms) of the next NRQL time window still to fetch. Only event tables save
    # resume state: their windows stay valid indefinitely, whereas NerdGraph pagination
    # cursors can expire — resuming a stale cursor would wedge every retry until the
    # 24h state TTL passes, so entity-style tables restart from scratch instead.
    window_start_ms: int | None = None


def get_graphql_url(region: str | None) -> str:
    return NEW_RELIC_GRAPHQL_URLS.get((region or "US").upper(), NEW_RELIC_GRAPHQL_URLS["US"])


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(headers={"API-Key": api_key}, redact_values=(api_key,))


@retry(
    retry=retry_if_exception_type(
        (
            NewRelicRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _execute_graphql(
    session: requests.Session,
    url: str,
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(url, json={"query": query, "variables": variables}, timeout=REQUEST_TIMEOUT_SECONDS)

    # 25 concurrent NerdGraph requests per user / 3,000 NRQL queries per account per
    # minute surface as 429s; both clear on their own, so back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise NewRelicRetryableError(f"New Relic API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"New Relic API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    body = response.json()
    errors = body.get("errors")
    if errors:
        messages = "; ".join(str(error.get("message", error)) for error in errors)
        # NerdGraph reports server-side timeouts/deadlines inside `errors` on an HTTP 200.
        if any(term in messages.lower() for term in ("timeout", "deadline", "too many requests")):
            raise NewRelicRetryableError(f"New Relic GraphQL error (retryable): {messages}")
        raise NewRelicGraphQLError(f"New Relic GraphQL error: {messages}")

    return body.get("data") or {}


GraphQLExecutor = Callable[[str, dict[str, Any]], dict[str, Any]]


def _make_executor(api_key: str, region: str | None, logger: FilteringBoundLogger) -> GraphQLExecutor:
    # One session for the whole sync so urllib3 keeps the connection alive across queries.
    session = _get_session(api_key)
    url = get_graphql_url(region)

    def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return _execute_graphql(session, url, query, variables, logger)

    return execute


def validate_credentials(api_key: str, account_id: int, region: str | None) -> tuple[bool, str | None]:
    # Credential validation runs outside a sync job, so there's no job-bound logger to pass.
    execute = _make_executor(api_key, region, structlog.get_logger(__name__))
    try:
        data = execute(VALIDATE_QUERY, {"accountId": account_id})
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (401, 403):
            return False, "Invalid New Relic API key. Create a User API key in your New Relic account and try again."
        return False, f"Could not connect to New Relic: {exc}"
    except NewRelicGraphQLError as exc:
        return False, f"Could not access New Relic account {account_id}: {exc}"
    except Exception as exc:
        return False, f"Could not connect to New Relic: {exc}"

    account = (data.get("actor") or {}).get("account")
    if not account:
        return (
            False,
            f"Your API key is valid but has no access to account {account_id}. "
            "Check the account ID and that the key belongs to a user on that account.",
        )
    return True, None


def _to_epoch_ms(value: Any) -> int:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, int | float):
        return int(value)
    raise ValueError(f"Cannot convert incremental value to epoch milliseconds: {value!r}")


def _normalize_event_row(row: dict[str, Any]) -> dict[str, Any]:
    # NRQL returns `timestamp` as epoch ms; store it as a datetime so incremental cursors
    # and datetime partitioning work on it directly.
    timestamp = row.get("timestamp")
    if isinstance(timestamp, int | float):
        row["timestamp"] = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
    return row


_EPOCH_MIN = datetime.min.replace(tzinfo=UTC)


def _sort_timestamp(row: dict[str, Any]) -> datetime:
    # Rows without a parseable timestamp sort first so they can't inflate the pipeline's
    # per-batch incremental watermark past rows that follow them.
    timestamp = row.get("timestamp")
    return timestamp if isinstance(timestamp, datetime) else _EPOCH_MIN


def _run_nrql(execute: GraphQLExecutor, account_id: int, nrql: str) -> list[dict[str, Any]]:
    data = execute(NRQL_QUERY, {"accountId": account_id, "nrql": nrql})
    account = (data.get("actor") or {}).get("account") or {}
    return (account.get("nrql") or {}).get("results") or []


def _fetch_event_window(
    execute: GraphQLExecutor,
    account_id: int,
    table: str,
    start_ms: int,
    end_ms: int,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Fetch every event in [start_ms, end_ms), recursively halving windows that hit the
    5,000-row NRQL cap. Yields each completed sub-window's rows sorted ascending by
    timestamp, in ascending sub-window order, so the overall stream is ascending and the
    pipeline's per-batch incremental watermark stays correct."""
    results = _run_nrql(
        execute,
        account_id,
        f"SELECT * FROM {table} SINCE {start_ms} UNTIL {end_ms} LIMIT MAX",
    )

    if len(results) >= NRQL_ROW_LIMIT and (end_ms - start_ms) > MIN_WINDOW_MS:
        mid_ms = (start_ms + end_ms) // 2
        yield from _fetch_event_window(execute, account_id, table, start_ms, mid_ms, logger)
        yield from _fetch_event_window(execute, account_id, table, mid_ms, end_ms, logger)
        return

    if len(results) >= NRQL_ROW_LIMIT:
        logger.warning(
            f"New Relic: {table} returned {len(results)} rows for a {end_ms - start_ms}ms window "
            f"[{start_ms}, {end_ms}); rows beyond the NRQL 5,000-row cap in this window are skipped"
        )

    if results:
        rows = [_normalize_event_row(row) for row in results]
        rows.sort(key=_sort_timestamp)
        yield rows


def _get_event_rows(
    execute: GraphQLExecutor,
    account_id: int,
    config: NewRelicEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewRelicResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    assert config.nrql_table is not None

    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    until_ms = now_ms - INGEST_LAG_BUFFER_MS

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # +1ms past the watermark: these tables sync append-only (no primary key to merge
        # on), so re-reading the boundary millisecond would materialize duplicate rows.
        since_ms = min(_to_epoch_ms(db_incremental_field_last_value) + 1, until_ms)
    else:
        since_ms = now_ms - int(timedelta(days=DEFAULT_LOOKBACK_DAYS).total_seconds() * 1000)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start_ms is not None:
        since_ms = max(since_ms, resume.window_start_ms)
        logger.debug(f"New Relic: resuming {config.name} from window start {since_ms}")

    window_start_ms = since_ms
    while window_start_ms < until_ms:
        window_end_ms = min(window_start_ms + DEFAULT_WINDOW_MS, until_ms)

        yield from _fetch_event_window(execute, account_id, config.nrql_table, window_start_ms, window_end_ms, logger)

        # Save AFTER yielding (and only when more windows remain) so a crash re-yields the
        # last window rather than skipping it — losing data is worse than the duplicate
        # rows a re-yield can append.
        if window_end_ms < until_ms:
            resumable_source_manager.save_state(NewRelicResumeConfig(window_start_ms=window_end_ms))

        window_start_ms = window_end_ms


def _iter_entities(execute: GraphQLExecutor, account_id: int) -> Iterator[list[dict[str, Any]]]:
    cursor: str | None = None
    while True:
        data = execute(ENTITY_SEARCH_QUERY, {"query": f"accountId = {account_id}", "cursor": cursor})
        results = (data.get("actor") or {}).get("entitySearch", {}).get("results") or {}
        entities = results.get("entities") or []
        if entities:
            yield entities
        cursor = results.get("nextCursor")
        if not cursor:
            return


def _iter_alert_policies(execute: GraphQLExecutor, account_id: int) -> Iterator[list[dict[str, Any]]]:
    cursor: str | None = None
    while True:
        data = execute(ALERT_POLICIES_QUERY, {"accountId": account_id, "cursor": cursor})
        search = ((data.get("actor") or {}).get("account") or {}).get("alerts", {}).get("policiesSearch") or {}
        policies = search.get("policies") or []
        if policies:
            yield policies
        cursor = search.get("nextCursor")
        if not cursor:
            return


def _flatten_alert_condition(condition: dict[str, Any]) -> dict[str, Any]:
    nrql = condition.pop("nrql", None)
    if isinstance(nrql, dict):
        condition["nrql_query"] = nrql.get("query")
    return condition


def _iter_alert_conditions(execute: GraphQLExecutor, account_id: int) -> Iterator[list[dict[str, Any]]]:
    cursor: str | None = None
    while True:
        data = execute(ALERT_CONDITIONS_QUERY, {"accountId": account_id, "cursor": cursor})
        search = ((data.get("actor") or {}).get("account") or {}).get("alerts", {}).get("nrqlConditionsSearch") or {}
        conditions = search.get("nrqlConditions") or []
        if conditions:
            yield [_flatten_alert_condition(condition) for condition in conditions]
        cursor = search.get("nextCursor")
        if not cursor:
            return


_ENTITY_STYLE_ITERATORS: dict[str, Callable[[GraphQLExecutor, int], Iterator[list[dict[str, Any]]]]] = {
    "entities": _iter_entities,
    "alert_policies": _iter_alert_policies,
    "alert_conditions": _iter_alert_conditions,
}


def get_rows(
    api_key: str,
    account_id: int,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewRelicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = NEW_RELIC_ENDPOINTS[endpoint]
    execute = _make_executor(api_key, region, logger)

    if config.nrql_table is not None:
        yield from _get_event_rows(
            execute,
            account_id,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    yield from _ENTITY_STYLE_ITERATORS[endpoint](execute, account_id)


def new_relic_source(
    api_key: str,
    account_id: int,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewRelicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = NEW_RELIC_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            account_id=account_id,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        sort_mode="asc",
        partition_count=1 if endpoint_config.partition_key else None,
        partition_size=1 if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
