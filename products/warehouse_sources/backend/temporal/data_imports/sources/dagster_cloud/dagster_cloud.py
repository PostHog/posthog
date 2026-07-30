import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.queries import VALIDATION_QUERY
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.settings import (
    DAGSTER_CLOUD_ENDPOINTS,
    DAGSTER_CLOUD_PAGE_SIZE,
    DagsterCloudEndpointConfig,
)

# Dagster+'s edge occasionally returns short bursts of 5xx/429; retry in-process long enough to
# ride those out. The wait blocks the source thread, but activity heartbeats are sent from an
# independent background task, so a multi-minute wait here won't trip the heartbeat timeout.
DAGSTER_CLOUD_MAX_RETRY_ATTEMPTS = 8

# Only letters/numbers/hyphen/underscore: the organization is a `*.dagster.cloud` subdomain label
# and the deployment a path segment, so restricting them keeps a crafted value from redirecting the
# stored token to an arbitrary host.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class DagsterCloudRetryableError(Exception):
    pass


@dataclasses.dataclass
class DagsterCloudResumeConfig:
    cursor: str


def build_graphql_url(organization: str, deployment: str) -> str:
    org = (organization or "").strip()
    deploy = (deployment or "").strip()
    if not _SLUG_RE.match(org) or not _SLUG_RE.match(deploy):
        raise ValueError(
            "Dagster+ organization and deployment must contain only letters, numbers, hyphens, and underscores."
        )
    return f"https://{org}.dagster.cloud/{deploy}/graphql"


def _make_session(api_token: str) -> requests.Session:
    # `Dagster-Cloud-Api-Token` is a custom header the sample-capture scrubber doesn't know, so the
    # token must be redacted by value; redirects stay off because `requests` only strips the standard
    # `Authorization` header on a cross-host redirect — a 30x would forward this header to its target.
    return make_tracked_session(
        headers={
            "Dagster-Cloud-Api-Token": api_token,
            "Content-Type": "application/json",
        },
        redact_values=(api_token,),
        allow_redirects=False,
    )


def _epoch_to_iso(value: Any) -> Any:
    """Normalize a Dagster epoch-seconds float to an ISO-8601 UTC string (fixed precision).

    Fixed microsecond precision keeps the watermark's max comparison stable regardless of whether
    the framework tracks it as a datetime or lexicographically. Non-numeric values pass through.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat(timespec="microseconds")
    return value


def _to_epoch_seconds(value: Any) -> float | None:
    """Convert an incremental watermark (datetime / date / ISO string / number) to epoch seconds.

    RunsFilter's createdAfter/updatedAfter are Float epoch seconds, but the framework can hand the
    stored watermark back in any of these shapes depending on how it round-tripped the column.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.timestamp()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp()
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    return None


def _build_runs_filter(incremental_field: str | None, last_value_epoch: float | None) -> dict[str, float] | None:
    if last_value_epoch is None:
        return None
    # createdAfter for a creation-time cursor, updatedAfter for everything else (the default).
    filter_key = "createdAfter" if incremental_field == "creationTime" else "updatedAfter"
    return {filter_key: last_value_epoch}


def _normalize_row(row: dict[str, Any], endpoint_config: DagsterCloudEndpointConfig) -> dict[str, Any]:
    if not endpoint_config.timestamp_fields:
        return row
    normalized = dict(row)
    for field_name in endpoint_config.timestamp_fields:
        if normalized.get(field_name) is not None:
            normalized[field_name] = _epoch_to_iso(normalized[field_name])
    return normalized


def _make_paginated_request(
    organization: str,
    deployment: str,
    api_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DagsterCloudResumeConfig],
    runs_filter: dict[str, float] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = DAGSTER_CLOUD_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown Dagster Cloud endpoint: {endpoint_name}")

    url = build_graphql_url(organization, deployment)
    sess = _make_session(api_token)

    @retry(
        retry=retry_if_exception_type(DagsterCloudRetryableError),
        stop=stop_after_attempt(DAGSTER_CLOUD_MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def execute(variables: dict[str, Any]) -> dict:
        try:
            response = sess.post(url, json={"query": endpoint_config.query, "variables": variables}, timeout=60)
        except (requests.ConnectionError, requests.Timeout) as e:
            # The session's urllib3 Retry only covers idempotent methods, so these POSTs get no
            # transport-level retry — fold transient network failures into the application backoff.
            raise DagsterCloudRetryableError(f"Dagster Cloud: transient network error - {e}")

        if response.status_code >= 500:
            raise DagsterCloudRetryableError(f"Dagster Cloud: server error {response.status_code}")
        if response.status_code == 429:
            raise DagsterCloudRetryableError("Dagster Cloud: rate limited (429)")
        # Redirects are pinned off (see _make_session), so a 30x is terminal — following it would
        # hand the token header to whatever host the Location points at.
        if 300 <= response.status_code < 400:
            raise Exception(f"Dagster Cloud: unexpected redirect ({response.status_code}) for url: {url}")

        try:
            payload = response.json()
        except Exception as e:
            if not response.ok:
                raise Exception(f"{response.status_code} Client Error: {response.reason} for url: {url}") from e
            # A 2xx whose body won't parse is almost always a truncated transfer; ride it out rather
            # than failing the activity. Don't echo the body — a partial page can carry data.
            raise DagsterCloudRetryableError(f"Dagster Cloud: incomplete JSON response ({e})") from e

        if not response.ok:
            raise Exception(f"{response.status_code} Client Error: {response.reason} for url: {url}")

        if "errors" in payload:
            messages = "; ".join(e.get("message", "") for e in payload["errors"])
            if "rate limit" in messages.lower():
                raise DagsterCloudRetryableError(f"Dagster Cloud: rate limited - {messages}")
            raise Exception(f"Dagster Cloud GraphQL error: {messages}")

        if "data" not in payload:
            raise Exception(f"Unexpected Dagster Cloud response format. Keys: {list(payload.keys())}")

        return payload

    variables: dict[str, Any] = {"limit": DAGSTER_CLOUD_PAGE_SIZE}
    if runs_filter is not None:
        variables["filter"] = runs_filter

    resume_config = resumable_source_manager.load_state()
    if resume_config is not None and resume_config.cursor:
        variables["cursor"] = resume_config.cursor
        logger.debug(f"Dagster Cloud: resuming {endpoint_name} from saved cursor")

    try:
        while True:
            payload = execute(variables)
            container = payload["data"][endpoint_config.response_field]

            typename = container.get("__typename")
            if typename != endpoint_config.success_typename:
                message = container.get("message", "")
                raise Exception(f"Dagster Cloud {endpoint_config.response_field} returned {typename}: {message}")

            rows = container.get(endpoint_config.results_key) or []
            yield [_normalize_row(row, endpoint_config) for row in rows]

            # A short page means we've reached the end of the (optionally filtered) result set.
            if len(rows) < DAGSTER_CLOUD_PAGE_SIZE:
                break

            if endpoint_config.cursor_mode == "connection":
                next_cursor = container.get("cursor")
            else:
                assert endpoint_config.cursor_row_field is not None
                next_cursor = rows[-1].get(endpoint_config.cursor_row_field)

            if not next_cursor:
                break

            variables["cursor"] = next_cursor
            # Checkpoint the next page to fetch AFTER yielding this one, so a crash re-fetches the
            # last page rather than skipping it — merge dedupes the overlap on primary_keys.
            resumable_source_manager.save_state(DagsterCloudResumeConfig(cursor=str(next_cursor)))
    finally:
        sess.close()


def dagster_cloud_source(
    organization: str,
    deployment: str,
    api_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DagsterCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = DAGSTER_CLOUD_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown Dagster Cloud endpoint: {endpoint_name}")

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        runs_filter = None
        if (
            endpoint_config.supports_incremental
            and should_use_incremental_field
            and db_incremental_field_last_value is not None
        ):
            last_value_epoch = _to_epoch_seconds(db_incremental_field_last_value)
            runs_filter = _build_runs_filter(incremental_field, last_value_epoch)
            logger.debug(f"Dagster Cloud: incremental sync for {endpoint_name} with filter {runs_filter}")

        yield from _make_paginated_request(
            organization=organization,
            deployment=deployment,
            api_token=api_token,
            endpoint_name=endpoint_name,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            runs_filter=runs_filter,
        )

    return SourceResponse(
        name=endpoint_name,
        items=get_rows,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode=endpoint_config.sort_mode,
    )


def validate_credentials(organization: str, deployment: str, api_token: str) -> tuple[bool, str | None]:
    try:
        url = build_graphql_url(organization, deployment)
    except ValueError as e:
        return False, str(e)

    try:
        sess = _make_session(api_token)
        response = sess.post(url, json={"query": VALIDATION_QUERY}, timeout=10)
        if response.status_code in (401, 403):
            return False, "Invalid Dagster+ API token, or the token cannot access this deployment."
        if 300 <= response.status_code < 400:
            return False, "Dagster+ responded with an unexpected redirect. Check the organization and deployment names."
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            return False, f"Dagster+ API error: {data['errors']}"
        if data.get("data") is not None:
            return True, None
        return False, "Could not verify Dagster+ credentials"
    except Exception as e:
        return False, str(e)
