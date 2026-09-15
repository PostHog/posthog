import re
import dataclasses
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast
from urllib.parse import parse_qs, quote, urlsplit

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.settings import (
    BAMBOOHR_ENDPOINTS,
    EMPLOYEE_TABLE_EMPLOYEE_ID,
    EMPLOYEE_TABLE_LAST_CHANGED,
    GOAL_ID,
    BambooHREndpointConfig,
    ChunkedDateWindow,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# BambooHR's API is served through a single gateway host; the company subdomain is a path segment.
# Confirmed live: the gateway returns 401 (not 404) for the versioned paths in settings.py, so the route
# shape is correct.
BAMBOOHR_API_HOST = "https://api.bamboohr.com/api/gateway.php"
# Basic auth uses the API key as the username and any non-empty string as the password.
BAMBOOHR_BASIC_AUTH_PASSWORD = "x"
# Credential validation is a single cheap probe; keep it snappy so source creation doesn't feel hung.
VALIDATE_TIMEOUT_SECONDS = 10
# Bounds each sync request, so a gateway that accepts the connection then stalls cannot hold a
# worker open indefinitely.
SYNC_TIMEOUT_SECONDS = 120
# Time-off endpoints require an explicit window; widen it enough to capture all history and pending future requests.
TIME_OFF_WINDOW_START = "2000-01-01"
TIME_OFF_FUTURE_DAYS = 730
# The employee-table history endpoints require a `since` cursor, so a full refresh needs a floor
# old enough to predate any company's records.
EMPLOYEE_TABLE_HISTORY_START = datetime(2000, 1, 1, tzinfo=UTC)
# BambooHR's page-numbered endpoints count from zero.
FIRST_PAGE_NUMBER = 0
# Endpoint whose rows the goal-comment iterator walks to reach each goal.
GOAL_COMMENTS_PARENT = "employee_goals"

# A BambooHR company subdomain is the "<company>" slug from <company>.bamboohr.com — letters, digits,
# and hyphens only. It's an editable, non-secret field spliced straight into the request path, so pin
# it to this allowlist before building any URL. Without it a value like "acme/v1/employees/123?" would
# inject extra path segments / query params and redirect the authenticated request (which carries the
# API key in its Basic auth header) at an arbitrary BambooHR endpoint.
SUBDOMAIN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
INVALID_SUBDOMAIN_MESSAGE = (
    "Invalid BambooHR company subdomain. Use only the company name from your BambooHR URL "
    "(letters, digits, and hyphens)."
)


def _validate_subdomain(subdomain: str) -> None:
    if not SUBDOMAIN_PATTERN.fullmatch(subdomain):
        raise ValueError(f"Invalid BambooHR subdomain: {subdomain!r}")


@dataclasses.dataclass(frozen=False)
class BambooHRResumeConfig:
    next_url: str


def _base_url(subdomain: str) -> str:
    _validate_subdomain(subdomain)
    return f"{BAMBOOHR_API_HOST}/{subdomain}"


class BambooHRBasicAuth(HttpBasicAuth):
    """Basic auth where the *username* is the secret (the API key), so redact it instead of the password."""

    def secret_values(self) -> tuple[str, ...]:
        return (self.username,) if self.username else ()


def _next_url(payload: Any) -> str | None:
    """Follow BambooHR's cursor pagination if the response advertises a next page.

    Classic endpoints (directory, meta, time off) return everything in a single response with no
    ``_links``, so this yields once. Cursor-paginated endpoints expose a full URL under ``_links.next``.
    """
    if not isinstance(payload, dict):
        return None
    links = payload.get("_links")
    if links is None:
        links = payload.get("links")
    if not isinstance(links, dict):
        return None
    next_link = links.get("next")
    # Only follow pagination URLs that stay on the canonical BambooHR gateway host, so a
    # tampered or compromised API response can't point our authenticated request at an internal
    # address (SSRF) and leak the API key carried in the Basic auth header.
    if isinstance(next_link, str) and next_link.startswith(BAMBOOHR_API_HOST):
        return next_link
    return None


class BambooHRPaginator(BaseNextUrlPaginator):
    """Follows the full next-page URL BambooHR returns under ``_links.next`` (or ``links.next``),
    pinned to the gateway host via ``_next_url``."""

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        next_url = _next_url(payload)
        if next_url:
            self._next_url = next_url
            self._has_next_page = True
        else:
            self._has_next_page = False

    def __str__(self) -> str:
        return "BambooHRPaginator(_links.next|links.next)"


def _page_from_url(url: Any) -> int | None:
    if not isinstance(url, str):
        return None
    values = parse_qs(urlsplit(url).query).get("page")
    if not values:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


class BambooHRApplicationsPaginator(BasePaginator):
    """Walks the ATS applications envelope (``paginationComplete`` plus ``nextPageUrl``).

    ``nextPageUrl`` is read only for the page number it carries, never followed: BambooHR builds
    it against the company's own domain while we call the same API through the gateway host the
    API key was issued for, so following it verbatim would leave that host.
    """

    def __init__(self, page_param: str = "page") -> None:
        super().__init__()
        self.page_param = page_param
        # None until the first response tells us which page the API served by default.
        self.page: int | None = None

    def _apply(self, request: Request) -> None:
        if self.page is None:
            return
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or payload.get("paginationComplete") or not data:
            self._has_next_page = False
            return
        next_page = _page_from_url(payload.get("nextPageUrl"))
        if next_page is None:
            if not payload.get("nextPageUrl"):
                self._has_next_page = False
                return
            # A next link we cannot read a page number out of still means more rows, so step
            # forward rather than truncating the table. The step is always +1 on the page we
            # last asked for, so the walk cannot revisit a page it already fetched.
            next_page = (self.page or 0) + 1
        self.page = next_page
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def __str__(self) -> str:
        return "BambooHRApplicationsPaginator(paginationComplete|nextPageUrl)"


def _paginator_for(config: BambooHREndpointConfig) -> BasePaginator:
    if config.pagination == "single":
        return SinglePagePaginator()
    if config.pagination == "page_number":
        return PageNumberPaginator(base_page=FIRST_PAGE_NUMBER, stop_after_empty_page=True)
    if config.pagination == "ats_applications":
        return BambooHRApplicationsPaginator()
    return BambooHRPaginator()


def _selector_for(config: BambooHREndpointConfig) -> tuple[str | None, bool]:
    """Map an endpoint's response layout to a (data_selector, data_selector_required) pair.

    - "dict" shape (e.g. ``meta/users`` — ``{"<id>": {...}}``): the ``*`` wildcard flattens the
      object to its values; not required so an empty account (empty object) is a legit 0-row page.
    - "object" shape (a by-id detail endpoint): no selector, and not required, so the single
      object body is wrapped as one row instead of failing the list check.
    - Enveloped list (``data_key``): select the key and fail loudly when it's absent (an API
      change) rather than silently syncing zero rows.
    - Bare list body: no selector; require a list so an unexpected 200 envelope fails loudly
      instead of being wrapped as a garbage row.
    """
    if config.data_shape == "dict":
        return "*", False
    if config.data_shape == "object":
        # A by-id detail body is one record; the client wraps it into a single row.
        return None, False
    if config.data_key is not None:
        return config.data_key, True
    return None, True


def _endpoint_extra(config: BambooHREndpointConfig) -> Endpoint:
    """The response-shape half of an endpoint config, for the fan-out helper's endpoint overrides."""
    data_selector, data_selector_required = _selector_for(config)
    # Parent and child are paginated separately, so each side needs its own paginator instance.
    extra: Endpoint = {"data_selector_required": data_selector_required, "paginator": _paginator_for(config)}
    if data_selector is not None:
        extra["data_selector"] = data_selector
    return extra


def _rest_client(base_url: str, api_key: str) -> RESTClient:
    return RESTClient(
        base_url=base_url,
        headers={"Accept": "application/json"},
        auth=BambooHRBasicAuth(username=api_key, password=BAMBOOHR_BASIC_AUTH_PASSWORD),
        # Default for the streams this client drives directly; callers that need an endpoint's
        # own paginator pass one to `paginate`.
        paginator=SinglePagePaginator(),
        # Pins every request to the gateway host the API key was issued for.
        allowed_hosts=[],
        request_timeout=SYNC_TIMEOUT_SECONDS,
    )


def _employee_table_rows(body: Any) -> Iterator[dict[str, Any]]:
    """Flatten one ``employees/changed/tables/{table}`` response into rows.

    The response groups rows under a map of employee id — ``{"employees": {"123": {"lastChanged":
    ..., "rows": [...]}}}`` — so the employee id and the change timestamp exist only on the map
    entry. Both are stamped onto every row; the map key wins over any ``employeeId`` in the row
    because it is what the API keyed the group by.
    """
    employees = body.get("employees") if isinstance(body, dict) else None
    if not isinstance(employees, dict):
        raise ValueError(
            "Required an 'employees' object in the response body, got "
            f"{type(employees).__name__}. The API response shape may have changed."
        )
    for employee_id, entry in employees.items():
        if not isinstance(entry, dict):
            continue
        last_changed = entry.get(EMPLOYEE_TABLE_LAST_CHANGED)
        for row in entry.get("rows") or []:
            yield {
                **row,
                EMPLOYEE_TABLE_EMPLOYEE_ID: str(employee_id),
                EMPLOYEE_TABLE_LAST_CHANGED: last_changed,
            }


def _employee_table_pages(
    client: RESTClient, config: BambooHREndpointConfig, since: datetime
) -> Iterator[list[dict[str, Any]]]:
    for page in client.paginate(path=config.path, params={"since": since.isoformat()}):
        for body in page:
            rows = list(_employee_table_rows(body))
            # Rows arrive grouped by employee, in no order — sort so the cursor really is
            # ascending and the pipeline's watermark can only move forward over rows we yielded.
            rows.sort(key=_last_changed_sort_key)
            if rows:
                yield rows


def _last_changed_sort_key(row: dict[str, Any]) -> datetime:
    return parse_datetime_value(row.get(EMPLOYEE_TABLE_LAST_CHANGED)) or datetime.min.replace(tzinfo=UTC)


def _chunked_window_pages(
    client: RESTClient, config: BambooHREndpointConfig, window: ChunkedDateWindow
) -> Iterator[list[dict[str, Any]]]:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=window.history_days)
    while start <= today:
        end = min(start + timedelta(days=window.chunk_days - 1), today)
        yield from _window_pages(client, config, start, end)
        start = end + timedelta(days=1)


def _window_pages(
    client: RESTClient, config: BambooHREndpointConfig, start: date, end: date
) -> Iterator[list[dict[str, Any]]]:
    params = {"start": start.isoformat(), "end": end.isoformat()}
    for page in client.paginate(path=config.path, params=params, data_selector_required=True):
        if page:
            yield page


def _format_path(path: str, **values: Any) -> str:
    """Bind path placeholders to ids taken from an API response.

    The ids are percent-encoded because they land in the request path: an id carrying a ``/`` or
    a ``?`` would otherwise add path segments or query params to an authenticated request.
    """
    for key, value in values.items():
        path = path.replace("{" + key + "}", quote(str(value), safe=""))
    return path


def _rows_for(
    client: RESTClient, config: BambooHREndpointConfig, path: str | None = None, params: dict[str, Any] | None = None
) -> Iterator[dict[str, Any]]:
    data_selector, data_selector_required = _selector_for(config)
    for page in client.paginate(
        path=path or config.path,
        params=config.params if params is None else params,
        paginator=_paginator_for(config),
        data_selector=data_selector,
        data_selector_required=data_selector_required,
    ):
        yield from page


def _goal_comment_pages(client: RESTClient, config: BambooHREndpointConfig) -> Iterator[list[dict[str, Any]]]:
    """Walk the directory, then each employee's goals, then each goal's comments.

    Two fan-out levels deep, which the single-hop dependent-resource helper cannot express. A
    comment row names neither the goal nor the employee it belongs to, so both are stamped on.
    """
    goals_config = BAMBOOHR_ENDPOINTS[GOAL_COMMENTS_PARENT]
    goals_fanout = goals_config.fanout
    if goals_fanout is None:
        raise ValueError(f"'{GOAL_COMMENTS_PARENT}' must fan out over a parent endpoint")
    employees_config = BAMBOOHR_ENDPOINTS[goals_fanout.parent_name]

    for employee in _rows_for(client, employees_config):
        employee_id = employee.get(goals_fanout.resolve_field)
        if employee_id is None:
            continue
        goals_path = _format_path(goals_config.path, employeeId=employee_id)
        for goal in _rows_for(client, goals_config, path=goals_path, params=dict(goals_fanout.child_params)):
            goal_id = goal.get("id")
            if goal_id is None:
                continue
            path = _format_path(config.path, employeeId=employee_id, goalId=goal_id)
            rows = [
                {**row, EMPLOYEE_TABLE_EMPLOYEE_ID: str(employee_id), GOAL_ID: str(goal_id)}
                for row in _rows_for(client, config, path=path)
            ]
            if rows:
                yield rows


def _employee_table_since(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> datetime:
    if not should_use_incremental_field:
        return EMPLOYEE_TABLE_HISTORY_START
    return parse_datetime_value(db_incremental_field_last_value) or EMPLOYEE_TABLE_HISTORY_START


def bamboohr_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BambooHRResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = BAMBOOHR_ENDPOINTS[endpoint]
    base_url = _base_url(subdomain)

    if config.custom_iterator == "goal_comments":
        client = _rest_client(base_url, api_key)
        return SourceResponse(
            name=endpoint,
            items=lambda: _goal_comment_pages(client, config),
            primary_keys=config.primary_keys,
        )

    if config.employee_table is not None:
        client = _rest_client(base_url, api_key)
        since = _employee_table_since(should_use_incremental_field, db_incremental_field_last_value)
        return SourceResponse(
            name=endpoint,
            items=lambda: _employee_table_pages(client, config, since),
            primary_keys=config.primary_keys,
        )

    if config.chunked_date_window is not None:
        client = _rest_client(base_url, api_key)
        window = config.chunked_date_window
        return SourceResponse(
            name=endpoint,
            items=lambda: _chunked_window_pages(client, config, window),
            primary_keys=config.primary_keys,
        )

    client_config: ClientConfig = {
        "base_url": base_url,
        "headers": {"Accept": "application/json"},
        # Auth goes through the framework config so the API key is redacted from logs;
        # only the non-secret Accept header is set on the session.
        "auth": BambooHRBasicAuth(username=api_key, password=BAMBOOHR_BASIC_AUTH_PASSWORD),
        "paginator": _paginator_for(config),
    }

    if config.fanout is not None:
        parent_config = BAMBOOHR_ENDPOINTS[config.fanout.parent_name]
        resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=BAMBOOHR_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                # BambooHR list endpoints take no page-size parameter.
                page_size_param=None,
                parent_endpoint_extra=_endpoint_extra(parent_config),
                child_endpoint_extra=_endpoint_extra(config),
            ),
        )
        return SourceResponse(
            name=endpoint,
            items=lambda: resource,
            primary_keys=config.primary_keys,
        )

    params: dict[str, Any] = dict(config.params)
    if config.requires_date_window:
        params["start"] = TIME_OFF_WINDOW_START
        params["end"] = (datetime.now(UTC) + timedelta(days=TIME_OFF_FUTURE_DAYS)).strftime("%Y-%m-%d")

    data_selector, data_selector_required = _selector_for(config)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": data_selector,
                    "data_selector_required": data_selector_required,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            # Guard the persisted resume URL too — only ever saved from _next_url (host-pinned),
            # but re-check so a tampered Redis state can't redirect our authenticated request.
            if not resume.next_url.startswith(BAMBOOHR_API_HOST):
                raise ValueError(f"BambooHR resume state contains an unexpected URL: {resume.next_url!r}")
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the hook fires AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on PK) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(BambooHRResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every BambooHR stream is full-refresh (see settings.py)
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
    )


def validate_credentials(subdomain: str, api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Cheap probe against ``meta/fields`` to confirm the subdomain + API key are genuine.

    A 403 means the key is valid but lacks scope for this endpoint — accept it at source-create
    (``schema_name is None``) since users may only grant the scopes they intend to sync.
    """
    try:
        url = f"{_base_url(subdomain)}/v1/meta/fields"
    except ValueError:
        return False, INVALID_SUBDOMAIN_MESSAGE

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Accept": "application/json"},
        auth=BambooHRBasicAuth(username=api_key, password=BAMBOOHR_BASIC_AUTH_PASSWORD),
        timeout=VALIDATE_TIMEOUT_SECONDS,
    )

    if ok:
        return True, None
    if status is None:
        return False, "Could not connect to BambooHR. Check the company subdomain and try again."
    if status == 401:
        return False, "Invalid BambooHR API key."
    if status == 404:
        return False, "BambooHR company subdomain not found. Use the subdomain from your BambooHR URL."
    if status == 403:
        if schema_name is None:
            return True, None
        return False, "Your BambooHR API key does not have permission to access this data."
    return False, f"BambooHR API returned an unexpected status code: {status}"
