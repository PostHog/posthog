import re
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.adjust.settings import (
    ADJUST_REPORTS,
    CATALOG_PRIMARY_KEYS,
    DEFAULT_LOOKBACK_DAYS,
    EVENTS_CATALOG,
    FILTER_TYPES,
    FILTERS_DATA,
    LINKS,
    PARTNERS,
    SUBLINKS,
)
from products.warehouse_sources.sources.sdk import (
    DEFAULT_RETRY,
    BoundedRetry,
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
)

ADJUST_API_HOST = "automate.adjust.com"
BASE_URL = f"https://{ADJUST_API_HOST}/reports-service"
REPORT_URL = f"{BASE_URL}/report"
EVENTS_URL = f"{BASE_URL}/events"
FILTERS_DATA_URL = f"{BASE_URL}/filters_data"
# Links, sublinks and partners come from the Campaign API, which takes the same API token.
CAMPAIGN_API_HOST = "api.adjust.com"
CAMPAIGN_API_URL = f"https://{CAMPAIGN_API_HOST}/public/v2"

# Reports are pulled one date window at a time so a long backfill streams instead of asking Adjust
# for years of rows in a single response. The window is also the resume unit.
WINDOW_DAYS = 30
# First sync backfill depth. Adjust does not retain report data indefinitely, so anything older
# than this is unlikely to be available anyway.
MAX_HISTORY_DAYS = 730
REQUEST_TIMEOUT_SECONDS = 300
# The Report Service API documents a `pagination` field but not its mechanism, so the page loop is
# driven purely by a next link when one is present. The cap stops a malformed/looping link from
# scanning forever.
MAX_PAGES_PER_WINDOW = 200
# The Campaign API pages 50 items at a time; the cap stops a looping cursor from scanning forever.
MAX_CAMPAIGN_API_PAGES = 1000
MAX_LINK_DEPTH = 4
# Event reports request one metric per event slug; batching keeps the query string short for
# accounts with large event catalogs.
MAX_EVENT_METRICS_PER_REQUEST = 50
# Adjust app and link tokens are short alphanumeric identifiers; reject anything else before it
# reaches a query string or a URL path.
_APP_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# During a Report Service incident, Adjust answers some requests with a 403 while the same token
# keeps working on the requests around it. A 403 is non-retryable and disables the schema, so the
# sync retries it first. The waits (0, 10 and 20 seconds) spread the tries past a short burst of
# 403s. A 403 that persists through the retries is real lost access, and it still reaches
# `_get_json` and disables the schema. The credential probe keeps the default policy so that a bad
# token fails fast in the source setup form.
SYNC_RETRY = BoundedRetry(
    total=DEFAULT_RETRY.total,
    backoff_factor=5,
    status_forcelist=(403, *DEFAULT_RETRY.status_forcelist),
    allowed_methods=DEFAULT_RETRY.allowed_methods,
    raise_on_status=False,
)


class AdjustRetryableError(Exception):
    """Transient upstream failure (408 / 429 / 5xx) that survived the tracked session's own retries."""

    pass


class AdjustPageCapError(Exception):
    """A Campaign API collection kept advertising a next page past the page cap."""

    pass


class AdjustCredentialsError(Exception):
    """A credential check failed for a reason we can explain to the user (bad token, bad app token)."""

    pass


@dataclasses.dataclass(frozen=False)
class AdjustResumeConfig:
    # ISO date (YYYY-MM-DD) of the next date window to request. Lets a multi-window backfill pick up
    # where it stopped after a heartbeat timeout instead of re-walking the whole history.
    next_start_date: str | None = None


def _today() -> date:
    return datetime.now(UTC).date()


def _get_session(api_token: str, retry: BoundedRetry | None = None) -> requests.Session:
    return make_tracked_session(
        retry=retry,
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        redact_values=(api_token,),
        # The Bearer token rides in every request's default headers, so pin the session off
        # redirects — an upstream redirect must not carry the credential to another host.
        allow_redirects=False,
    )


def parse_app_tokens(app_tokens: str | None) -> list[str]:
    """Split the optional comma-separated app token filter, rejecting anything malformed.

    Raises ``AdjustCredentialsError`` rather than silently dropping a bad entry — a typo'd token
    would otherwise quietly narrow (or widen) the report to the wrong set of apps.
    """
    if not app_tokens:
        return []
    tokens = [token.strip() for token in app_tokens.split(",")]
    tokens = [token for token in tokens if token]
    for token in tokens:
        if not _APP_TOKEN_RE.fullmatch(token):
            raise AdjustCredentialsError(
                f"'{token}' does not look like an Adjust app token. App tokens are the short "
                "alphanumeric identifiers shown under your app's settings in the Adjust dashboard."
            )
    return tokens


def build_report_params(
    report: str,
    start: date,
    end: date,
    app_tokens: list[str],
    metrics: list[str] | None = None,
) -> dict[str, str]:
    config = ADJUST_REPORTS[report]
    params = {
        "dimensions": ",".join(config.dimensions),
        "metrics": ",".join(config.metrics if metrics is None else metrics),
        "date_period": f"{start.isoformat()}:{end.isoformat()}",
        # Ascending by day so the rows arrive in the order `sort_mode="asc"` promises and the
        # incremental watermark only ever moves forward.
        "sort": "day",
    }
    if app_tokens:
        params["app_token__in"] = ",".join(app_tokens)
    return params


def _error_message(response: requests.Response) -> str:
    """Best-effort human-readable detail from an Adjust error body."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or error.get("detail")
    else:
        detail = error
    detail = detail or body.get("message") or body.get("detail")
    return f" — {detail}" if isinstance(detail, str) and detail else ""


def _get_json(session: requests.Session, url: str, logger: FilteringBoundLogger) -> Any:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # 408 is a transient request timeout on Adjust's side; retry it like 429/5xx rather than
    # treating it as a bad request the client sent.
    if response.status_code in (408, 429) or response.status_code >= 500:
        raise AdjustRetryableError(f"Adjust API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Adjust API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        # The API token rides in the Authorization header, so the URL is safe to embed — it lets
        # `get_non_retryable_errors()` match on the stable host prefix.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {url}{_error_message(response)}",
            response=response,
        )

    if response.status_code == 204:
        return None
    return response.json()


def _request(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    body = _get_json(session, url, logger)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ValueError(f"Adjust returned an unexpected report payload of type {type(body).__name__}")
    return body


def fetch_events(
    session: requests.Session, app_tokens: list[str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    params = {"tokens_mapping": "true"}
    if app_tokens:
        params["app_token__in"] = ",".join(app_tokens)
    body = _get_json(session, f"{EVENTS_URL}?{urlencode(params)}", logger)
    if body is None:
        return []
    if not isinstance(body, list):
        raise ValueError(f"Adjust returned an unexpected events payload of type {type(body).__name__}")
    return [event for event in body if isinstance(event, dict)]


def report_event_names(events: list[dict[str, Any]]) -> dict[str, str | None]:
    """Map each event slug that can be requested as a `{slug}_events` metric to its readable name.

    SKAdNetwork events are reported through the SKAN conversion metrics, not as event counts.
    """
    names: dict[str, str | None] = {}
    for event in events:
        slug = event.get("id")
        if isinstance(slug, str) and slug and not event.get("is_skad_event"):
            name = event.get("name")
            names[slug] = name if isinstance(name, str) else None
    return names


def _is_zero(value: Any) -> bool:
    try:
        return float(value) == 0
    except (TypeError, ValueError):
        return False


def unpivot_event_rows(
    rows: list[dict[str, Any]],
    dimensions: list[str],
    event_names: dict[str, str | None],
) -> list[dict[str, Any]]:
    """Turn one column per event into one row per (dimensions, event).

    Zero counts are dropped: Adjust returns a value for every requested event on every row, and
    most events don't fire for most partners on most days.
    """
    unpivoted: list[dict[str, Any]] = []
    for row in rows:
        base = {dimension: row.get(dimension) for dimension in dimensions}
        for slug, name in event_names.items():
            value = row.get(f"{slug}_events")
            if value is None or _is_zero(value):
                continue
            unpivoted.append({**base, "event_slug": slug, "event_name": name, "events": value})
    return unpivoted


def extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the report rows out of a Report Service response.

    Adjust returns them under `rows`; tolerate a `data` list too, since the CSV/pivot variants of
    the same endpoint have historically wrapped rows differently.
    """
    for key in ("rows", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def next_page_url(payload: dict[str, Any]) -> str | None:
    """Return the absolute next-page URL, if the response advertises one.

    The `pagination` field is present but undocumented, so only an explicit link is followed —
    anything else terminates the page loop rather than guessing an offset scheme. The link is
    pinned to HTTPS on the Adjust API host: `_request` fetches it with the session whose default
    headers carry the customer's Bearer token, so a tampered upstream `next` must not be able to
    point the credentialed request at an attacker-controlled or internal host.
    """
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict):
        return None
    return _pinned_url(pagination.get("next") or pagination.get("next_url"), ADJUST_API_HOST)


def campaign_api_next_url(data: dict[str, Any]) -> str | None:
    """Return the Campaign API's `paging.next` link, pinned to HTTPS on the Campaign API host."""
    paging = data.get("paging")
    if not isinstance(paging, dict):
        return None
    return _pinned_url(paging.get("next"), CAMPAIGN_API_HOST)


def _pinned_url(candidate: Any, host: str) -> str | None:
    if not isinstance(candidate, str) or not candidate:
        return None
    # Parsers disagree on backslashes, whitespace and userinfo, so a link that holds any of them
    # could reach a different host than the one checked here.
    if "\\" in candidate or any(char.isspace() or ord(char) < 0x20 for char in candidate):
        return None
    try:
        parts = urlsplit(candidate)
        if parts.scheme != "https" or parts.hostname != host or parts.username is not None or parts.port is not None:
            return None
    except ValueError:
        return None
    return parts.geturl()


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19].replace("Z", "")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def resolve_start_date(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    today: date,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> date:
    earliest = today - timedelta(days=MAX_HISTORY_DAYS)
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            return min(max(watermark - timedelta(days=lookback_days), earliest), today)
    return earliest


def date_windows(
    start: date, end: date, window_days: int = WINDOW_DAYS
) -> list[tuple[date, date]]:  # nosemgrep: tuple-return-prefer-dataclass -- pre-existing, file moved
    """Split [start, end] into consecutive inclusive windows of at most `window_days` days."""
    if start > end:
        return []
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=window_days - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def validate_credentials(api_token: str, app_tokens: str | None = None) -> bool:
    """Confirm the API token (and any app token filter) works with a one-day report probe.

    Returns ``True`` on success. Raises ``AdjustCredentialsError`` with a user-facing message when
    Adjust rejects the token, the app tokens, or the request, ``AdjustRetryableError`` on
    rate-limit / 5xx responses, and lets transport errors propagate so a transient failure isn't
    mislabelled as a bad credential. Never returns ``False``.
    """
    tokens = parse_app_tokens(app_tokens)
    today = _today()
    params = {
        "dimensions": "day",
        "metrics": "installs",
        "date_period": f"{today.isoformat()}:{today.isoformat()}",
    }
    if tokens:
        params["app_token__in"] = ",".join(tokens)

    response = _get_session(api_token).get(f"{REPORT_URL}?{urlencode(params)}", timeout=30)

    if response.status_code in (408, 429) or response.status_code >= 500:
        raise AdjustRetryableError(f"Adjust API error (retryable): status={response.status_code}")
    if response.status_code == 200:
        return True
    if response.status_code == 401:
        raise AdjustCredentialsError(
            "Adjust rejected the API token. Check that you pasted a valid Adjust API token from "
            "your account settings in the Adjust dashboard."
        )
    if response.status_code == 403:
        raise AdjustCredentialsError(
            "Adjust denied access. Check that your user has reporting access to the apps you want "
            "to import and that your account includes the Report Service API."
        )
    if response.status_code in (400, 404, 422):
        raise AdjustCredentialsError(
            f"Adjust rejected the report request (HTTP {response.status_code})"
            f"{_error_message(response)}. If you set app tokens, check they belong to this account."
        )
    raise AdjustCredentialsError(
        f"Adjust returned an unexpected response (HTTP {response.status_code}) while validating "
        "credentials. If your API token looks correct, please try again shortly."
    )


def _iter_report_pages(
    session: requests.Session,
    params: dict[str, str],
    report: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{REPORT_URL}?{urlencode(params)}"
    for page in range(MAX_PAGES_PER_WINDOW):
        payload = _request(session, url, logger)
        yield extract_rows(payload)

        next_url = next_page_url(payload)
        if next_url is None:
            return
        if page + 1 == MAX_PAGES_PER_WINDOW:
            logger.warning(
                "Adjust page cap reached; truncating window",
                report=report,
                date_period=params["date_period"],
                pages=MAX_PAGES_PER_WINDOW,
            )
            return
        url = next_url


def get_event_catalog(
    api_token: str,
    app_tokens: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    events = fetch_events(_get_session(api_token, SYNC_RETRY), parse_app_tokens(app_tokens), logger)
    if events:
        yield events


def get_filters_data(
    api_token: str,
    app_tokens: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdjustResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    tokens = set(parse_app_tokens(app_tokens))
    session = _get_session(api_token, SYNC_RETRY)
    for filter_type in FILTER_TYPES:
        try:
            body = _request(session, f"{FILTERS_DATA_URL}?{urlencode({'required_filters': filter_type})}", logger)
        except requests.HTTPError as e:
            # One lookup that Adjust no longer accepts must not fail the other lookups.
            if e.response is not None and e.response.status_code == 400:
                logger.warning("Adjust: filters_data rejected a filter type, skipping it", filter_type=filter_type)
                resumable_source_manager.safe_point()
                continue
            raise

        # The response is keyed by filter type, and Adjust's own example shows a key that differs
        # from the requested value, so every list in the body is kept under its response key.
        rows = [
            {**item, "filter_type": key}
            for key, items in body.items()
            if isinstance(items, list)
            for item in items
            if isinstance(item, dict)
            and item.get("id") is not None
            # Keep the app lookup inside the app token filter, like every other table.
            and not (tokens and key == "apps" and item["id"] not in tokens)
        ]
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def _iter_campaign_api_pages(
    session: requests.Session, url: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for _page in range(MAX_CAMPAIGN_API_PAGES):
        body = _request(session, url, logger)
        data = body.get("data")
        if not isinstance(data, dict):
            return
        items = data.get("items")
        yield [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

        next_url = campaign_api_next_url(data)
        if next_url is None:
            return
        url = next_url
    # A full refresh replaces the table, so a truncated scan must fail rather than drop the tail.
    raise AdjustPageCapError(f"Adjust Campaign API returned more than {MAX_CAMPAIGN_API_PAGES} pages for {url}")


def _campaign_api_app_tokens(
    session: requests.Session, app_tokens: str | None, logger: FilteringBoundLogger
) -> list[str]:
    """The apps to fan out over: the configured app tokens, else every app the token can read."""
    tokens = parse_app_tokens(app_tokens)
    if tokens:
        return tokens
    body = _request(session, f"{FILTERS_DATA_URL}?{urlencode({'required_filters': 'apps'})}", logger)
    apps = body.get("apps")
    if not isinstance(apps, list):
        return []
    return [
        app["id"]
        for app in apps
        if isinstance(app, dict) and isinstance(app.get("id"), str) and _APP_TOKEN_RE.fullmatch(app["id"])
    ]


def _trackers_url(app_token: str, parent_token: str | None = None) -> str:
    url = f"{CAMPAIGN_API_URL}/apps/{app_token}/trackers"
    return f"{url}/{parent_token}/children" if parent_token else url


def _parent_tokens(rows: list[dict[str, Any]]) -> list[str]:
    return [
        row["token"]
        for row in rows
        if row.get("has_subtrackers") and isinstance(row.get("token"), str) and _APP_TOKEN_RE.fullmatch(row["token"])
    ]


def get_partners(
    api_token: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdjustResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    for rows in _iter_campaign_api_pages(_get_session(api_token, SYNC_RETRY), f"{CAMPAIGN_API_URL}/partners", logger):
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def get_links(
    api_token: str,
    app_tokens: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdjustResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(api_token, SYNC_RETRY)
    for app_token in _campaign_api_app_tokens(session, app_tokens, logger):
        for rows in _iter_campaign_api_pages(session, _trackers_url(app_token), logger):
            if rows:
                yield [{**row, "app_token": app_token} for row in rows]
            else:
                resumable_source_manager.safe_point()


def get_sublinks(
    api_token: str,
    app_tokens: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdjustResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk every link with sublinks down to the deepest level (campaign, ad group, creative)."""
    session = _get_session(api_token, SYNC_RETRY)
    for app_token in _campaign_api_app_tokens(session, app_tokens, logger):
        # Adjust links go 4 levels deep (network, campaign, ad group, creative). The depth limit and
        # the visited set stop a malformed tree from walking forever.
        pending: list[tuple[str, int]] = []
        visited: set[str] = set()
        for rows in _iter_campaign_api_pages(session, _trackers_url(app_token), logger):
            pending.extend((token, 1) for token in _parent_tokens(rows))
            resumable_source_manager.safe_point()

        while pending:
            parent_token, depth = pending.pop()
            if parent_token in visited or depth >= MAX_LINK_DEPTH:
                continue
            visited.add(parent_token)
            for rows in _iter_campaign_api_pages(session, _trackers_url(app_token, parent_token), logger):
                pending.extend((token, depth + 1) for token in _parent_tokens(rows))
                if rows:
                    yield [{**row, "app_token": app_token, "parent_token": parent_token} for row in rows]
                else:
                    resumable_source_manager.safe_point()


def get_rows(
    api_token: str,
    app_tokens: str | None,
    report: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdjustResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    if report not in ADJUST_REPORTS:
        raise ValueError(f"Unknown Adjust report: {report}")

    config = ADJUST_REPORTS[report]
    tokens = parse_app_tokens(app_tokens)
    session = _get_session(api_token, SYNC_RETRY)

    event_names: dict[str, str | None] = {}
    metric_batches = [config.metrics]
    if config.event_metrics:
        event_names = report_event_names(fetch_events(session, tokens, logger))
        slugs = list(event_names)
        metric_batches = [
            [f"{slug}_events" for slug in slugs[i : i + MAX_EVENT_METRICS_PER_REQUEST]]
            for i in range(0, len(slugs), MAX_EVENT_METRICS_PER_REQUEST)
        ]
        if not metric_batches:
            logger.info("Adjust: no events in the events catalog, skipping event report", report=report)
            return

    today = _today()
    start = resolve_start_date(
        should_use_incremental_field, db_incremental_field_last_value, today, config.lookback_days
    )
    windows = date_windows(start, today)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_start_date:
        windows = [window for window in windows if window[0].isoformat() >= resume.next_start_date]
        logger.debug(f"Adjust: resuming {report} from {resume.next_start_date}")

    # The tracked session already retries 403, 429 and transient 5xx honoring `Retry-After`, so there is
    # deliberately no second retry layer here — anything that reaches us has already been retried,
    # and the Temporal activity retries the job.
    for index, (window_start, window_end) in enumerate(windows):
        if config.event_metrics:
            # Each metric batch walks the whole window by day, so the batches are merged and
            # re-sorted to keep rows ascending across the window, as `sort_mode="asc"` promises.
            window_rows: list[dict[str, Any]] = []
            for metrics in metric_batches:
                params = build_report_params(report, window_start, window_end, tokens, metrics)
                for rows in _iter_report_pages(session, params, report, logger):
                    window_rows.extend(unpivot_event_rows(rows, config.dimensions, event_names))
                    if not window_rows:
                        resumable_source_manager.safe_point()
            if window_rows:
                window_rows.sort(key=lambda row: str(row.get("day") or ""))
                yield window_rows
        else:
            params = build_report_params(report, window_start, window_end, tokens)
            for rows in _iter_report_pages(session, params, report, logger):
                if rows:
                    yield rows
                # The staged cursor points at this window's start or earlier, so a resume re-reads
                # the window and loses no rows.
                resumable_source_manager.safe_point()

        # Save AFTER yielding the window so a crash re-yields it rather than skipping it (merge
        # dedupes on the dimension key).
        if index + 1 < len(windows):
            resumable_source_manager.save_state(AdjustResumeConfig(next_start_date=windows[index + 1][0].isoformat()))


def adjust_source(
    api_token: str,
    app_tokens: str | None,
    report: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdjustResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    if report in CATALOG_PRIMARY_KEYS:
        catalogs: dict[str, Callable[[], Iterator[list[dict[str, Any]]]]] = {
            EVENTS_CATALOG: lambda: get_event_catalog(api_token, app_tokens, logger),
            FILTERS_DATA: lambda: get_filters_data(api_token, app_tokens, logger, resumable_source_manager),
            PARTNERS: lambda: get_partners(api_token, logger, resumable_source_manager),
            LINKS: lambda: get_links(api_token, app_tokens, logger, resumable_source_manager),
            SUBLINKS: lambda: get_sublinks(api_token, app_tokens, logger, resumable_source_manager),
        }
        return SourceResponse(
            name=report,
            items=catalogs[report],
            primary_keys=CATALOG_PRIMARY_KEYS[report],
            # The lookup tables save no checkpoint, so an interrupted run starts again from the top.
            supports_resume=False,
        )

    config = ADJUST_REPORTS[report]

    return SourceResponse(
        name=report,
        items=lambda: get_rows(
            api_token=api_token,
            app_tokens=app_tokens,
            report=report,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["day"],
        sort_mode="asc",
        # Aggregated dimension keys can collide when a dimension value comes back blank (e.g.
        # organic traffic with no campaign) — an expected trait of report data, not a data-quality
        # problem the user can fix. Don't set has_duplicate_primary_keys: that flag tells
        # validate_incremental_sync to block incremental syncing altogether, which would make
        # `day` (the only incremental field this source offers) permanently unusable. The merge's
        # own per-batch dedup (keep-last-per-key) already resolves the collision safely.
    )
