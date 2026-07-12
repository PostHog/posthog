"""pretix transport layer.

pretix is an open-source event-ticketing platform offered both as the hosted SaaS
(``https://pretix.eu``) and self-hosted (a customer-supplied host), so the API base URL must be
configurable. Auth is a team-level API token in an ``Authorization: Token <token>`` header; a token
is scoped to a single organizer, and every resource lives under
``/api/v1/organizers/{organizer}/...``.

List endpoints are page-number paginated with a ``count``/``next``/``previous``/``results``
envelope (page size defaults to the maximum of 50), where ``next`` is the full URL of the following
page. Orders and invoices use the organizer-level list endpoints spanning all events; the remaining
event-scoped resources fan out over the organizer's events.

Only ``orders`` documents a server-side timestamp filter (``modified_since``) together with a
``last_modified`` ordering key, so it is the only incremental stream. Everything else is full
refresh — pretix's other list endpoints only support ``If-Modified-Since`` conditional fetching
(all-or-nothing 304s), which is not a per-row cursor.
"""

import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.settings import (
    EVENT_SLUG_KEY,
    EVENTS_PATH,
    PRETIX_ENDPOINTS,
    EndpointScope,
    PretixEndpointConfig,
)

DEFAULT_API_HOST = "https://pretix.eu"
API_VERSION_PATH = "/api/v1"

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# pretix Hosted enforces 360 requests/minute per organizer token and returns 429 + Retry-After.
MAX_RETRY_AFTER_SECONDS = 60

HOST_NOT_ALLOWED_ERROR = "pretix API URL is not allowed"
HTTP_NOT_ALLOWED_ERROR = "pretix API URL must use HTTPS"
INVALID_ORGANIZER_ERROR = "Invalid pretix organizer short name"


class PretixRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PretixHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class PretixResumeConfig:
    # Full URL of the next page to fetch, taken verbatim from the API's ``next`` link (query params,
    # including any `modified_since` filter, are baked into it). Only persisted for organizer-level
    # endpoints — event fan-out endpoints restart from the first event on resume and rely on merge
    # dedupe, since event ordering is not guaranteed stable across runs.
    next_url: str | None = None


def normalize_base_url(base_url: Optional[str]) -> str:
    """Turn whatever the user typed into a ``<scheme>://<host>/api/v1`` base URL.

    Blank → the hosted pretix SaaS. Accepts bare hosts (``tickets.example.com``), full URLs with or
    without a scheme, and values that already include the ``/api/v1`` suffix.
    """
    raw = (base_url or "").strip()
    if not raw:
        raw = DEFAULT_API_HOST
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    # Drop a trailing version segment the user may have pasted in, then re-add the version we target.
    raw = re.sub(r"/api/v\d+$", "", raw)
    return f"{raw}{API_VERSION_PATH}"


def _host_of(base_url: str) -> str:
    # `urlparse` treats a backslash (and its `%5c` encoding) as userinfo, so
    # `https://127.0.0.1\@example.com` parses as host `example.com` while requests/urllib3 (per the
    # WHATWG URL rules) treat `\` as a path separator and connect to `127.0.0.1`. Normalize to `/`
    # first so the host we validate is the host the request actually reaches (SSRF bypass guard).
    normalized = base_url.replace("\\", "/").replace("%5c", "/").replace("%5C", "/")
    return (urlparse(normalized).hostname or "").lower()


def _is_https(base_url: str) -> bool:
    # The API token rides in the Authorization header, so refuse plaintext HTTP to keep an on-path
    # attacker from capturing it.
    return urlparse(base_url).scheme == "https"


def _quote_organizer(organizer: str) -> str:
    """URL-quote the organizer slug so it can't inject path segments into request URLs."""
    cleaned = organizer.strip().strip("/")
    if not cleaned:
        raise ValueError(INVALID_ORGANIZER_ERROR)
    return quote(cleaned, safe="")


def _get_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Token {api_token}", "Accept": "application/json"}


def _format_modified_since(value: Any) -> str:
    """Format an incremental value for pretix's ``modified_since`` filter (ISO 8601 UTC, Z suffix)."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _check_host(base_url: str, team_id: int) -> None:
    """Raise unless the (customer-controlled, possibly self-hosted) base URL is safe to call."""
    host = _host_of(base_url)
    host_ok, host_err = _is_host_safe(host, team_id)
    if not host_ok:
        raise PretixHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
    if not _is_https(base_url):
        raise PretixHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)


def _parse_retry_after(response: requests.Response) -> float | None:
    """Honor a whole-second ``Retry-After`` on 429. HTTP-date forms are ignored."""
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Use a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, PretixRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def _origin_of(url: str) -> tuple[str, str, int]:
    # Same backslash normalization as `_host_of`, so the origin we compare is the one requests
    # actually connects to.
    normalized = url.replace("\\", "/").replace("%5c", "/").replace("%5C", "/")
    parsed = urlparse(normalized)
    scheme = parsed.scheme.lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, (parsed.hostname or "").lower(), port


def _ensure_same_origin(url: str, base_url: str) -> None:
    """Refuse pagination/resume URLs that leave the validated pretix origin.

    ``next`` links come from the (possibly self-hosted, customer-controlled) server and resume URLs
    from persisted state, while the session attaches the API token to every request — following an
    off-origin URL would hand the token to an arbitrary host (or reach internal addresses)."""
    if _origin_of(url) != _origin_of(base_url):
        raise PretixHostNotAllowedError(f"pretix pagination URL is not on the configured pretix host: {url}")


def _fetch_page_impl(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Fetch one list page. ``url`` is absolute — the initial endpoint URL (params baked in via
    urlencode) or a verbatim ``next`` link, so page params are never re-sent."""
    # Don't follow redirects: an attacker-controlled self-hosted URL could 3xx to an internal
    # address, bypassing the host validation done before the request (SSRF).
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

    if response.status_code == 429 or response.status_code >= 500:
        retry_after = _parse_retry_after(response) if response.status_code == 429 else None
        raise PretixRetryableError(
            f"pretix API error (retryable): status={response.status_code}, url={url}", retry_after=retry_after
        )

    # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather than
    # silently parsing the redirect body as data.
    if response.is_redirect or response.is_permanent_redirect:
        raise PretixHostNotAllowedError(
            f"pretix API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
        )

    if not response.ok:
        logger.error(f"pretix API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise PretixRetryableError(f"pretix returned an unexpected payload for {url}: {type(data).__name__}")

    next_url = data.get("next")
    return data["results"], next_url if isinstance(next_url, str) and next_url else None


_fetch_page = retry(
    retry=retry_if_exception_type((PretixRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)(_fetch_page_impl)


def _iter_pages(
    session: requests.Session,
    first_url: str,
    base_url: str,
    logger: FilteringBoundLogger,
) -> Iterator[tuple[list[dict[str, Any]], Optional[str]]]:
    """Yield ``(page_items, next_url)`` across every page starting at ``first_url``.

    Every fetched URL — including a resumed ``first_url`` — and every ``next`` link is pinned to the
    validated base origin before it is fetched or yielded (and thus before it can be persisted)."""
    url: Optional[str] = first_url
    while url:
        _ensure_same_origin(url, base_url)
        items, next_url = _fetch_page(session, url, logger)
        if next_url:
            _ensure_same_origin(next_url, base_url)
        yield items, next_url
        url = next_url


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    return f"{base_url}{path}?{urlencode(params)}" if params else f"{base_url}{path}"


def _iter_event_slugs(
    session: requests.Session, base_url: str, organizer: str, logger: FilteringBoundLogger
) -> Iterator[str]:
    url = _build_url(base_url, EVENTS_PATH.format(organizer=organizer), {})
    for page, _ in _iter_pages(session, url, base_url, logger):
        for event in page:
            # Fail fast on a malformed response rather than silently dropping an event's children.
            yield str(event["slug"])


def get_rows(
    api_token: str,
    organizer: str,
    base_url: Optional[str],
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PretixResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config: PretixEndpointConfig = PRETIX_ENDPOINTS[endpoint]
    resolved_base_url = normalize_base_url(base_url)
    # Re-check at run time (not just at source-create) in case the URL was edited or now resolves
    # to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    _check_host(resolved_base_url, team_id)
    quoted_organizer = _quote_organizer(organizer)

    # `redact_values` masks the token from captured HTTP samples — it rides in the Authorization
    # header with the non-standard `Token` scheme.
    session = make_tracked_session(headers=_get_headers(api_token), redact_values=(api_token,))

    params: dict[str, Any] = {}
    if config.ordering:
        # An explicit stable sort keeps page boundaries deterministic, and for `orders` it makes the
        # response order match SourceResponse.sort_mode="asc" so the incremental watermark advances
        # correctly (DRF-style `ordering=<field>` is ascending).
        params["ordering"] = config.ordering
    # Only narrow with the server-side `modified_since` filter when the endpoint supports it and the
    # user's chosen cursor is the field that filter targets. Honors inputs.incremental_field rather
    # than assuming it.
    if (
        should_use_incremental_field
        and config.modified_since_field
        and db_incremental_field_last_value
        and incremental_field in (None, config.modified_since_field)
    ):
        params["modified_since"] = _format_modified_since(db_incremental_field_last_value)

    if config.scope == EndpointScope.ORGANIZER:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        if resume and resume.next_url:
            logger.debug(f"pretix: resuming {endpoint} from saved page URL")
            first_url = resume.next_url
        else:
            first_url = _build_url(resolved_base_url, config.path.format(organizer=quoted_organizer), params)

        for page, next_url in _iter_pages(session, first_url, resolved_base_url, logger):
            if page:
                yield page
            # Save AFTER yielding so a crash re-fetches from the last unpersisted page (merge
            # dedupes the re-pulled page on the primary key).
            if next_url:
                resumable_source_manager.save_state(PretixResumeConfig(next_url=next_url))
        return

    # Event fan-out: paginate the child endpoint per event, stamping each row with its parent event
    # slug so composite primary keys stay unique table-wide. No resume state is persisted here.
    for event_slug in _iter_event_slugs(session, resolved_base_url, quoted_organizer, logger):
        path = config.path.format(organizer=quoted_organizer, event=quote(event_slug, safe=""))
        for page, _ in _iter_pages(session, _build_url(resolved_base_url, path, params), resolved_base_url, logger):
            if page:
                yield [{**row, EVENT_SLUG_KEY: event_slug} for row in page]


def pretix_source(
    api_token: str,
    organizer: str,
    base_url: Optional[str],
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PretixResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PRETIX_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            organizer=organizer,
            base_url=base_url,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(
    api_token: str, organizer: str, base_url: Optional[str], team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe the organizer's events list to confirm the token is genuine and scoped correctly.

    pretix team tokens carry per-resource permissions, so a single cheap probe only asserts the
    token + organizer pair is valid — per-endpoint 403s at sync time surface through
    ``get_non_retryable_errors``.
    """
    resolved_base_url = normalize_base_url(base_url)

    try:
        quoted_organizer = _quote_organizer(organizer)
    except ValueError:
        return False, INVALID_ORGANIZER_ERROR

    if team_id is not None:
        host_ok, host_err = _is_host_safe(_host_of(resolved_base_url), team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR
    if not _is_https(resolved_base_url):
        return False, HTTP_NOT_ALLOWED_ERROR

    url = _build_url(resolved_base_url, EVENTS_PATH.format(organizer=quoted_organizer), {"page_size": 1})
    session = make_tracked_session(headers=_get_headers(api_token), redact_values=(api_token,))
    try:
        response = session.get(url, timeout=15, allow_redirects=False)
    except Exception as e:
        return False, f"Could not connect to pretix: {e}"

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid pretix API token"

    if response.status_code == 403:
        # pretix returns 403 both for an unknown organizer and for a token without access to it.
        return False, (
            "Your pretix API token does not have access to this organizer. "
            "Check the organizer short name and the token's team permissions."
        )

    return False, f"pretix returned HTTP {response.status_code}"
