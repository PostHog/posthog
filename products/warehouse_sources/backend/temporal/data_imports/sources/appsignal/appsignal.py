import dataclasses
from collections import deque
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, NoReturn, Optional
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.settings import (
    APPSIGNAL_ENDPOINTS,
    AppsignalEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import (
    redact_literal_values,
    scrub_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

APPSIGNAL_BASE_URL = "https://appsignal.com"
APPSIGNAL_GRAPHQL_URL = f"{APPSIGNAL_BASE_URL}/graphql"

# Row cap per windowed REST fetch. The Samples/Markers APIs have no cursor pagination — only
# `limit` plus time bounds — so windows holding more rows than this are bisected.
WINDOW_PAGE_LIMIT = 200
# Hard ceiling on a single fetch once a window can't be bisected further (1-second windows).
MAX_LEAF_LIMIT = 10_000
# Smallest leaf window a bisection can produce. A window must be at least twice this to split
# (see `_get_windowed_rows`); anything narrower is fetched directly even if it's over the page limit.
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
    # V2 log lines: timestamp of the last line yielded, the keyset cursor of the next page.
    cursor_time: str | None = None


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


def _raise_scrubbed_transport_error(error: requests.RequestException, api_token: str, context: str) -> NoReturn:
    """Re-raise a transport failure with the API token stripped from the message.

    requests' connection/timeout exceptions embed the full request URL — including the
    `?token=` credential — in their text. Left intact that lands in job logs and
    `latest_error`, so anyone able to view a failed import could recover the token.
    Convert to a retryable error whose message has the credential (and its URL-encoded
    forms) redacted; unlike `_raise_for_status_scrubbed`, this covers failures raised
    before any response exists.
    """
    scrubbed = redact_literal_values(str(error), [api_token])
    raise AppsignalRetryableError(f"AppSignal {context} transport error: {scrubbed}") from None


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
    try:
        response = session.get(
            url,
            params={**params, "token": api_token},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        _raise_scrubbed_transport_error(error, api_token, "API")

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
    try:
        response = session.post(
            APPSIGNAL_GRAPHQL_URL,
            params={"token": api_token},
            json={"query": query, "variables": variables},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        _raise_scrubbed_transport_error(error, api_token, "GraphQL")

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

        # Require at least 2 * MIN_WINDOW_SECONDS before splitting: the right child's `mid - 1`
        # overlap eats a second, so on a narrower window it would equal the parent and the walk
        # would spin forever. Below that, fetch directly even if the window is over the page limit.
        if count > WINDOW_PAGE_LIMIT and (window_before - window_since) >= 2 * MIN_WINDOW_SECONDS:
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


# --- Public API V2 (https://appsignal.com/api/v2) -----------------------------------------
# Logs, metrics and traces are only served by V2; the legacy /api/{app_id}/*.json endpoints
# above do not expose them, and the GraphQL metrics API is deprecated.
APPSIGNAL_V2_URL = f"{APPSIGNAL_BASE_URL}/api/v2"
# Documented ceiling on `pagination.per_page` for the V2 list endpoints.
V2_PAGE_SIZE = 100
# Resolution the metric buckets are requested at. Pinning it keeps bucket timestamps stable
# between syncs, so a re-read of the same range merges onto the same rows instead of seeding
# a second set at a different granularity.
METRICS_RESOLUTION = "HOURLY"
METRICS_RESOLUTION_SECONDS = 3600
METRICS_WINDOW_SECONDS = 7 * 24 * 3600
# Selectors sent per timeseries request. One request can ask for many metrics at once, which
# keeps the request count proportional to the time range rather than to the metric count.
METRICS_SELECTORS_PER_REQUEST = 25
# How far back a first metrics or traces sync reaches. Neither endpoint reports the account's
# retention bound, and both clamp `from` to it server side, so the walk needs a lower bound of
# its own instead of the EARLIEST_START used for the legacy endpoints.
METRICS_INITIAL_LOOKBACK_SECONDS = 30 * 24 * 3600
TRACES_INITIAL_LOOKBACK_SECONDS = 7 * 24 * 3600
TRACES_WINDOW_SECONDS = 6 * 3600
# Traces whose spans are fetched in one sync. Spans cost one request per trace, so a first
# sync on a busy app is capped and the next sync continues from the watermark.
MAX_SPAN_TRACES_PER_SYNC = 5_000
SPAN_BATCH_TRACES = 100
# AppSignal's metric types map onto the `Field` enum the timeseries selector asks for. A
# measurement has no single natural field, so the mean is taken as the representative one.
METRIC_TYPE_FIELDS = {"gauge": "gauge", "counter": "counter", "measurement": "mean"}


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _format_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _to_iso(epoch: int) -> str:
    return _format_iso(datetime.fromtimestamp(epoch, tz=UTC))


def _iter_windows(start: int, end: int, size: int) -> Iterator[tuple[int, int]]:
    while start < end:
        stop = min(start + size, end)
        yield start, stop
        start = stop


def _resolve_walk_start(
    config: AppsignalEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    logger: FilteringBoundLogger,
    now: int,
    initial_lookback_seconds: int,
    overlap_seconds: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> int:
    start = now - initial_lookback_seconds
    if should_use_incremental_field:
        watermark = _to_epoch(db_incremental_field_last_value)
        if watermark is not None:
            start = watermark - overlap_seconds

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start is not None:
        start = resume.window_start
        logger.debug(f"AppSignal: resuming {config.name} from window_start={start}")

    return start


@retry(
    retry=retry_if_exception_type((AppsignalRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_v2(
    session: requests.Session,
    api_token: str,
    path: str,
    logger: FilteringBoundLogger,
    body: Optional[dict[str, Any]] = None,
) -> Any:
    """Call a Public API V2 endpoint. A body means POST, no body means GET.

    Returns the decoded body as-is: the V2 endpoints answer with a bare JSON array as often as
    with an object, so the caller decides how to read it.
    """
    url = f"{APPSIGNAL_V2_URL}{path}"
    try:
        if body is None:
            response = session.get(url, params={"token": api_token}, timeout=REQUEST_TIMEOUT_SECONDS)
        else:
            response = session.post(url, params={"token": api_token}, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        _raise_scrubbed_transport_error(error, api_token, "V2 API")

    if response.status_code == 429 or response.status_code >= 500:
        raise AppsignalRetryableError(f"AppSignal V2 API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"AppSignal V2 API error: status={response.status_code}, path={path}")
        _raise_for_status_scrubbed(response)

    return response.json()


_APPS_QUERY = """
query OrganizationApps {
  viewer {
    organizations {
      id
      name
      slug
      apps {
        id
        name
        environment
        platforms
        languages
        status
        lastPushProcessedAt
        createdAt
        updatedAt
      }
    }
  }
}
"""

_LOG_SOURCES_QUERY = """
query LogSources($appId: String!) {
  app(id: $appId) {
    logs {
      sources {
        id
      }
    }
  }
}
"""


def _get_app_rows(
    session: requests.Session,
    api_token: str,
    app_id: str,
    config: AppsignalEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    body = _fetch_graphql(session, api_token, _APPS_QUERY, {}, logger)
    organizations = ((body.get("data") or {}).get("viewer") or {}).get("organizations") or []

    rows = [
        {
            **app,
            "organizationId": organization.get("id"),
            "organizationName": organization.get("name"),
            "organizationSlug": organization.get("slug"),
        }
        for organization in organizations
        for app in organization.get("apps") or []
        if isinstance(app, dict)
    ]
    if rows:
        yield rows


def _get_log_source_ids(
    session: requests.Session,
    api_token: str,
    app_id: str,
    logger: FilteringBoundLogger,
) -> list[str]:
    body = _fetch_graphql(session, api_token, _LOG_SOURCES_QUERY, {"appId": app_id}, logger)
    app = (body.get("data") or {}).get("app")
    if app is None:
        raise Exception("AppSignal app not found: check that the app ID matches your AppSignal app")

    sources = ((app.get("logs") or {}).get("sources")) or []
    return [source["id"] for source in sources if isinstance(source, dict) and source.get("id")]


def _get_log_line_rows(
    session: requests.Session,
    api_token: str,
    app_id: str,
    config: AppsignalEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk log lines oldest-first through the V2 keyset cursor.

    The cursor is the timestamp of the last line received, and the endpoint includes that
    instant, so lines sharing it come back on the next page. They are filtered against the ids
    already yielded, and the cursor only ever moves forward: a page ending on or before the
    cursor cannot advance the walk on its own.
    """
    source_ids = _get_log_source_ids(session, api_token, app_id, logger)
    if not source_ids:
        logger.info("AppSignal: app has no log sources, nothing to sync")
        return

    # No cursor asks for the oldest page the account's retention still holds.
    cursor: Optional[datetime] = None
    if should_use_incremental_field:
        watermark = _to_epoch(db_incremental_field_last_value)
        if watermark is not None:
            cursor = datetime.fromtimestamp(watermark - 1, tz=UTC)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.cursor_time is not None:
        cursor = _parse_iso(resume.cursor_time)
        logger.debug(f"AppSignal: resuming {config.name} from cursor_time={resume.cursor_time}")

    # Ids already yielded at `cursor`, so that instant can be re-requested without duplicating.
    seen_at_cursor: set[str] = set()

    while True:
        page = _fetch_v2(
            session,
            api_token,
            "/logs/lines",
            logger,
            body={
                "site_id": app_id,
                "source_ids": source_ids,
                "query": "",
                "pagination": {
                    "per_page": V2_PAGE_SIZE,
                    "order": "ASC",
                    "cursor": {"time": _format_iso(cursor) if cursor is not None else None},
                },
            },
        )
        rows = [row for row in page or [] if isinstance(row, dict)]
        if not rows:
            break

        fresh = [row for row in rows if row.get("id") not in seen_at_cursor]
        if fresh:
            yield fresh

        last = _parse_iso(rows[-1].get("timestamp"))
        if last is None:
            break

        if cursor is None or last > cursor:
            cursor = last
            seen_at_cursor = {row["id"] for row in rows if _parse_iso(row.get("timestamp")) == last and row.get("id")}
            if fresh:
                # Save AFTER yielding so a crash re-yields the last page rather than skipping it.
                resumable_source_manager.save_state(AppsignalResumeConfig(cursor_time=_format_iso(cursor)))
            if len(rows) < V2_PAGE_SIZE:
                break
            continue

        if len(rows) < V2_PAGE_SIZE:
            break

        # A whole page landed on or before the cursor, so the keyset cursor cannot advance by
        # itself and re-requesting would loop. Step past that instant instead; anything beyond a
        # page at that exact timestamp cannot be reached through this API.
        logger.warning(
            f"AppSignal: more than {V2_PAGE_SIZE} log lines share timestamp {_format_iso(cursor)}, "
            f"skipping the rest of that instant"
        )
        cursor = cursor + timedelta(milliseconds=1)
        seen_at_cursor |= {row["id"] for row in rows if row.get("id")}


def _iter_metric_definitions(
    session: requests.Session,
    api_token: str,
    app_id: str,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    names = _fetch_v2(session, api_token, f"/metrics/names/{quote(app_id, safe='')}", logger)
    for name in names or []:
        if not isinstance(name, str):
            continue
        try:
            detail = _fetch_v2(
                session,
                api_token,
                f"/metrics/type_and_tags/{quote(app_id, safe='')}/{quote(name, safe='')}",
                logger,
            )
        except requests.HTTPError as error:
            # Documented 404: the metric stopped reporting between the two calls.
            if error.response is None or error.response.status_code != 404:
                raise
            detail = {}
        yield {
            "name": name,
            "metric_type": detail.get("metric_type"),
            "available_tags": detail.get("available_tags") or [],
        }


def _get_metric_name_rows(
    session: requests.Session,
    api_token: str,
    app_id: str,
    config: AppsignalEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    rows = list(_iter_metric_definitions(session, api_token, app_id, logger))
    if rows:
        yield rows


def _selector_tags(available_tags: Any) -> dict[str, str]:
    """Build a tag filter that matches every series of a metric.

    `available_tags` is documented both as a list of tag-key lists and, in the example
    response, as a list of tag key/value objects. Both are read as the set of tag keys, and
    each key is matched with the API's `*` wildcard so no series is filtered out.
    """
    keys: set[str] = set()
    for combination in available_tags or []:
        if isinstance(combination, dict):
            keys.update(key for key in combination if isinstance(key, str))
        elif isinstance(combination, list):
            keys.update(key for key in combination if isinstance(key, str))
    return dict.fromkeys(sorted(keys), "*")


def _get_metric_timeseries_rows(
    session: requests.Session,
    api_token: str,
    app_id: str,
    config: AppsignalEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk every metric's buckets through ascending time windows.

    Windows are the outer loop and metrics the inner one, so each yielded batch covers one
    window and batches arrive oldest-first. That keeps `sort_mode="asc"` watermarking honest,
    which per-metric walks would not: their timestamps restart with every metric.
    """
    selectors = []
    for definition in _iter_metric_definitions(session, api_token, app_id, logger):
        field_name = METRIC_TYPE_FIELDS.get(definition["metric_type"] or "")
        if field_name is None:
            continue
        selectors.append(
            {"name": definition["name"], "field": field_name, "tags": _selector_tags(definition["available_tags"])}
        )
    if not selectors:
        return

    now = int(datetime.now(UTC).timestamp())
    start = _resolve_walk_start(
        config,
        resumable_source_manager,
        logger,
        now,
        METRICS_INITIAL_LOOKBACK_SECONDS,
        # Re-read the bucket the watermark sits in: it was still filling when it was synced,
        # and the merge replaces it with the settled value.
        METRICS_RESOLUTION_SECONDS,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )

    for window_since, window_before in _iter_windows(start, now, METRICS_WINDOW_SECONDS):
        rows: list[dict[str, Any]] = []
        for offset in range(0, len(selectors), METRICS_SELECTORS_PER_REQUEST):
            body = _fetch_v2(
                session,
                api_token,
                "/metrics/timeseries",
                logger,
                body={
                    "site_id": app_id,
                    "from": _to_iso(window_since),
                    "to": _to_iso(window_before),
                    "resolution": METRICS_RESOLUTION,
                    "select": selectors[offset : offset + METRICS_SELECTORS_PER_REQUEST],
                },
            )
            for serie in (body or {}).get("series") or []:
                for point in serie.get("data") or []:
                    rows.append(
                        {
                            "series_id": serie.get("id"),
                            "metric_name": serie.get("name"),
                            "field": serie.get("field"),
                            "tags": serie.get("tags"),
                            "timestamp": point.get("timestamp"),
                            "value": point.get("value"),
                        }
                    )

        if not rows:
            continue

        rows.sort(key=lambda row: _to_epoch(row.get("timestamp")) or 0)
        yield rows
        resumable_source_manager.save_state(AppsignalResumeConfig(window_start=window_before))


def _iter_action_traces(
    session: requests.Session,
    api_token: str,
    app_id: str,
    namespace: str,
    action_name: str,
    since: int,
    before: int,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """Sweep one action's traces by splitting the window whenever a response comes back full.

    `traces/performance` caps a response at `per_page` and its cursor only names the keyset
    column, so a full response means the window was truncated rather than exhausted. Halving
    the window is the only way to reach the rest.
    """
    windows: deque[tuple[int, int]] = deque([(since, before)])
    while windows:
        window_since, window_before = windows.popleft()
        rows = (
            _fetch_v2(
                session,
                api_token,
                "/tracing/traces/performance",
                logger,
                body={
                    "site_ids": [app_id],
                    "namespace": namespace,
                    "action_name": action_name,
                    "from": _to_iso(window_since),
                    "to": _to_iso(window_before),
                    "pagination": {"per_page": V2_PAGE_SIZE, "order": "ASC", "cursor": "Time"},
                },
            )
            or []
        )
        rows = [row for row in rows if isinstance(row, dict)]

        if len(rows) >= V2_PAGE_SIZE and (window_before - window_since) >= 2 * MIN_WINDOW_SECONDS:
            mid = (window_since + window_before) // 2
            # The right child starts 1s early so a trace landing exactly on `mid` cannot fall
            # between the halves if both bounds turn out exclusive. Dupes merge away.
            windows.appendleft((max(mid - 1, window_since), window_before))
            windows.appendleft((window_since, mid))
            continue

        if len(rows) >= V2_PAGE_SIZE:
            logger.warning(
                f"AppSignal: more than {V2_PAGE_SIZE} traces for {namespace}/{action_name} within "
                f"[{window_since}, {window_before}], which is narrower than the walk can split"
            )

        yield from rows


def _window_traces(
    session: requests.Session,
    api_token: str,
    app_id: str,
    since: int,
    before: int,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """Collect every trace recorded in a window, oldest-first.

    Traces are only reachable one action at a time, so the window's actions are swept first
    and the result is sorted: rows arrive grouped by action, which is not a time order.
    """
    actions = (
        _fetch_v2(
            session,
            api_token,
            "/tracing/actions",
            logger,
            body={"site_id": app_id, "from": _to_iso(since), "to": _to_iso(before)},
        )
        or []
    )

    traces: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        namespace, action_name = action.get("namespace"), action.get("action")
        if not namespace or not action_name:
            continue
        traces.extend(_iter_action_traces(session, api_token, app_id, namespace, action_name, since, before, logger))

    traces.sort(key=lambda trace: _to_epoch(trace.get("time")) or 0)
    return traces


def _get_performance_trace_rows(
    session: requests.Session,
    api_token: str,
    app_id: str,
    config: AppsignalEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    now = int(datetime.now(UTC).timestamp())
    start = _resolve_walk_start(
        config,
        resumable_source_manager,
        logger,
        now,
        TRACES_INITIAL_LOOKBACK_SECONDS,
        1,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )

    for window_since, window_before in _iter_windows(start, now, TRACES_WINDOW_SECONDS):
        traces = _window_traces(session, api_token, app_id, window_since, window_before, logger)
        if not traces:
            continue
        yield traces
        resumable_source_manager.save_state(AppsignalResumeConfig(window_start=window_before))


def _get_trace_span_rows(
    session: requests.Session,
    api_token: str,
    app_id: str,
    config: AppsignalEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    """Fan spans out per trace, oldest trace first.

    Spans cost one request per trace, so the sweep stops at MAX_SPAN_TRACES_PER_SYNC. Stopping
    is safe because traces are processed in ascending `time` order: the watermark lands on the
    last trace handled and the next sync picks up from there.
    """
    now = int(datetime.now(UTC).timestamp())
    start = _resolve_walk_start(
        config,
        resumable_source_manager,
        logger,
        now,
        TRACES_INITIAL_LOOKBACK_SECONDS,
        1,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )

    traces_fetched = 0
    for window_since, window_before in _iter_windows(start, now, TRACES_WINDOW_SECONDS):
        spans: list[dict[str, Any]] = []
        batch_traces = 0
        capped = False
        last_trace_time: Any = None

        for trace in _window_traces(session, api_token, app_id, window_since, window_before, logger):
            trace_id, trace_time = trace.get("trace_id"), trace.get("time")
            if not trace_id:
                continue
            if traces_fetched >= MAX_SPAN_TRACES_PER_SYNC:
                logger.warning(
                    f"AppSignal: reached the {MAX_SPAN_TRACES_PER_SYNC} trace limit for {config.name}, "
                    f"the next sync continues from the last trace handled"
                )
                capped = True
                break

            traces_fetched += 1
            batch_traces += 1
            last_trace_time = trace_time
            rows = _fetch_v2(
                session,
                api_token,
                "/tracing/trace",
                logger,
                body={"site_ids": [app_id], "trace_id": trace_id},
            )
            spans.extend({**row, "trace_time": trace_time} for row in rows or [] if isinstance(row, dict))

            if batch_traces >= SPAN_BATCH_TRACES:
                yield spans
                resumable_source_manager.save_state(
                    AppsignalResumeConfig(window_start=_to_epoch(trace_time) or window_since)
                )
                spans, batch_traces = [], 0

        if spans:
            yield spans
        if capped:
            resumable_source_manager.save_state(
                AppsignalResumeConfig(window_start=_to_epoch(last_trace_time) or window_since)
            )
            return
        resumable_source_manager.save_state(AppsignalResumeConfig(window_start=window_before))


_WALKERS = {
    "apps": _get_app_rows,
    "log_lines": _get_log_line_rows,
    "metric_names": _get_metric_name_rows,
    "metric_timeseries": _get_metric_timeseries_rows,
    "performance_traces": _get_performance_trace_rows,
    "trace_spans": _get_trace_span_rows,
}


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

    if config.api == "custom":
        assert config.walker is not None
        yield from _WALKERS[config.walker](
            session,
            api_token,
            app_id,
            config,
            resumable_source_manager,
            logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
        return

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
        primary_keys=list(config.primary_keys),
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
