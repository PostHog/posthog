import dataclasses
from collections import deque
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.settings import (
    APPSIGNAL_ENDPOINTS,
    AppsignalEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import scrub_url
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

APPSIGNAL_BASE_URL = "https://appsignal.com"
APPSIGNAL_GRAPHQL_URL = f"{APPSIGNAL_BASE_URL}/graphql"

# Row cap per windowed REST fetch. The Samples/Markers APIs have no cursor pagination — only
# `limit` plus time bounds — so windows holding more rows than this are bisected.
WINDOW_PAGE_LIMIT = 200
# Hard ceiling on a single fetch once a window can't be bisected further (1-second windows).
MAX_LEAF_LIMIT = 10_000
# Windows narrower than this are fetched directly instead of split again.
MIN_WINDOW_SECONDS = 2
GRAPHQL_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Default lower time bound for full-history walks — predates AppSignal's founding, and the
# window bisection skips empty ranges in O(log) count probes.
EARLIEST_START = int(datetime(2010, 1, 1, tzinfo=UTC).timestamp())


class AppsignalRetryableError(Exception):
    pass


@dataclasses.dataclass
class AppsignalResumeConfig:
    # REST windowed endpoints: epoch second the remaining walk starts from.
    window_start: int | None = None
    # GraphQL incident endpoints: offset of the next page to fetch.
    offset: int | None = None


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to UNIX epoch seconds.

    Samples carry `time` as an epoch integer; markers carry `created_at` as an ISO 8601
    string; persisted watermarks come back as ints or datetimes depending on the field type.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        return int(parsed.timestamp())
    return None


def _raise_for_status_scrubbed(response: requests.Response) -> None:
    """`raise_for_status` equivalent that never leaks the `token` query param.

    AppSignal authenticates via a `?token=` URL param, and requests' own HTTPError message
    embeds the full URL — which would surface the credential in job error messages and logs.
    """
    if response.ok:
        return
    kind = "Client Error" if response.status_code < 500 else "Server Error"
    raise requests.HTTPError(
        f"{response.status_code} {kind}: {response.reason} for url: {scrub_url(response.url or '')}",
        response=response,
    )


@retry(
    retry=retry_if_exception_type((AppsignalRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_json(
    session: requests.Session,
    api_token: str,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        url,
        params={**params, "token": api_token},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise AppsignalRetryableError(f"AppSignal API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"AppSignal API error: status={response.status_code}, url={scrub_url(response.url or url)}")
        _raise_for_status_scrubbed(response)

    return response.json()


@retry(
    retry=retry_if_exception_type((AppsignalRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_graphql(
    session: requests.Session,
    api_token: str,
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(
        APPSIGNAL_GRAPHQL_URL,
        params={"token": api_token},
        json={"query": query, "variables": variables},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise AppsignalRetryableError(f"AppSignal GraphQL error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"AppSignal GraphQL error: status={response.status_code}")
        _raise_for_status_scrubbed(response)

    body = response.json()
    if body.get("errors"):
        messages = "; ".join(str(error.get("message", error)) for error in body["errors"])
        raise Exception(f"AppSignal GraphQL query failed: {messages}")

    return body


def validate_credentials(api_token: str, app_id: str) -> bool:
    """One cheap probe that exercises both the personal token and the app ID."""
    try:
        response = make_tracked_session().get(
            f"{APPSIGNAL_BASE_URL}/api/{app_id}/markers.json",
            params={"token": api_token, "count_only": "true", "limit": "1"},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def _incident_query(config: AppsignalEndpointConfig) -> str:
    return (
        "query IncidentsList($appId: String!, $limit: Int, $offset: Int, $order: IncidentOrderEnum) {\n"
        "  app(id: $appId) {\n"
        f"    {config.graphql_field}(limit: $limit, offset: $offset, order: $order) {{\n"
        f"{config.graphql_selection}\n"
        "    }\n"
        "  }\n"
        "}"
    )


def _get_incident_rows(
    session: requests.Session,
    api_token: str,
    app_id: str,
    config: AppsignalEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    assert config.graphql_field is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None and resume.offset is not None else 0
    if offset:
        logger.debug(f"AppSignal: resuming {config.name} from offset={offset}")

    query = _incident_query(config)

    while True:
        body = _fetch_graphql(
            session,
            api_token,
            query,
            # order=ID keeps offset pages stable while incidents update mid-walk.
            {"appId": app_id, "limit": GRAPHQL_PAGE_SIZE, "offset": offset, "order": "ID"},
            logger,
        )
        app = (body.get("data") or {}).get("app")
        if app is None:
            raise Exception("AppSignal app not found: check that the app ID matches your AppSignal app")
        rows = app.get(config.graphql_field) or []
        if not rows:
            break

        yield rows
        offset += len(rows)

        if len(rows) < GRAPHQL_PAGE_SIZE:
            break
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it.
        resumable_source_manager.save_state(AppsignalResumeConfig(offset=offset))


def _window_count(
    session: requests.Session,
    api_token: str,
    url: str,
    config: AppsignalEndpointConfig,
    since: int,
    before: int,
    logger: FilteringBoundLogger,
) -> int:
    data = _fetch_json(
        session,
        api_token,
        url,
        {**config.extra_params, config.since_param: since, config.before_param: before, "count_only": "true"},
        logger,
    )
    return int(data.get("count") or 0)


def _window_rows(
    session: requests.Session,
    api_token: str,
    url: str,
    config: AppsignalEndpointConfig,
    since: int,
    before: int,
    limit: int,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    data = _fetch_json(
        session,
        api_token,
        url,
        {**config.extra_params, config.since_param: since, config.before_param: before, "limit": limit},
        logger,
    )
    rows = data.get(config.data_key or "", []) or []
    return [row for row in rows if isinstance(row, dict)]


def _get_windowed_rows(
    session: requests.Session,
    api_token: str,
    app_id: str,
    config: AppsignalEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk a legacy REST endpoint through ascending time windows.

    The Samples/Markers APIs only expose `limit` plus lower/upper time bounds — no cursor —
    and their sort order is undocumented. A `count_only` probe per window drives an
    order-agnostic bisection: windows holding more than WINDOW_PAGE_LIMIT rows split in half
    until each leaf fits in a single request. Leaves are yielded oldest-window-first with rows
    sorted ascending on the cursor field, so `sort_mode="asc"` watermark checkpointing holds.
    """
    # Bound to a local so the None-narrowing survives into the sort lambda below.
    cursor_field = config.cursor_field
    assert config.path is not None and cursor_field is not None

    url = f"{APPSIGNAL_BASE_URL}{config.path.format(app_id=app_id)}"
    now = int(datetime.now(UTC).timestamp())

    start = EARLIEST_START
    if should_use_incremental_field:
        watermark = _to_epoch(db_incremental_field_last_value)
        if watermark is not None:
            # 1-second overlap: the API's bound inclusivity is undocumented, so re-pull the
            # boundary second and let merge dedupe on the primary key.
            start = max(watermark - 1, EARLIEST_START)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start is not None:
        start = resume.window_start
        logger.debug(f"AppSignal: resuming {config.name} from window_start={start}")

    if start >= now:
        return

    windows: deque[tuple[int, int]] = deque([(start, now)])
    while windows:
        window_since, window_before = windows.popleft()
        count = _window_count(session, api_token, url, config, window_since, window_before, logger)
        if count == 0:
            continue

        if count > WINDOW_PAGE_LIMIT and (window_before - window_since) >= MIN_WINDOW_SECONDS:
            mid = (window_since + window_before) // 2
            # The right child starts 1s early: if both bounds turn out exclusive, a row landing
            # exactly on `mid` would otherwise fall between the halves. Dupes merge away.
            windows.appendleft((max(mid - 1, window_since), window_before))
            windows.appendleft((window_since, mid))
            continue

        limit = min(max(count, WINDOW_PAGE_LIMIT), MAX_LEAF_LIMIT)
        if count > MAX_LEAF_LIMIT:
            logger.warning(
                f"AppSignal: {config.name} window [{window_since}, {window_before}] holds {count} rows, "
                f"fetching only the first {MAX_LEAF_LIMIT}"
            )
        rows = _window_rows(session, api_token, url, config, window_since, window_before, limit, logger)
        if not rows:
            continue

        rows.sort(key=lambda row: _to_epoch(row.get(cursor_field)) or 0)
        yield rows

        # Save AFTER yielding: everything before the next pending window is now complete, so a
        # resumed attempt restarts the walk there and re-yields at most the last window.
        next_start = windows[0][0] if windows else window_before
        resumable_source_manager.save_state(AppsignalResumeConfig(window_start=next_start))


def get_rows(
    api_token: str,
    app_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APPSIGNAL_ENDPOINTS[endpoint]
    # One session reused across every request so urllib3 keeps the connection alive.
    session = make_tracked_session()

    if config.api == "graphql":
        yield from _get_incident_rows(session, api_token, app_id, config, resumable_source_manager, logger)
        return

    yield from _get_windowed_rows(
        session,
        api_token,
        app_id,
        config,
        resumable_source_manager,
        logger,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def appsignal_source(
    api_token: str,
    app_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = APPSIGNAL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            app_id=app_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
