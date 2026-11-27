"""Moxie transport layer.

Moxie (withmoxie.com) is an all-in-one business-management app for freelancers, hosted on a
per-workspace pod (e.g. `pod00.withmoxie.dev`), so the API base URL is a user-supplied credential
rather than a constant. Auth is a single `X-API-KEY` header
(https://help.withmoxie.com/en/articles/8154735-public-api-fundamentals).

Almost every list/search endpoint returns the full collection as one bare JSON array with no
pagination and no filter on a modification time, so every table here is full refresh only. Two
endpoint shapes exist:
most return an array of objects, but `emailTemplates`, `invoiceTemplates`, `vendors`, and `formNames`
return an array of bare strings (template/vendor/form names). The framework's per-item `data_map` only
runs on dict items (see `Resource._apply_transforms`), so those four are wrapped into a one-column row
after the fact in `moxie_source`, not declared as a `data_map` on the resource.

`time_entries` returns at most 10,000 rows per call in no guaranteed order. When a call reaches
that cap, the source splits the `timerStart` window in half and asks again (see
`iter_time_entries`). `ticket_comments` and `project_notes` take a parent id, so they fan out over
`tickets` and `projects`.

Moxie enforces a hard rate limit of 100 Public API requests per 5-minute window per workspace,
returning HTTP 429 when exceeded. The other tables send only a few requests per sync, so the
transport-level retry is enough for them. The fan-out tables send one request per parent, so they
pace every request through a `RequestPacer` (see `_PacedSession`).
"""

import re
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast
from urllib.parse import urlparse

from requests import PreparedRequest, Request, Response, Session

from products.warehouse_sources.sources.moxie.settings import (
    FANOUT_RATE_LIMIT_HOLD_SECONDS,
    FANOUT_REQUESTS_PER_SECOND,
    MOXIE_API_PATH_PREFIX,
    MOXIE_ENDPOINTS,
    MoxieEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    RequestPacer,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    _is_host_safe,
    build_dependent_resource,
    format_datetime,
    frozen,
    make_tracked_session,
    parse_retry_after,
    rest_api_resource,
    validate_via_probe,
)

HOST_NOT_ALLOWED_ERROR = "Moxie workspace base URL is not allowed"
HTTP_NOT_ALLOWED_ERROR = "Moxie workspace base URL must use HTTPS"

# (connect, read) timeout: a customer-controlled host that accepts the connection and then never
# responds (or trickles bytes) would otherwise hold an import worker for the activity's full runtime
# budget, since RESTClient passes this straight to `requests` as `timeout=None` when unset.
REQUEST_TIMEOUT_SECONDS = (10.0, 60.0)

# List Time Entries returns at most this many rows per call.
TIME_ENTRIES_ROW_CAP = 10_000
# The lower bound of the first `timerStart` window. Moxie did not exist before this date.
TIME_ENTRIES_EARLIEST = datetime(2000, 1, 1, tzinfo=UTC)


@frozen
class TimeWindow:
    # Both bounds are inclusive on the API side. None leaves that side open.
    earliest: Optional[datetime]
    latest: Optional[datetime]


class MoxieTimeEntriesCapError(Exception):
    pass


class MoxieHostNotAllowedError(Exception):
    pass


@frozen
class MoxieResumeConfig:
    # `build_dependent_resource` checkpoint for a fan-out table: the parents already done and the
    # cursor of the one in progress.
    fanout_state: Optional[dict[str, Any]] = None


def normalize_base_url(base_url: Optional[str]) -> str:
    """Turn whatever the user pasted from Connected Apps > Integrations into a full base URL.

    Accepts a bare pod host (`pod00.withmoxie.dev`) or the full URL shown in Moxie's UI
    (`https://pod00.withmoxie.dev/api/public`), with or without a trailing slash.
    """
    raw = (base_url or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    if not re.search(r"/api/public$", raw, flags=re.IGNORECASE):
        raw = f"{raw}/api/public"
    return raw


def _host_of(base_url: str) -> str:
    # `urlparse` treats a backslash (and its `%5c` encoding) as userinfo, so
    # `https://127.0.0.1\@example.com` parses as host `example.com` while requests/urllib3 (per the
    # WHATWG URL rules) treat `\` as a path separator and connect to `127.0.0.1`. Normalize to `/`
    # first so the host we validate is the host the request actually reaches (SSRF bypass guard).
    normalized = base_url.replace("\\", "/").replace("%5c", "/").replace("%5C", "/")
    return (urlparse(normalized).hostname or "").lower()


def _is_https(base_url: str) -> bool:
    # The API key rides in the X-API-KEY header, so refuse plaintext HTTP to keep an on-path
    # attacker from capturing it.
    return urlparse(base_url).scheme == "https"


def _flatten_workspace_user(item: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested `user.userId` onto the row root as `user_id`, the only stable per-row key
    List Workspace Users exposes (a nested field can't be declared as a `SourceResponse` primary key).
    """
    user = item.get("user") or {}
    return {**item, "user_id": user.get("userId")}


def get_resource(endpoint: str, params: Optional[dict[str, Any]] = None) -> EndpointResource:
    config = MOXIE_ENDPOINTS[endpoint]
    request_params = {**config.params, **(params or {})}
    endpoint_config: Endpoint = {"path": config.path}
    if request_params:
        endpoint_config["params"] = request_params
    resource: EndpointResource = {
        "name": endpoint,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }
    if endpoint == "workspace_users":
        resource["data_map"] = _flatten_workspace_user
    return resource


def _split(window: TimeWindow) -> Optional[list[TimeWindow]]:
    if window.earliest is None or window.latest is None:
        return None
    half = timedelta(seconds=int((window.latest - window.earliest).total_seconds()) // 2)
    if half <= timedelta(0):
        return None
    middle = window.earliest + half
    return [TimeWindow(earliest=window.earliest, latest=middle), TimeWindow(earliest=middle, latest=window.latest)]


def iter_time_entries(
    fetch: Callable[[Optional[TimeWindow]], list[dict[str, Any]]], now: datetime
) -> Iterator[list[dict[str, Any]]]:
    """Read every time entry, in `timerStart` windows small enough to stay under the row cap.

    Most workspaces fit in one call with no window. Otherwise a window that reaches the cap is split
    in half, and the halves are read in order, so adjacent windows share only their bound. Two
    open-ended windows before and after the split range keep entries with an unusual start time.
    """
    rows = fetch(None)
    if len(rows) < TIME_ENTRIES_ROW_CAP:
        if rows:
            yield rows
        return

    upper = now + timedelta(days=366)
    # A stack, so the windows run from the earliest to the latest.
    pending = [
        TimeWindow(earliest=upper, latest=None),
        TimeWindow(earliest=TIME_ENTRIES_EARLIEST, latest=upper),
        TimeWindow(earliest=None, latest=TIME_ENTRIES_EARLIEST),
    ]
    previous_ids: set[Any] = set()
    while pending:
        window = pending.pop()
        rows = fetch(window)
        if len(rows) >= TIME_ENTRIES_ROW_CAP:
            halves = _split(window)
            if halves is None:
                # Yielding the capped page would drop rows without a trace. This also ends a walk
                # against a host that returns a full page for every window.
                raise MoxieTimeEntriesCapError(
                    f"Moxie returned {len(rows)} time entries for a window that cannot be split "
                    f"({window.earliest} to {window.latest}), so some entries cannot be read"
                )
            pending.extend(reversed(halves))
            continue
        # Both bounds are inclusive, so an entry that starts on the shared bound of two windows
        # comes back from both.
        page = [row for row in rows if row.get("id") is None or row.get("id") not in previous_ids]
        previous_ids = {row.get("id") for row in rows}
        if page:
            yield page


def _client_config(resolved_base_url: str, api_key: str) -> ClientConfig:
    return {
        "base_url": resolved_base_url,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"},
        # The list endpoints return the whole collection in one bare array. Ticket comments set
        # their own cursor paginator.
        "paginator": "single_page",
        # Don't follow redirects: a compromised/edited base_url could 3xx to an internal address,
        # bypassing the host check (SSRF).
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }


class _PacedSession:
    """Takes a pacer slot before every request it sends, and reports each 429 to the pacer.

    `RESTClient` drives the pagination and the retries itself, so the pacing must sit in front of
    `send`. `RESTClient` reads `headers` and calls `prepare_request` and `send`. Every request still
    goes out through the tracked session, with its redaction and its refusal to follow redirects.
    """

    def __init__(self, session: Session, pacer: RequestPacer) -> None:
        self._session = session
        self._pacer = pacer

    @property
    def headers(self) -> Any:
        return self._session.headers

    def prepare_request(self, request: Request) -> PreparedRequest:
        return self._session.prepare_request(request)

    def send(self, request: PreparedRequest, **kwargs: Any) -> Response:
        self._pacer.wait_turn()
        response = self._session.send(request, **kwargs)
        if response.status_code == 429:
            self._pacer.throttled(parse_retry_after(response))
        return response


def _paced_client_config(client_config: ClientConfig, api_key: str) -> ClientConfig:
    pacer = RequestPacer(FANOUT_REQUESTS_PER_SECOND, hold_seconds=FANOUT_RATE_LIMIT_HOLD_SECONDS)
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    # Not a `Session` subclass: the tracked session comes from a factory, and a subclass would have
    # to rebuild its adapters.
    return {**client_config, "session": cast(Session, _PacedSession(session, pacer))}


def _fanout_resource(
    config: MoxieEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MoxieResumeConfig],
) -> Iterable[Any]:
    assert config.fanout is not None
    # A paced fan-out over a large workspace runs for hours, so a restart skips the parents it
    # already finished instead of starting again from the first one.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(MoxieResumeConfig(fanout_state=state))

    if config.name == "ticket_comments":
        child_endpoint_extra: Any = {
            "data_selector": "comments",
            "paginator": JSONResponseCursorPaginator(
                cursor_path="nextCursor", cursor_param="cursor", raise_on_repeated_cursor=True
            ),
        }
    else:
        child_endpoint_extra = {"paginator": SinglePagePaginator()}
    return build_dependent_resource(
        endpoint_configs=MOXIE_ENDPOINTS,
        child_endpoint=config.name,
        fanout=config.fanout,
        client_config=client_config,
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        child_endpoint_extra=child_endpoint_extra,
        child_params_extra=dict(config.params),
        page_size_param=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def moxie_source(
    base_url: Optional[str],
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MoxieResumeConfig],
) -> SourceResponse:
    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)
    config = MOXIE_ENDPOINTS[endpoint]

    client_config = _client_config(resolved_base_url, api_key)

    def rest_config(params: Optional[dict[str, Any]] = None) -> RESTAPIConfig:
        return {"client": client_config, "resource_defaults": None, "resources": [get_resource(endpoint, params)]}

    def fetch_time_entries(window: Optional[TimeWindow]) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if window is not None and window.earliest is not None:
            params["earliest"] = format_datetime(window.earliest, "iso_z")
        if window is not None and window.latest is not None:
            params["latest"] = format_datetime(window.latest, "iso_z")
        return [row for batch in rest_api_resource(rest_config(params), team_id, job_id, None) for row in batch]

    wrap_field = config.wrap_scalar_as

    def items() -> Any:
        for batch in rest_api_resource(rest_config(), team_id, job_id, None):
            if wrap_field:
                yield [{wrap_field: value} for value in batch]
            else:
                yield batch

    def source_items() -> Iterable[Any]:
        # Re-check at run time, not just at source-create: the base_url can be edited later and now
        # resolve to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            raise MoxieHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        if not _is_https(resolved_base_url):
            raise MoxieHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)

        if config.fanout is not None:
            # Returned as is, so the pipeline reads the framework resource directly.
            return _fanout_resource(
                config, _paced_client_config(client_config, api_key), team_id, job_id, resumable_source_manager
            )
        if endpoint == "time_entries":
            return iter_time_entries(fetch_time_entries, datetime.now(UTC))
        return items()

    has_partition_key = config.partition_key is not None
    return SourceResponse(
        name=endpoint,
        items=source_items,
        primary_keys=config.primary_keys,
        # Full-refresh replace: there's no incremental watermark to checkpoint, but an explicit sort
        # still guards against a page-boundary shuffle on the (single, unpaginated) response.
        sort_mode="asc",
        partition_mode="datetime" if has_partition_key else None,
        partition_format="month" if has_partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(
    base_url: Optional[str], api_key: str, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)

    if not host:
        return False, "That doesn't look like a Moxie workspace base URL."

    # The host is fully customer-controlled (per-workspace pod), so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    if not _is_https(resolved_base_url):
        return False, HTTP_NOT_ALLOWED_ERROR

    # List Clients takes no parameters and needs no scope beyond the API key itself, so it's the
    # cheapest probe available and doubles as the request the `clients` table itself makes.
    url = f"{resolved_base_url}{MOXIE_API_PATH_PREFIX}/clients/list"
    is_valid, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"X-API-KEY": api_key, "Accept": "application/json"},
        allow_redirects=False,
    )
    if is_valid:
        return True, None
    if status == 401:
        return False, "Moxie rejected the API key. Check the key and workspace base URL, then try again."
    if status == 403:
        return False, "The Moxie API key does not have permission for this workspace."
    return False, "Could not connect to Moxie with the given credentials."
