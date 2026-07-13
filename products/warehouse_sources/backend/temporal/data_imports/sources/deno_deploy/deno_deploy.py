import re
import hashlib
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.settings import (
    DENO_DEPLOY_ENDPOINTS,
    DenoDeployEndpointConfig,
)

DENO_DEPLOY_HOST = "api.deno.com"
DENO_DEPLOY_BASE_URL = f"https://{DENO_DEPLOY_HOST}"

# Default page size for the cursor-paginated list endpoints (API default is 30, max 100).
DEFAULT_LIST_PAGE_SIZE = 100


class DenoDeployRetryableError(Exception):
    pass


def _require_deno_deploy_url(url: str) -> str:
    """SSRF guard for every authenticated request. The bearer token is attached to whatever URL we
    fetch, and both pagination `Link` headers and persisted resume URLs are attacker-influenceable, so
    only accept HTTPS URLs whose host is exactly `api.deno.com` before the token can be forwarded."""
    try:
        parts = urlsplit(url)
    except ValueError as e:
        raise ValueError(f"Refusing to fetch malformed Deno Deploy URL: {e}")
    if parts.scheme != "https" or parts.hostname != DENO_DEPLOY_HOST:
        raise ValueError(f"Refusing to fetch off-host Deno Deploy URL (host={parts.hostname!r})")
    return url


def _make_session(access_token: str) -> requests.Session:
    """A tracked session that (1) masks the bearer token in logged URLs and captured samples and
    (2) never follows redirects, so a tampered response can't bounce the `Authorization` header to an
    attacker-controlled host."""
    return make_tracked_session(redact_values=(access_token,), allow_redirects=False)


@dataclasses.dataclass
class DenoDeployResumeConfig:
    # Full URL of the next page to fetch. None means "start this app's endpoint at its first page" —
    # used when the bookmark advances to a fan-out app whose first-page URL isn't known until built.
    next_url: str | None = None
    # The fan-out app currently being processed, as a stable app id (not a positional index) so apps
    # added/removed between a crash and the retry can't resume into the wrong app. None for the
    # top-level (non-fan-out) endpoints.
    app_id: str | None = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _format_rfc3339(dt: datetime) -> str:
    """Format a datetime as RFC 3339 / ISO 8601 with a `Z` suffix, which Deno Deploy's time filters
    accept. isoformat() emits `+00:00`; we normalize to `Z` to match the API's documented examples."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _as_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return None


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{DENO_DEPLOY_BASE_URL}{path}"
    return f"{DENO_DEPLOY_BASE_URL}{path}?{urlencode(params)}"


def _parse_next_link(link_header: str) -> str | None:
    """Return the URL with rel="next" from Deno Deploy's Link header, if any.

    The header looks like: `Link: </v2/apps?cursor=eyJ...&limit=30>; rel="next"`. The URL may be
    relative to the API host, so resolve it against the base URL."""
    if not link_header:
        return None
    for part in link_header.split(","):
        match = re.search(r'<([^>]+)>;\s*rel="next"', part.strip())
        if match:
            url = match.group(1)
            if url.startswith("/"):
                return f"{DENO_DEPLOY_BASE_URL}{url}"
            return url
    return None


@retry(
    retry=retry_if_exception_type(
        (
            DenoDeployRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    # Validate every URL at the single choke point where the token is attached: this covers freshly
    # built URLs, `Link`-header continuations, logs cursors, and persisted resume URLs alike.
    _require_deno_deploy_url(url)
    response = session.get(url, headers=headers, timeout=60)

    # Rate limits aren't documented in the spec; treat 429 and 5xx as transient and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise DenoDeployRetryableError(f"Deno Deploy API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Deno Deploy API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    """Confirm the org access token is genuine with one cheap probe against the apps list."""
    url = _require_deno_deploy_url(_build_url("/v2/apps", {"limit": 1}))
    try:
        response = _make_session(access_token).get(url, headers=_get_headers(access_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Deno Deploy access token. Create a new organization access token and reconnect."
    if response.status_code == 403:
        return False, "Your Deno Deploy access token does not have permission to read this organization's data."

    try:
        message = response.json().get("message", response.text)
    except ValueError:
        message = response.text
    return False, message


def _iter_app_refs(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[tuple[str, str]]:
    """Page through /v2/apps and yield each app's (id, slug), following the Link header cursor."""
    url: str | None = _build_url("/v2/apps", {"limit": DEFAULT_LIST_PAGE_SIZE})
    while url:
        response = _fetch(session, url, headers, logger)
        data = response.json()
        for app in data if isinstance(data, list) else []:
            yield app["id"], app.get("slug", "")
        url = _parse_next_link(response.headers.get("Link", ""))


def _log_row_id(app_id: str, log: dict[str, Any]) -> str:
    """Runtime log lines carry no natural id, so synthesize a stable content hash. Merging on it makes
    re-pulling the overlapping boundary window idempotent (identical lines collapse to one row). Two
    genuinely distinct lines identical across every field would also collapse — an accepted, rare loss
    for a source without log ids."""
    parts = [
        app_id,
        str(log.get("timestamp", "")),
        str(log.get("level", "")),
        str(log.get("message", "")),
        str(log.get("revision_id", "")),
        str(log.get("region", "")),
        str(log.get("trace_id", "")),
        str(log.get("span_id", "")),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _shape_log(log: dict[str, Any], app_id: str, app_slug: str) -> dict[str, Any]:
    return {**log, "app_id": app_id, "app_slug": app_slug, "id": _log_row_id(app_id, log)}


def _reshape_analytics(body: dict[str, Any], app_id: str, app_slug: str) -> list[dict[str, Any]]:
    """Deno returns analytics as a columnar {fields: [{name}], values: [[...], ...]} payload. Reshape
    it into one dict per time bucket keyed by field name (the docs say to map by name, not position)."""
    field_names = [f["name"] for f in body.get("fields", [])]
    rows: list[dict[str, Any]] = []
    for value_row in body.get("values", []):
        row: dict[str, Any] = dict(zip(field_names, value_row))
        row["app_id"] = app_id
        row["app_slug"] = app_slug
        rows.append(row)
    return rows


def _time_window_params(
    config: DenoDeployEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> tuple[str, str]:
    """Resolve the [start, end] window for the time-ranged endpoints (logs, analytics).

    `end` is always `now` — never omitted, since the logs endpoint switches to real-time streaming
    without it. `start` is the incremental watermark (minus a small lookback for boundary/clock-skew
    slack, clamped to never exceed now) or, on the first sync / full refresh, `now - default_lookback`.
    Because each run fetches every app up to `now`, consecutive windows overlap and leave no gap."""
    now = datetime.now(UTC)
    last = _as_utc_datetime(db_incremental_field_last_value) if should_use_incremental_field else None
    if last is not None:
        start = min(last, now)
        if config.incremental_lookback:
            start = start - config.incremental_lookback
    else:
        start = now - timedelta(days=config.default_lookback_days or 7)
    return _format_rfc3339(start), _format_rfc3339(now)


def _initial_child_url(
    config: DenoDeployEndpointConfig,
    app_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    path = config.path.format(app=app_id)
    if config.kind == "logs":
        start, end = _time_window_params(config, should_use_incremental_field, db_incremental_field_last_value)
        return _build_url(path, {"start": start, "end": end, "limit": config.page_size or 1000})
    if config.kind == "analytics":
        since, until = _time_window_params(config, should_use_incremental_field, db_incremental_field_last_value)
        return _build_url(path, {"since": since, "until": until})
    # Plain list child (revisions).
    return _build_url(path, {"limit": config.page_size or DEFAULT_LIST_PAGE_SIZE})


def _logs_next_url(current_url: str, next_cursor: str) -> str:
    """The logs endpoint returns its cursor in the body (`next_cursor`), not a Link header. Rebuild the
    next-page URL by swapping the `cursor` query param on the current URL, preserving start/end/limit.

    `parse_qsl` decodes the existing (already percent-encoded) query values so `urlencode` re-encodes
    them exactly once — splitting the raw query string by hand would double-encode `start`/`end`."""
    parts = urlsplit(current_url)
    params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "cursor"]
    params.append(("cursor", next_cursor))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))


def _parse_page(
    config: DenoDeployEndpointConfig, response: requests.Response, app_id: str, app_slug: str
) -> tuple[list[dict[str, Any]], str | None]:
    """Return (rows, next_url) for one fetched page, shaped per endpoint kind."""
    if config.kind == "logs":
        body = response.json()
        rows = [_shape_log(log, app_id, app_slug) for log in body.get("logs", [])]
        next_cursor = body.get("next_cursor")
        next_url = _logs_next_url(response.url, next_cursor) if next_cursor else None
        return rows, next_url
    if config.kind == "analytics":
        return _reshape_analytics(response.json(), app_id, app_slug), None
    # Plain list child (revisions): inject the parent app context the child response omits.
    data = response.json()
    rows = [{**item, "app_id": app_id, "app_slug": app_slug} for item in (data if isinstance(data, list) else [])]
    return rows, _parse_next_link(response.headers.get("Link", ""))


def _list_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: DenoDeployEndpointConfig,
    resumable_source_manager: ResumableSourceManager[DenoDeployResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Top-level cursor-paginated list (apps, domains), following the Link header."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url: str | None = resume.next_url
        logger.debug(f"Deno Deploy: resuming {config.name} from URL: {url}")
    else:
        url = _build_url(config.path, {"limit": config.page_size or DEFAULT_LIST_PAGE_SIZE})

    while url:
        response = _fetch(session, url, headers, logger)
        data = response.json()
        rows = data if isinstance(data, list) else []
        next_url = _parse_next_link(response.headers.get("Link", ""))
        if rows:
            yield rows
        if not next_url:
            break
        # Save AFTER yielding so a crash mid-yield re-fetches this page rather than skipping it; merge
        # dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(DenoDeployResumeConfig(next_url=next_url))
        url = next_url


def _fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: DenoDeployEndpointConfig,
    resumable_source_manager: ResumableSourceManager[DenoDeployResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every app in the org, walking the child endpoint (revisions, analytics, logs) per
    app. A stable app-id bookmark lets a retry resume mid-fan-out without re-walking finished apps."""
    app_refs = list(_iter_app_refs(session, headers, logger))
    app_ids = [ref[0] for ref in app_refs]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = 0
    resume_url: str | None = None
    if resume is not None and resume.app_id is not None and resume.app_id in app_ids:
        start_index = app_ids.index(resume.app_id)
        resume_url = resume.next_url
        logger.debug(f"Deno Deploy: resuming {config.name} fan-out from app_id={resume.app_id}, url={resume_url}")

    for index in range(start_index, len(app_refs)):
        app_id, app_slug = app_refs[index]
        url: str | None = resume_url or _initial_child_url(
            config, app_id, should_use_incremental_field, db_incremental_field_last_value
        )
        resume_url = None  # only the resumed-into app uses the saved URL; the rest start fresh

        while url:
            response = _fetch(session, url, headers, logger)
            rows, next_url = _parse_page(config, response, app_id, app_slug)
            if rows:
                yield rows
            if not next_url:
                break
            resumable_source_manager.save_state(DenoDeployResumeConfig(next_url=next_url, app_id=app_id))
            url = next_url

        # Advance the bookmark to the next app so a crash between apps resumes there; its first-page
        # URL is rebuilt fresh when the loop reaches it.
        if index + 1 < len(app_refs):
            resumable_source_manager.save_state(DenoDeployResumeConfig(next_url=None, app_id=app_refs[index + 1][0]))


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DenoDeployResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DENO_DEPLOY_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    session = _make_session(access_token)

    if config.fan_out_over_apps:
        yield from _fan_out_rows(
            session,
            headers,
            config,
            resumable_source_manager,
            logger,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    yield from _list_rows(session, headers, config, resumable_source_manager, logger)


def deno_deploy_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DenoDeployResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = DENO_DEPLOY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Every endpoint emits ascending by its partition/incremental field: the list endpoints are
        # full-refresh (order only needs to be stable), and the time-windowed endpoints (logs,
        # analytics) return oldest-first within the [start, end] window, matching the watermark's
        # forward advance.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
