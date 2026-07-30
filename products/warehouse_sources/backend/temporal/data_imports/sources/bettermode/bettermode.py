import json
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.settings import (
    BETTERMODE_ENDPOINTS,
    BettermodeEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Bettermode serves one GraphQL endpoint per hosting region.
BETTERMODE_HOSTS = {
    "us": "https://api.bettermode.com",
    "eu": "https://api.bettermode.de",
}
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
# Page size when enumerating parent post ids for the replies fan-out — id-only nodes are
# cheap in Bettermode's query-cost model, so the maximum-ish page keeps request count low.
PARENT_PAGE_SIZE = 100

_TOKEN_QUERY = """
query AppToken($networkId: String!) {
  limitedToken(context: NETWORK, networkId: $networkId, entityId: $networkId) {
    accessToken
  }
}
"""

_PARENT_POSTS_QUERY = """
query ParentPosts($limit: Int!, $after: String) {
  posts(limit: $limit, after: $after) {
    pageInfo {
      endCursor
      hasNextPage
    }
    nodes {
      id
      totalRepliesCount
    }
  }
}
"""


class BettermodeRetryableError(Exception):
    pass


class BettermodeGraphQLError(Exception):
    """A GraphQL-level error. Bettermode returns these in HTTP 200 bodies with a status code
    in the error's extensions; the message keeps a stable `Bettermode API error (status N)`
    prefix that `get_non_retryable_errors` matches on."""


@dataclasses.dataclass
class BettermodeResumeConfig:
    # Relay cursor of the last fully-yielded page within the current connection.
    after: str | None = None
    # Replies fan-out bookmark: the parent post currently being processed. A stable post-ID
    # bookmark (not a positional index) so posts created/deleted between a crash and the
    # retry can't resume us into the wrong parent. None for top-level endpoints.
    post_id: str | None = None


def _base_url(region: str) -> str:
    host = BETTERMODE_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Invalid Bettermode region: {region}")
    return host


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor as an ISO 8601 UTC string for a filterBy value."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def _execute(
    session: requests.Session,
    url: str,
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(url, json={"query": query, "variables": variables}, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise BettermodeRetryableError(f"Bettermode API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"Bettermode API error: status={response.status_code}, body={response.text}")
        response.raise_for_status()

    body = response.json()
    errors = body.get("errors")
    if errors:
        # GraphQL errors arrive in 200 responses; the real status lives on the error object
        # (e.g. 401/403 for auth problems, 404 "App not found" for bad client credentials).
        first = errors[0] if isinstance(errors[0], dict) else {}
        status = first.get("status") or (first.get("extensions") or {}).get("status")
        message = "; ".join(str(error.get("message", error)) for error in errors if isinstance(error, dict))
        raise BettermodeGraphQLError(f"Bettermode API error (status {status}): {message}")

    return body.get("data") or {}


class _NoopLogger:
    def error(self, *args: Any, **kwargs: Any) -> None:
        return None


def get_access_token(region: str, client_id: str, client_secret: str, network_id: str) -> str:
    """Mint an app access token (a ~30-day JWT) via the `limitedToken` query.

    The exchange authenticates with HTTP Basic auth of the app's client id/secret; the app
    must be published and installed on the target community or Bettermode responds with a
    403 in the GraphQL errors.
    """
    session = make_tracked_session(redact_values=(client_secret,), capture=False)
    session.auth = (client_id, client_secret)
    data = _execute(session, _base_url(region), _TOKEN_QUERY, {"networkId": network_id}, _NoopLogger())  # type: ignore[arg-type]
    token = (data.get("limitedToken") or {}).get("accessToken")
    if not token:
        raise BettermodeGraphQLError("Bettermode API error (status None): token exchange returned no accessToken")
    return token


def _get_authed_session(region: str, client_id: str, client_secret: str, network_id: str) -> requests.Session:
    token = get_access_token(region, client_id, client_secret, network_id)
    return make_tracked_session(
        headers={"Authorization": f"Bearer {token}"}, redact_values=(token, client_secret), capture=False
    )


def validate_credentials(region: str, client_id: str, client_secret: str, network_id: str) -> tuple[bool, str | None]:
    """One cheap probe: minting the app token validates the client id/secret, the network id,
    and that the app is installed on the community."""
    try:
        get_access_token(region, client_id, client_secret, network_id)
        return True, None
    except BettermodeGraphQLError as e:
        return False, str(e)
    except Exception:
        return False, "Could not reach the Bettermode API"


def _build_query(config: BettermodeEndpointConfig) -> str:
    args = {"limit": "Int!", "after": "String", **config.extra_args}
    declarations = ", ".join(f"${name}: {gql_type}" for name, gql_type in args.items())
    call_args = ", ".join(f"{name}: ${name}" for name in args)
    return f"""
query ({declarations}) {{
  {config.query_field}({call_args}) {{
    pageInfo {{
      endCursor
      hasNextPage
    }}
    nodes {{
{config.node_fields}
    }}
  }}
}}
"""


def _build_post_variables(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Sort and (when incremental) filter variables for the `posts` connection.

    An explicit `orderBy` keeps pagination deterministic across pages. The filter value is a
    JSON-encoded ISO datetime — the format Bettermode's own frontend passes — and `gte`
    re-fetches the boundary row so records sharing the watermark are never skipped (merge
    dedupes on the primary key).
    """
    filter_field = incremental_field or "createdAt"
    variables: dict[str, Any] = {"orderBy": filter_field, "reverse": False}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        variables["filterBy"] = [
            {
                "key": filter_field,
                "operator": "gte",
                "value": json.dumps(_format_datetime(db_incremental_field_last_value)),
            }
        ]
    return variables


def _make_execute(session: requests.Session, url: str, logger: FilteringBoundLogger):
    @retry(
        retry=retry_if_exception_type((BettermodeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return _execute(session, url, query, variables, logger)

    return execute


def _iter_connection(
    execute: Any,
    query: str,
    query_field: str,
    base_variables: dict[str, Any],
    page_size: int,
    after: str | None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Walk one Relay-style connection, yielding `(nodes, next_cursor)` per page.

    `next_cursor` is None on the final page so callers know not to persist resume state
    past the end of the connection.
    """
    while True:
        data = execute(query, {**base_variables, "limit": page_size, "after": after})
        connection = data.get(query_field) or {}
        nodes = connection.get("nodes") or []
        page_info = connection.get("pageInfo") or {}
        has_next = bool(page_info.get("hasNextPage"))
        end_cursor = page_info.get("endCursor")
        next_cursor = end_cursor if has_next and end_cursor and nodes else None

        if nodes:
            yield nodes, next_cursor

        if next_cursor is None:
            break
        after = next_cursor


def _get_reply_rows(
    execute: Any,
    config: BettermodeEndpointConfig,
    resumable_source_manager: ResumableSourceManager[BettermodeResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out one `replies(postId: ...)` connection per post that has replies.

    Bettermode has no flat network-wide replies listing, so parents are enumerated with a
    cheap id-only posts walk first. Only direct replies of listed posts are fetched.
    """
    parent_ids: list[str] = []
    for nodes, _ in _iter_connection(execute, _PARENT_POSTS_QUERY, "posts", {}, PARENT_PAGE_SIZE, None):
        parent_ids.extend(node["id"] for node in nodes if (node.get("totalRepliesCount") or 0) > 0)

    # Resolve the saved post-ID bookmark to the slice of parents still to process. If the
    # bookmarked post no longer exists, start over — merge dedupes re-pulled rows on the
    # primary key. `resume_after` is consumed by the bookmarked parent only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = parent_ids
    resume_after: str | None = None
    if resume is not None and resume.post_id is not None and resume.post_id in parent_ids:
        remaining = parent_ids[parent_ids.index(resume.post_id) :]
        resume_after = resume.after
        logger.debug(f"Bettermode: resuming replies from post_id={resume.post_id}")

    query = _build_query(config)
    for index, post_id in enumerate(remaining):
        variables = {"postId": post_id, "orderBy": "createdAt", "reverse": False}
        for nodes, next_cursor in _iter_connection(
            execute, query, "replies", variables, config.page_size, resume_after
        ):
            yield nodes
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields the
            # last page rather than skipping it — merge dedupes on the primary key.
            if next_cursor:
                resumable_source_manager.save_state(BettermodeResumeConfig(after=next_cursor, post_id=post_id))
        resume_after = None

        # Advance the bookmark so a crash between parents resumes at the next post.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(BettermodeResumeConfig(after=None, post_id=remaining[index + 1]))


def get_rows(
    region: str,
    client_id: str,
    client_secret: str,
    network_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BettermodeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = BETTERMODE_ENDPOINTS[endpoint]
    session = _get_authed_session(region, client_id, client_secret, network_id)
    execute = _make_execute(session, _base_url(region), logger)

    if config.fan_out_replies:
        yield from _get_reply_rows(execute, config, resumable_source_manager, logger)
        return

    base_variables: dict[str, Any] = {}
    if config.query_field == "posts":
        base_variables = _build_post_variables(
            should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after = resume.after if resume is not None else None
    if after is not None:
        logger.debug(f"Bettermode: resuming {endpoint} from cursor")

    query = _build_query(config)
    for nodes, next_cursor in _iter_connection(
        execute, query, config.query_field, base_variables, config.page_size, after
    ):
        yield nodes
        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the
        # primary key) rather than skipping it.
        if next_cursor:
            resumable_source_manager.save_state(BettermodeResumeConfig(after=next_cursor))


def bettermode_source(
    region: str,
    client_id: str,
    client_secret: str,
    network_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BettermodeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = BETTERMODE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            client_id=client_id,
            client_secret=client_secret,
            network_id=network_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Bettermode doesn't document connection ordering guarantees, so the pipeline defers
        # the incremental watermark commit until a run completes.
        sort_mode="desc",
    )
