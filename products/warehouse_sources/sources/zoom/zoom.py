import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast
from urllib.parse import quote

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    OAuth2Auth,
    OAuth2GrantType,
    Resource,
    ResponseAction,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SourceResponse,
    create_response_hooks,
    frozen,
    make_parent_key_name,
    make_tracked_session,
    reach_safe_point,
    rest_api_resource,
    rest_api_resources,
    validate_via_probe,
)
from products.warehouse_sources.sources.zoom.settings import ZOOM_ENDPOINTS, ZoomEndpointConfig

ZOOM_API_BASE = "https://api.zoom.us/v2"
ZOOM_OAUTH_URL = "https://zoom.us/oauth/token"

# Zoom paginates every list endpoint with an opaque `next_page_token` carried in the body and echoed
# back as a query param; the framework's cursor paginator stops when the token comes back empty.
_CURSOR_PATH = "next_page_token"
_CURSOR_PARAM = "next_page_token"

# The host report only covers the last six months: the current month and the five full months before it.
_REPORT_FULL_MONTHS = 5
_REPORT_TYPES = ("active", "inactive")
# Lower bound for a user whose row carries no `created_at`: Zoom opened to the public in January 2013.
_EARLIEST_RECORDING_DATE = date(2013, 1, 1)

# A parent this endpoint can't serve (a user without the relevant license or plan, a meeting that
# never took place) returns 400/404; skip that parent without aborting the whole sync (an empty page
# that stops this parent's pagination). Any other non-2xx still raises. Code 300 is an invalid or
# expired `next_page_token`: ignoring it would silently drop the rest of that parent's pages, so fail
# the request instead and let the run retry.
_PER_PARENT_RESPONSE_ACTIONS: list[ResponseAction] = [
    {
        "status_code": 400,
        "json_field": "code",
        "json_values": [300],
        "action": "retry",
        "message": "Zoom next_page_token is invalid or expired",
    },
    {"status_code": 400, "action": "ignore"},
    {"status_code": 404, "action": "ignore"},
]

# Zoom documents only 404 for a user without recordings (codes 1001 and 3301). Any 400, such as a
# missing scope, must fail the sync instead of returning an empty table.
_RECORDING_RESPONSE_ACTIONS: list[ResponseAction] = [
    _PER_PARENT_RESPONSE_ACTIONS[0],
    {"status_code": 404, "action": "ignore"},
]
# The users list defaults to active users, but deactivated users keep their cloud recordings.
_RECORDING_USER_STATUSES = ("active", "inactive")
# Appended to `share_url` or `play_url`, this passcode opens a protected recording.
_RECORDING_SECRET_FIELDS = ("recording_play_passcode",)


@dataclasses.dataclass(frozen=False)
class ZoomResumeConfig:
    # Top-level (users): the opaque cursor for the next page. Kept under its original name so state
    # saved by the previous implementation still deserializes.
    next_page_token: str = ""
    # Retained for backwards compatibility with state saved by the previous fan-out implementation
    # (`ResumableSourceManager` reconstructs the dataclass from saved keys). No longer written.
    user_index: int = 0
    # Fan-out (meetings/webinars): the framework's dependent-resource resume state
    # (`{"completed": [...], "current": ..., "child_state": ...}`).
    fanout_state: Optional[dict[str, Any]] = None


def _oauth_auth(account_id: str, client_id: str, client_secret: str) -> OAuth2Auth:
    """Server-to-Server OAuth for Zoom: exchange the account credentials for a short-lived bearer
    token (Basic client auth, `account_id` in the token-request body), minted lazily and re-minted
    before expiry by the framework. Using the framework auth keeps the client secret and the minted
    token redacted from logs and error messages."""
    return OAuth2Auth(
        token_url=ZOOM_OAUTH_URL,
        client_id=client_id,
        client_secret=client_secret,
        grant_type=cast(OAuth2GrantType, "account_credentials"),
        client_auth_method="basic",
        extra_token_request_params={"account_id": account_id},
    )


def _client_config(account_id: str, client_id: str, client_secret: str) -> ClientConfig:
    return {
        "base_url": ZOOM_API_BASE,
        "auth": _oauth_auth(account_id, client_id, client_secret),
        "paginator": JSONResponseCursorPaginator(cursor_path=_CURSOR_PATH, cursor_param=_CURSOR_PARAM),
    }


def _top_level_resource(
    client_config: ClientConfig,
    config: ZoomEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZoomResumeConfig],
) -> Resource:
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page_token:
            initial_paginator_state = {"cursor": resume.next_page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(ZoomResumeConfig(next_page_token=state["cursor"]))

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {"page_size": config.page_size, **config.params},
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _encode_uuid(uuid: str) -> str:
    # Zoom UUIDs are base64 and can hold `/`, `+` and `=`. Zoom asks for a double-encoded UUID when it
    # starts with `/` or contains `//`, and a single-encoded one otherwise.
    encoded = quote(uuid, safe="")
    if uuid.startswith("/") or "//" in uuid:
        encoded = quote(encoded, safe="")
    return encoded


def _row_map(config: ZoomEndpointConfig) -> Optional[Callable[[dict[str, Any]], dict[str, Any]]]:
    parent = config.parent
    renames = (
        {make_parent_key_name(parent, field): column for field, column in config.parent_columns.items()}
        if parent is not None
        else {}
    )
    if not renames and not config.adds_uuid_path:
        return None

    def row_map(row: dict[str, Any]) -> dict[str, Any]:
        for parent_key, column in renames.items():
            row[column] = row.pop(parent_key, None)
        if config.adds_uuid_path and row.get("uuid"):
            row["_uuid_path"] = _encode_uuid(row["uuid"])
        return row

    return row_map


def _resource_chain(config: ZoomEndpointConfig) -> list[ZoomEndpointConfig]:
    chain = [config]
    while chain[0].parent is not None:
        chain.insert(0, ZOOM_ENDPOINTS[chain[0].parent])
    return chain


def _resource_config(config: ZoomEndpointConfig) -> EndpointResource:
    params: dict[str, Any] = {**config.params}
    if config.paginated:
        params["page_size"] = config.page_size
    endpoint: Endpoint = {"path": config.path, "params": params, "data_selector": config.data_key}
    if not config.paginated:
        endpoint["paginator"] = "single_page"

    resource: EndpointResource = {"name": config.name, "endpoint": endpoint}
    if config.parent is not None:
        params[config.parent_param] = {"type": "resolve", "resource": config.parent, "field": config.parent_field}
        resource["include_from_parent"] = list(config.parent_columns)
        endpoint["response_actions"] = list(_PER_PARENT_RESPONSE_ACTIONS)
    row_map = _row_map(config)
    if row_map is not None:
        resource["data_map"] = row_map
    return resource


def supports_resume(endpoint: str) -> bool:
    config = ZOOM_ENDPOINTS[endpoint]
    # The REST framework checkpoints a fan-out with one dependent level only.
    return not config.monthly_windows and len(_resource_chain(config)) <= 2


def _fan_out_resource(
    client_config: ClientConfig,
    config: ZoomEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZoomResumeConfig],
) -> Resource:
    # The framework resumes a fan-out with one dependent level only. A chained fan-out (e.g.
    # participants <- instances <- meetings <- users) gets no resume hook and re-reads on retry.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(ZoomResumeConfig(fanout_state=state))

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [_resource_config(level) for level in _resource_chain(config)],
    }

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    resource = next(r for r in resources if r.name == config.name)
    if config.adds_uuid_path:
        # `_uuid_path` only exists to build the child request path; keep it out of the table.
        resource.add_map(_drop_uuid_path)
    return resource


def _drop_uuid_path(row: dict[str, Any]) -> dict[str, Any]:
    row.pop("_uuid_path", None)
    return row


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _next_month_start(day: date) -> date:
    return (day.replace(day=1) + timedelta(days=32)).replace(day=1)


@frozen
class DateWindow:
    start: date
    end: date


def month_windows(start: date, end: date) -> Iterator[DateWindow]:
    """Calendar-month windows from `start` to `end`, both inclusive. The first window starts at `start`."""
    current = start
    while current <= end:
        next_start = _next_month_start(current)
        yield DateWindow(start=current, end=min(next_start - timedelta(days=1), end))
        current = next_start


def _as_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value).date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed.astimezone(UTC) if parsed.tzinfo else parsed).date()


def _pages(
    client: RESTClient,
    path: str,
    params: dict[str, Any],
    data_key: str,
    response_actions: Optional[list[ResponseAction]] = None,
) -> Iterator[list[dict[str, Any]]]:
    for page in client.paginate(
        path,
        params=params,
        paginator=JSONResponseCursorPaginator(cursor_path=_CURSOR_PATH, cursor_param=_CURSOR_PARAM),
        data_selector=data_key,
        hooks=create_response_hooks(response_actions),
    ):
        if page:
            yield page
        # Every row read so far has been handed on, so the run can stop here.
        reach_safe_point()


def _report_users_rows(
    client: RESTClient, config: ZoomEndpointConfig, today: date, last_value: Any
) -> Iterator[list[dict[str, Any]]]:
    earliest = _month_start(today)
    for _ in range(_REPORT_FULL_MONTHS):
        earliest = _month_start(earliest - timedelta(days=1))
    # The cursor is the start of the newest month read, which may have been partial; read it again.
    cursor = _as_date(last_value)
    start = max(earliest, _month_start(cursor)) if cursor else earliest

    for window in month_windows(start, today):
        for report_type in _REPORT_TYPES:
            params = {
                "type": report_type,
                "from": window.start.isoformat(),
                "to": window.end.isoformat(),
                "page_size": config.page_size,
            }
            for page in _pages(client, config.path, params, config.data_key):
                yield [
                    {
                        **row,
                        "period_start": window.start.isoformat(),
                        "period_end": window.end.isoformat(),
                        "report_type": report_type,
                    }
                    for row in page
                ]


def _recordings_rows(
    client: RESTClient, config: ZoomEndpointConfig, today: date, last_value: Any
) -> Iterator[list[dict[str, Any]]]:
    users = ZOOM_ENDPOINTS["users"]
    cursor = _as_date(last_value)
    # Zoom's `next_page_token` expires after 15 minutes, and walking the recording history of one
    # page of users can take longer, so the whole user list is read first.
    user_starts: list[tuple[str, date]] = []
    for status in _RECORDING_USER_STATUSES:
        user_params = {"status": status, "page_size": users.page_size}
        for user_page in _pages(client, users.path, user_params, users.data_key):
            for user in user_page:
                user_id = user.get("id")
                if not user_id:
                    continue
                # No recording predates the user, so a first sync starts at the user's creation date.
                start = _as_date(user.get("created_at")) or _EARLIEST_RECORDING_DATE
                if cursor is not None:
                    start = max(start, cursor)
                user_starts.append((str(user_id), start))

    for user_id, start in user_starts:
        path = config.path.format(**{config.parent_param: quote(user_id, safe="")})
        for window in month_windows(start, today):
            params = {"from": window.start.isoformat(), "to": window.end.isoformat(), "page_size": config.page_size}
            for page in _pages(client, path, params, config.data_key, _RECORDING_RESPONSE_ACTIONS):
                yield [_without_secrets(row) for row in page]


def _without_secrets(row: dict[str, Any]) -> dict[str, Any]:
    for field_name in _RECORDING_SECRET_FIELDS:
        row.pop(field_name, None)
    return row


_WINDOWED_ITERATORS: dict[
    str, Callable[[RESTClient, ZoomEndpointConfig, date, Any], Iterator[list[dict[str, Any]]]]
] = {
    "report_users": _report_users_rows,
    "recordings": _recordings_rows,
}


def _windowed_rows(
    account_id: str,
    client_id: str,
    client_secret: str,
    config: ZoomEndpointConfig,
    last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    client = RESTClient(
        base_url=ZOOM_API_BASE,
        auth=_oauth_auth(account_id, client_id, client_secret),
        # HTTP samples are stored before rows reach `_without_secrets`, so recording responses skip them.
        capture=config.name != "recordings",
    )
    today = datetime.now(UTC).date()
    yield from _WINDOWED_ITERATORS[config.name](client, config, today, last_value)


def zoom_source(
    account_id: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZoomResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = ZOOM_ENDPOINTS[endpoint]
    partitioning: dict[str, Any] = {
        "partition_count": 1,
        "partition_size": 1,
        "partition_mode": "datetime" if config.partition_key else None,
        "partition_format": "week" if config.partition_key else None,
        "partition_keys": [config.partition_key] if config.partition_key else None,
    }

    if config.monthly_windows:
        last_value = db_incremental_field_last_value if should_use_incremental_field else None
        return SourceResponse(
            name=endpoint,
            items=lambda: _windowed_rows(account_id, client_id, client_secret, config, last_value),
            primary_keys=config.primary_keys,
            supports_resume=False,
            **partitioning,
        )

    client_config = _client_config(account_id, client_id, client_secret)
    if config.parent is not None:
        resource = _fan_out_resource(client_config, config, team_id, job_id, resumable_source_manager)
    else:
        resource = _top_level_resource(client_config, config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        column_hints=resource.column_hints,
        supports_resume=supports_resume(endpoint),
        **partitioning,
    )


def validate_credentials(
    account_id: str,
    client_id: str,
    client_secret: str,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    auth = _oauth_auth(account_id, client_id, client_secret)

    # Minting the token verifies the account ID / client ID / secret without touching a scoped
    # endpoint. Any failure here means the credentials themselves are wrong.
    try:
        auth._obtain_token()
    except Exception:
        return False, "Invalid Zoom account ID, client ID, or client secret"

    # At source-create (no specific schema) a genuine token is enough — users may only grant scopes
    # for the endpoints they intend to sync, so don't probe a scoped endpoint here.
    if schema_name is None:
        return True, None

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(client_secret,)),
        f"{ZOOM_API_BASE}/users?page_size=1",
        auth=auth,
    )
    if ok:
        return True, None
    if status in (401, 403):
        return (
            False,
            "Zoom credentials are valid but lack the required scopes. Grant user/meeting/webinar read scopes and retry.",
        )
    return False, f"Zoom API returned an unexpected status ({status})"
