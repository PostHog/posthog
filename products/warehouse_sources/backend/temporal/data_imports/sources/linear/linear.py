import dataclasses
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.linear.queries import QUERIES, VIEWER_QUERY
from products.warehouse_sources.backend.temporal.data_imports.sources.linear.settings import (
    LINEAR_API_URL,
    LINEAR_DEFAULT_PAGE_SIZE,
    LINEAR_ENDPOINTS,
)

# Linear's edge returns short bursts of 5xx/429 that clear within a minute or two, so
# retry in-process long enough to ride those out before failing the activity. The backoff
# blocks the source thread, but heartbeats are sent from an independent background task
# (LivenessHeartbeater), so a multi-minute wait here doesn't trip the activity heartbeat
# timeout. Genuine outages still fall through to Temporal rescheduling the whole activity,
# which resumes from the saved cursor.
LINEAR_MAX_RETRY_ATTEMPTS = 8
# Cap how long a single Retry-After can stall us, so a misbehaving header sending a huge
# value can't pin the activity open for an unreasonable time.
LINEAR_MAX_RETRY_AFTER_SECONDS = 60
# Stateless backoff used when a 429 carries no usable Retry-After hint.
_LINEAR_FALLBACK_WAIT = wait_exponential_jitter(initial=1, max=60)


class LinearRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        # Seconds Linear asked us to wait (from a 429 Retry-After), if any.
        self.retry_after = retry_after


def _parse_retry_after(response: requests.Response) -> float | None:
    """Linear's edge fronts 429s with a standard Retry-After in delta-seconds; ignore other forms."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, seconds)


def _wait_strategy(retry_state: RetryCallState) -> float:
    """Honor a 429's Retry-After when present, else fall back to jittered exponential backoff.

    Doing the wait here (rather than time.sleep inside execute) avoids stacking both delays.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    if isinstance(exc, LinearRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, LINEAR_MAX_RETRY_AFTER_SECONDS)
    return _LINEAR_FALLBACK_WAIT(retry_state)


@dataclasses.dataclass
class LinearResumeConfig:
    cursor: str


def _make_paginated_request(
    access_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LinearResumeConfig],
    updated_at_gte: str | None = None,
):
    endpoint_config = LINEAR_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown Linear endpoint: {endpoint_name}")

    query = QUERIES.get(endpoint_name)
    if not query:
        raise ValueError(f"No GraphQL query for endpoint: {endpoint_name}")

    graphql_query_name = endpoint_config.graphql_query_name or endpoint_name

    sess = make_tracked_session(
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
    )

    @retry(
        retry=retry_if_exception_type(LinearRetryableError),
        stop=stop_after_attempt(LINEAR_MAX_RETRY_ATTEMPTS),
        wait=_wait_strategy,
        reraise=True,
    )
    def execute(variables: dict[str, Any]) -> dict:
        try:
            response = sess.post(LINEAR_API_URL, json={"query": query, "variables": variables}, timeout=60)
        except (requests.ConnectionError, requests.Timeout) as e:
            # The session's urllib3 Retry only covers idempotent methods, so Linear's POSTs get no
            # transport-level retry. Route transient network failures (read timeout, connection reset)
            # through the same backoff path as 5xx/429 instead of failing the whole activity on one blip.
            raise LinearRetryableError(f"Linear: transient network error - {e}")

        if response.status_code >= 500:
            raise LinearRetryableError(f"Linear: server error {response.status_code}")

        # Linear answers HTTP-level rate limits with a 429 and an HTML body (not GraphQL JSON),
        # so this must be caught before the JSON parse below. Otherwise response.json() raises a
        # JSONDecodeError that escalates to a plain, non-retryable Exception instead of being
        # retried with backoff like the GraphQL-level RATELIMITED case. The blind exponential
        # backoff often gives up before Linear's rate-limit window resets, so honor the
        # Retry-After it sends when present and fall back to the exponential otherwise.
        if response.status_code == 429:
            raise LinearRetryableError("Linear: rate limited (429)", retry_after=_parse_retry_after(response))

        try:
            payload = response.json()
        except Exception as e:
            if not response.ok:
                raise Exception(
                    f"{response.status_code} Client Error: {response.reason} (Linear API: {response.text})"
                ) from e
            # A 2xx whose body won't parse as JSON is almost always a truncated transfer (the
            # connection dropped mid-body on a large page), not a stable response Linear will keep
            # returning. Ride it out on the same backoff path as other transient failures instead of
            # failing the activity outright. Don't echo response.text — a partial body carries data.
            raise LinearRetryableError(f"Linear: incomplete JSON response ({e})") from e

        if "errors" in payload:
            error_messages = [e.get("message", "") for e in payload["errors"]]
            joined = "; ".join(error_messages)
            if any(e.get("extensions", {}).get("code") == "RATELIMITED" for e in payload["errors"]):
                raise LinearRetryableError(f"Linear: rate limited - {joined}")
            if not response.ok:
                raise Exception(f"{response.status_code} Client Error: {response.reason} (Linear API: {joined})")
            raise Exception(f"Linear GraphQL error: {joined}")

        if not response.ok:
            raise Exception(f"{response.status_code} Client Error: {response.reason} (Linear API: {payload})")

        if "data" not in payload:
            raise Exception(f"Unexpected Linear response format. Keys: {list(payload.keys())}")

        return payload

    variables: dict[str, Any] = {"pageSize": LINEAR_DEFAULT_PAGE_SIZE}

    if updated_at_gte:
        variables["filter"] = {"updatedAt": {"gt": updated_at_gte}}

    resume_config = resumable_source_manager.load_state()
    if resume_config is not None:
        variables["cursor"] = resume_config.cursor
        logger.debug(f"Linear: resuming {endpoint_name} from saved cursor")

    try:
        has_next_page = True
        while has_next_page:
            logger.debug(f"Querying Linear endpoint {endpoint_name} with variables: {variables}")
            payload = execute(variables)

            data = payload["data"][graphql_query_name]["nodes"]
            yield data

            page_info = payload["data"][graphql_query_name]["pageInfo"]
            has_next_page = page_info["hasNextPage"]
            if has_next_page:
                end_cursor = page_info.get("endCursor")
                if not end_cursor:
                    # If the API reports hasNextPage=True with a missing/null endCursor the
                    # paginator would loop forever on the same page. Fail the run instead of
                    # silently returning partial results, so the issue is visible.
                    raise Exception(f"Linear: hasNextPage=True but endCursor is empty for {endpoint_name}")
                variables["cursor"] = end_cursor
                # Checkpoint points at the next page to fetch. On resume the first request
                # re-fetches that page; full-refresh appends and incremental merges on the
                # endpoint's primary_key, so duplicates are tolerated.
                resumable_source_manager.save_state(LinearResumeConfig(cursor=end_cursor))
    finally:
        sess.close()


def linear_source(
    access_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LinearResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
) -> SourceResponse:
    endpoint_config = LINEAR_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown Linear endpoint: {endpoint_name}")

    def get_rows():
        updated_at_gte = None
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            updated_at_gte = str(db_incremental_field_last_value)
            logger.debug(f"Linear: incremental sync for {endpoint_name} since {updated_at_gte}")

        yield from _make_paginated_request(
            access_token=access_token,
            endpoint_name=endpoint_name,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            updated_at_gte=updated_at_gte,
        )

    return SourceResponse(
        items=get_rows,
        primary_keys=[endpoint_config.primary_key],
        name=endpoint_name,
        partition_count=endpoint_config.partition_count,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    try:
        sess = make_tracked_session(
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
        )
        response = sess.post(
            LINEAR_API_URL,
            json={"query": VIEWER_QUERY},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            return False, f"Linear API error: {data['errors']}"
        if "data" in data and data["data"].get("viewer"):
            return True, None
        return False, "Could not verify Linear credentials"
    except Exception as e:
        return False, str(e)
