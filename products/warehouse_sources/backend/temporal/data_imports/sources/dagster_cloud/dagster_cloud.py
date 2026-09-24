import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.queries import VALIDATION_QUERY
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.settings import (
    DAGSTER_CLOUD_ENDPOINTS,
    DAGSTER_CLOUD_PAGE_SIZE,
    REPOSITORIES_PARENT_CONFIG,
    DagsterCloudEndpointConfig,
    DagsterCloudFanOutConfig,
    WindowUnit,
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


@frozen
class DagsterCloudResumeConfig:
    # Top-level endpoints: the next page cursor to request.
    cursor: str = ""
    # Fan-out endpoints: how many parents of the walk finished, and where the parent after them
    # had got to in its backwards page walk. The parent walk itself is replayed from the start on
    # resume — parent lists are small and cheap next to the child pages they drive.
    parents_done: int = 0
    window_cursor: str = ""


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


def _millis_to_iso(value: Any) -> Any:
    """Normalize a Dagster epoch-milliseconds value to an ISO-8601 UTC string.

    The asset event resolvers return `timestamp` as a string of epoch milliseconds, unlike the
    run/backfill resolvers' epoch-seconds floats. Non-numeric values pass through.
    """
    if isinstance(value, bool):
        return value
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return value
    return datetime.fromtimestamp(millis / 1000.0, tz=UTC).isoformat(timespec="microseconds")


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
    if not endpoint_config.timestamp_fields and not endpoint_config.millis_timestamp_fields:
        return row
    normalized = dict(row)
    for field_name in endpoint_config.timestamp_fields:
        if normalized.get(field_name) is not None:
            normalized[field_name] = _epoch_to_iso(normalized[field_name])
    for field_name in endpoint_config.millis_timestamp_fields:
        if normalized.get(field_name) is not None:
            normalized[field_name] = _millis_to_iso(normalized[field_name])
    return normalized


def _raise_for_http_status(response: requests.Response, url: str) -> None:
    if response.status_code >= 500:
        raise DagsterCloudRetryableError(f"Dagster Cloud: server error {response.status_code}")
    if response.status_code == 429:
        raise DagsterCloudRetryableError("Dagster Cloud: rate limited (429)")
    # Redirects are pinned off (see _make_session), so a 30x is terminal — following it would
    # hand the token header to whatever host the Location points at.
    if 300 <= response.status_code < 400:
        raise Exception(f"Dagster Cloud: unexpected redirect ({response.status_code}) for url: {url}")
    if not response.ok:
        raise Exception(f"{response.status_code} Client Error: {response.reason} for url: {url}")


def _parse_json_body(response: requests.Response) -> dict[str, Any]:
    try:
        return response.json()
    except Exception as e:
        # The status is already known good, so a body that won't parse is almost always a truncated
        # transfer; ride it out rather than failing the activity. Don't echo the body — a partial
        # page can carry data.
        raise DagsterCloudRetryableError(f"Dagster Cloud: incomplete JSON response ({e})") from e


def _raise_for_graphql_errors(payload: dict[str, Any]) -> None:
    if "errors" in payload:
        messages = "; ".join(e.get("message", "") for e in payload["errors"])
        if "rate limit" in messages.lower():
            raise DagsterCloudRetryableError(f"Dagster Cloud: rate limited - {messages}")
        raise Exception(f"Dagster Cloud GraphQL error: {messages}")

    if "data" not in payload:
        raise Exception(f"Unexpected Dagster Cloud response format. Keys: {list(payload.keys())}")


def _validate_response(response: requests.Response, url: str) -> dict[str, Any]:
    # Anything worth another attempt raises DagsterCloudRetryableError; every other failure raises a
    # plain Exception, which the retry below treats as terminal.
    _raise_for_http_status(response, url)
    payload = _parse_json_body(response)
    _raise_for_graphql_errors(payload)
    return payload


@retry(
    retry=retry_if_exception_type(DagsterCloudRetryableError),
    stop=stop_after_attempt(DAGSTER_CLOUD_MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _execute_query(sess: requests.Session, url: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    try:
        response = sess.post(url, json={"query": query, "variables": variables}, timeout=60)
    except (requests.ConnectionError, requests.Timeout) as e:
        # The session's urllib3 Retry only covers idempotent methods, so these POSTs get no
        # transport-level retry — fold transient network failures into the application backoff.
        raise DagsterCloudRetryableError(f"Dagster Cloud: transient network error - {e}")

    return _validate_response(response, url)


def _extract_rows(
    payload: dict[str, Any], endpoint_config: DagsterCloudEndpointConfig
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Unwrap the OrError union member holding the rows.

    Returns the container alongside its rows (the container carries the connection cursor), or
    None when the response says the parent is gone — a fan-out reads its parent list before its
    children, so a parent deleted in between must be skipped rather than fail the sync.
    """
    container = payload["data"][endpoint_config.response_field]
    if endpoint_config.success_typename is None:
        # The root field returns the row list directly rather than an OrError union (assetNodes).
        return {}, list(container or [])

    typename = container.get("__typename")
    if typename in endpoint_config.skip_typenames:
        return None
    if typename != endpoint_config.success_typename:
        message = container.get("message", "")
        raise Exception(f"Dagster Cloud {endpoint_config.response_field} returned {typename}: {message}")
    return container, list(container.get(endpoint_config.results_key) or [])


def _read_next_cursor(
    container: dict[str, Any], rows: list[dict[str, Any]], endpoint_config: DagsterCloudEndpointConfig
) -> Any:
    if endpoint_config.cursor_mode == "connection":
        return container.get("cursor")
    assert endpoint_config.cursor_row_field is not None
    return rows[-1].get(endpoint_config.cursor_row_field)


def _iter_cursor_pages(
    sess: requests.Session,
    url: str,
    endpoint_config: DagsterCloudEndpointConfig,
    variables: dict[str, Any],
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Walk a cursor-paginated list endpoint, yielding raw rows with the cursor that follows them.

    The cursor is handed back rather than checkpointed so the caller decides whether a page
    boundary is worth resume state — a parent walk replays from the start, a synced table does not.
    """
    variables = dict(variables)
    previous_cursor: str | None = variables.get("cursor")

    while True:
        payload = _execute_query(sess, url, endpoint_config.query, variables)
        extracted = _extract_rows(payload, endpoint_config)
        if extracted is None:
            return
        container, rows = extracted

        next_cursor: str | None = None
        # A short page means we've reached the end of the (optionally filtered) result set.
        if endpoint_config.cursor_mode is not None and len(rows) >= DAGSTER_CLOUD_PAGE_SIZE:
            raw_cursor = _read_next_cursor(container, rows, endpoint_config)
            next_cursor = str(raw_cursor) if raw_cursor else None

        yield rows, next_cursor
        if next_cursor is None:
            return
        # A cursor that repeats would replay the same page forever, since nothing else bounds
        # this walk.
        if next_cursor == previous_cursor:
            raise Exception(f"Dagster Cloud {endpoint_config.name}: pagination cursor did not advance")
        previous_cursor = next_cursor
        variables["cursor"] = next_cursor


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

    variables: dict[str, Any] = {"limit": DAGSTER_CLOUD_PAGE_SIZE}
    if runs_filter is not None:
        variables["filter"] = runs_filter

    resume_config = resumable_source_manager.load_state()
    if resume_config is not None and resume_config.cursor:
        variables["cursor"] = resume_config.cursor
        logger.debug(f"Dagster Cloud: resuming {endpoint_name} from saved cursor")

    try:
        for rows, next_cursor in _iter_cursor_pages(sess, url, endpoint_config, variables):
            yield [_normalize_row(row, endpoint_config) for row in rows]

            # Checkpoint the next page to fetch AFTER yielding this one, so a crash re-fetches the
            # last page rather than skipping it — merge dedupes the overlap on primary_keys.
            if next_cursor is not None:
                resumable_source_manager.save_state(DagsterCloudResumeConfig(cursor=next_cursor))
    finally:
        sess.close()


def _iter_repository_parents(sess: requests.Session, url: str) -> Iterator[dict[str, Any]]:
    payload = _execute_query(sess, url, REPOSITORIES_PARENT_CONFIG.query, {})
    extracted = _extract_rows(payload, REPOSITORIES_PARENT_CONFIG)
    if extracted is None:
        return
    _, rows = extracted
    for row in rows:
        yield {
            "repositoryId": row.get("id"),
            "repositoryName": row.get("name"),
            "repositoryLocationName": (row.get("location") or {}).get("name"),
        }


def _iter_asset_parents(sess: requests.Session, url: str) -> Iterator[dict[str, Any]]:
    endpoint_config = DAGSTER_CLOUD_ENDPOINTS["assets"]
    for rows, _ in _iter_cursor_pages(sess, url, endpoint_config, {"limit": DAGSTER_CLOUD_PAGE_SIZE}):
        for row in rows:
            path = (row.get("key") or {}).get("path") or []
            yield {"assetId": row.get("id"), "assetKeyPath": path, "assetKeyInput": {"path": path}}


def _iter_instigation_state_parents(sess: requests.Session, url: str) -> Iterator[dict[str, Any]]:
    endpoint_config = DAGSTER_CLOUD_ENDPOINTS["instigation_states"]
    for repository in _iter_repository_parents(sess, url):
        payload = _execute_query(sess, url, endpoint_config.query, {"repositoryID": repository["repositoryId"]})
        extracted = _extract_rows(payload, endpoint_config)
        if extracted is None:
            continue
        _, rows = extracted
        for row in rows:
            yield {
                "repositoryName": row.get("repositoryName") or repository["repositoryName"],
                "repositoryLocationName": row.get("repositoryLocationName") or repository["repositoryLocationName"],
                "instigationName": row.get("name"),
                "instigationStateId": row.get("id"),
                "instigationSelectorId": row.get("selectorId"),
            }


def _iter_parents(sess: requests.Session, url: str, fan_out: DagsterCloudFanOutConfig) -> Iterator[dict[str, Any]]:
    if fan_out.parent_kind == "repositories":
        yield from _iter_repository_parents(sess, url)
    elif fan_out.parent_kind == "assets":
        yield from _iter_asset_parents(sess, url)
    else:
        yield from _iter_instigation_state_parents(sess, url)


def _window_from_epoch_seconds(seconds: float, unit: WindowUnit | None) -> str | float:
    return str(int(seconds * 1000)) if unit == "millis_string" else seconds


def _window_to_wire(value: str, unit: WindowUnit | None) -> str | float:
    return value if unit == "millis_string" else float(value)


def _oldest_window_value(rows: list[dict[str, Any]], fan_out: DagsterCloudFanOutConfig) -> str | None:
    """The oldest window value on a page, which bounds the next (older) page.

    Dagster applies these bounds strictly (`timestamp < before`), so paging on the page's minimum
    neither re-reads it nor skips past it — with the one exception of events sharing that exact
    instant across a page boundary, which the API gives no way to disambiguate.
    """
    assert fan_out.window_row_field is not None
    values = [row.get(fan_out.window_row_field) for row in rows]
    present = [value for value in values if value is not None]
    if not present:
        return None
    try:
        if fan_out.window_unit == "millis_string":
            return str(min(int(value) for value in present))
        return str(min(float(value) for value in present))
    except (TypeError, ValueError):
        return None


def _inject_parent_fields(
    row: dict[str, Any], parent: dict[str, Any], fan_out: DagsterCloudFanOutConfig
) -> dict[str, Any]:
    if not fan_out.include_from_parent:
        return row
    enriched = dict(row)
    for parent_key in fan_out.include_from_parent:
        enriched[parent_key] = parent.get(parent_key)
    return enriched


def _iter_child_pages(
    sess: requests.Session,
    url: str,
    endpoint_config: DagsterCloudEndpointConfig,
    parent: dict[str, Any],
    watermark_epoch: float | None,
    start_window: str,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Yield one parent's child rows, page by page, with the window bound that follows each page."""
    fan_out = endpoint_config.fan_out
    assert fan_out is not None

    before_variable = fan_out.before_variable

    variables: dict[str, Any] = {"limit": DAGSTER_CLOUD_PAGE_SIZE}
    for variable_name, parent_key in fan_out.parent_variables.items():
        variables[variable_name] = parent.get(parent_key)
    if fan_out.after_variable is not None and watermark_epoch is not None:
        variables[fan_out.after_variable] = _window_from_epoch_seconds(watermark_epoch, fan_out.window_unit)
    if before_variable is not None and start_window:
        variables[before_variable] = _window_to_wire(start_window, fan_out.window_unit)

    previous_window = start_window

    while True:
        payload = _execute_query(sess, url, endpoint_config.query, variables)
        extracted = _extract_rows(payload, endpoint_config)
        if extracted is None:
            return
        _, rows = extracted

        next_window: str | None = None
        if before_variable is not None and len(rows) >= DAGSTER_CLOUD_PAGE_SIZE:
            next_window = _oldest_window_value(rows, fan_out)

        yield (
            [_inject_parent_fields(_normalize_row(row, endpoint_config), parent, fan_out) for row in rows],
            next_window,
        )

        if next_window is None or before_variable is None:
            return
        # The walk is otherwise unbounded, and only a strictly older bound guarantees it ends.
        # Truncating a parent instead would be silent data loss: sort_mode is "desc", so the
        # watermark commits at the top of this parent's history and the skipped events below it
        # would never be requested again.
        if next_window == previous_window:
            raise Exception(f"Dagster Cloud {endpoint_config.name}: page window did not advance past {next_window}")
        previous_window = next_window
        variables[before_variable] = _window_to_wire(next_window, fan_out.window_unit)


def _fetch_parent_batch(
    sess: requests.Session,
    url: str,
    endpoint_config: DagsterCloudEndpointConfig,
    batch: list[dict[str, Any]],
) -> Iterator[list[dict[str, Any]]]:
    fan_out = endpoint_config.fan_out
    assert fan_out is not None and fan_out.batch_variable is not None and fan_out.batch_field is not None

    variables = {fan_out.batch_variable: [parent.get(fan_out.batch_field) for parent in batch]}
    payload = _execute_query(sess, url, endpoint_config.query, variables)
    extracted = _extract_rows(payload, endpoint_config)
    if extracted is None:
        return
    _, rows = extracted
    yield [_normalize_row(row, endpoint_config) for row in rows]


def _iter_fanout_rows(
    sess: requests.Session,
    url: str,
    endpoint_config: DagsterCloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DagsterCloudResumeConfig],
    resume_config: DagsterCloudResumeConfig | None,
    watermark_epoch: float | None,
) -> Iterator[list[dict[str, Any]]]:
    fan_out = endpoint_config.fan_out
    assert fan_out is not None

    parents_done = resume_config.parents_done if resume_config else 0
    start_window = resume_config.window_cursor if resume_config else ""
    if parents_done or start_window:
        logger.debug(f"Dagster Cloud: resuming {endpoint_config.name} after {parents_done} parents")

    # Kept live past the loop so a trailing partial batch can checkpoint the parents it covered.
    index = parents_done - 1
    batch: list[dict[str, Any]] = []

    for index, parent in enumerate(_iter_parents(sess, url, fan_out)):
        if index < parents_done:
            continue

        if fan_out.batch_variable is not None:
            batch.append(parent)
            if len(batch) >= fan_out.batch_size:
                yield from _fetch_parent_batch(sess, url, endpoint_config, batch)
                resumable_source_manager.save_state(DagsterCloudResumeConfig(parents_done=index + 1))
                batch = []
            continue

        # Only the parent the saved state stopped inside resumes mid-window; the ones after it
        # start from their newest event.
        window = start_window if index == parents_done else ""
        for page, next_window in _iter_child_pages(sess, url, endpoint_config, parent, watermark_epoch, window):
            yield page
            # Save after yielding, so a crash re-reads the last page instead of skipping it.
            if next_window is not None:
                resumable_source_manager.save_state(
                    DagsterCloudResumeConfig(parents_done=index, window_cursor=next_window)
                )
        resumable_source_manager.save_state(DagsterCloudResumeConfig(parents_done=index + 1))

    if batch:
        yield from _fetch_parent_batch(sess, url, endpoint_config, batch)
        resumable_source_manager.save_state(DagsterCloudResumeConfig(parents_done=index + 1))


def _make_fanout_request(
    organization: str,
    deployment: str,
    api_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DagsterCloudResumeConfig],
    watermark_epoch: float | None = None,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = DAGSTER_CLOUD_ENDPOINTS.get(endpoint_name)
    if not endpoint_config or endpoint_config.fan_out is None:
        raise ValueError(f"Unknown Dagster Cloud fan-out endpoint: {endpoint_name}")

    url = build_graphql_url(organization, deployment)
    sess = _make_session(api_token)
    resume_config = resumable_source_manager.load_state()

    try:
        yield from _iter_fanout_rows(
            sess, url, endpoint_config, logger, resumable_source_manager, resume_config, watermark_epoch
        )
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
        watermark_epoch = None
        if (
            endpoint_config.supports_incremental
            and should_use_incremental_field
            and db_incremental_field_last_value is not None
        ):
            watermark_epoch = _to_epoch_seconds(db_incremental_field_last_value)

        if endpoint_config.fan_out is not None:
            if watermark_epoch is not None:
                logger.debug(f"Dagster Cloud: incremental sync for {endpoint_name} after {watermark_epoch}")
            yield from _make_fanout_request(
                organization=organization,
                deployment=deployment,
                api_token=api_token,
                endpoint_name=endpoint_name,
                logger=logger,
                resumable_source_manager=resumable_source_manager,
                watermark_epoch=watermark_epoch,
            )
            return

        runs_filter = _build_runs_filter(incremental_field, watermark_epoch)
        if runs_filter is not None:
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
