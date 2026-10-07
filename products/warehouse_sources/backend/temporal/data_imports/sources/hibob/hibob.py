from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.settings import (
    HIBOB_ENDPOINTS,
    NAMED_LISTS,
    TIME_OFF_CALENDARS,
    HiBobEndpointConfig,
)

HIBOB_BASE_URL = "https://api.hibob.com"

# HiBob rejects more than 5000 employee ids in one calendar search (400 tooManyEmployeeIds).
EMPLOYEE_ID_BATCH_SIZE = 5000
# Max page size the calendars search accepts.
CALENDAR_PAGE_LIMIT = 1000
REQUEST_TIMEOUT_SECONDS = 30


def validate_credentials(service_user_id: str, service_user_token: str) -> tuple[bool, str | None]:
    """Confirm the service user credentials are valid with a cheap tasks probe.

    Service users need explicit per-category permission grants (403); only 401
    means the credentials themselves are bad. Transport failures surface their
    real reason rather than masquerading as an auth error."""
    session = make_tracked_session(redact_values=(service_user_token,))
    session.auth = (service_user_id, service_user_token)
    try:
        response = session.get(f"{HIBOB_BASE_URL}/v1/tasks", timeout=10)
        if response.status_code == 401:
            return False, "Invalid HiBob Service User credentials"
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        session.close()


def _leaf_key(key: str) -> str:
    """HiBob returns calendar fields under JSON-pointer keys (e.g. `/employeeCalendar/employeeId`).
    Keep only the leaf segment so columns are clean; a flat key is returned unchanged."""
    return key.rsplit("/", 1)[-1] if "/" in key else key


def _leaf_keys_page(page: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{_leaf_key(key): value for key, value in item.items()} for item in page]


def _employee_history_page(page: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten bulk table results (`{employeeId, values: [...]}` per employee) into one row per entry."""
    rows: list[dict[str, Any]] = []
    for result in page:
        employee_id = result.get("employeeId")
        for value in result.get("values") or []:
            # The spec types each item as a `{values, restricted_columns}` wrapper, while the
            # single-employee table endpoints return bare entries, so accept both shapes.
            entries = value["values"] if isinstance(value.get("values"), list) else [value]
            rows.extend({**entry, "employeeId": employee_id} for entry in entries)
    return rows


PAGE_MAPPERS: dict[str, Callable[[list[dict[str, Any]]], list[dict[str, Any]]]] = {
    "employee_history": _employee_history_page,
    "pointer_keys": _leaf_keys_page,
}


def _map_pages(
    pages: Iterable[list[dict[str, Any]]], mapper: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
) -> Iterator[list[dict[str, Any]]]:
    for page in pages:
        yield mapper(page)


def _paginator(config: HiBobEndpointConfig) -> BasePaginator:
    if config.cursor_location is None:
        return SinglePagePaginator()
    return JSONResponseCursorPaginator(
        cursor_path="response_metadata.next_cursor",
        cursor_param="cursor",
        param_location=config.cursor_location,
        raise_on_repeated_cursor=True,
    )


def _iter_employee_ids(session: Any) -> Iterator[str]:
    employees_config = HIBOB_ENDPOINTS["employees"]
    response = session.post(
        f"{HIBOB_BASE_URL}{employees_config.path}",
        json=employees_config.body,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    for employee in response.json().get(employees_config.data_key, []):
        employee_id = employee.get("id")
        if employee_id is not None:
            # HiBob ids exceed JS safe-integer range, so send them back as strings.
            yield str(employee_id)


def _search_employee_calendars(session: Any, path: str, employee_ids: list[str]) -> Iterator[list[dict[str, Any]]]:
    cursor: str | None = None
    while True:
        body: dict[str, Any] = {
            "filters": [
                {"fieldId": "/employeeCalendar/employeeId", "operator": "equals", "values": employee_ids},
            ],
            "limit": CALENDAR_PAGE_LIMIT,
        }
        if cursor:
            body["cursor"] = cursor

        response = session.post(f"{HIBOB_BASE_URL}{path}", json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()

        items = data.get("items", [])
        if items:
            yield _leaf_keys_page(items)

        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break


def _time_off_calendars_rows(
    service_user_id: str, service_user_token: str, path: str
) -> Iterator[list[dict[str, Any]]]:
    # The search resolves the holiday calendar for a supplied set of employee ids, so fan out over
    # every employee. Repeated 401/403s trip HiBob's WAF, so auth errors fail loud (raise_for_status)
    # rather than retry — the tracked session only retries 429/5xx.
    session = make_tracked_session(redact_values=(service_user_token,))
    session.auth = (service_user_id, service_user_token)
    try:
        employee_ids = list(_iter_employee_ids(session))
        for start in range(0, len(employee_ids), EMPLOYEE_ID_BATCH_SIZE):
            batch = employee_ids[start : start + EMPLOYEE_ID_BATCH_SIZE]
            yield from _search_employee_calendars(session, path, batch)
    finally:
        session.close()


def _flatten_list_items(list_name: str, items: list[dict[str, Any]], parent_id: Any = None) -> Iterator[dict[str, Any]]:
    for item in items:
        children = item.get("children") or []
        yield {
            **{key: value for key, value in item.items() if key != "children"},
            "listName": list_name,
            "parentId": parent_id,
        }
        yield from _flatten_list_items(list_name, children, item.get("id"))


def _named_lists_rows(
    service_user_id: str, service_user_token: str, config: HiBobEndpointConfig
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(redact_values=(service_user_token,))
    session.auth = (service_user_id, service_user_token)
    try:
        response = session.get(f"{HIBOB_BASE_URL}{config.path}", params=config.params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    finally:
        session.close()

    # Accept the documented array of lists and an object keyed by list name, the shape older Bob docs show.
    named_lists = data.values() if isinstance(data, dict) else data
    rows: list[dict[str, Any]] = []
    for named_list in named_lists:
        rows.extend(_flatten_list_items(named_list.get("name"), named_list.get(config.data_key) or []))
    if rows:
        yield rows


def _since(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def hibob_source(
    service_user_id: str,
    service_user_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = HIBOB_ENDPOINTS[endpoint]

    if endpoint == TIME_OFF_CALENDARS:
        return SourceResponse(
            name=endpoint,
            items=lambda: _time_off_calendars_rows(service_user_id, service_user_token, config.path),
            primary_keys=list(config.primary_keys),
            partition_count=1,
            partition_size=1,
            sort_mode="asc",
        )

    if endpoint == NAMED_LISTS:
        return SourceResponse(
            name=endpoint,
            items=lambda: _named_lists_rows(service_user_id, service_user_token, config),
            primary_keys=list(config.primary_keys),
            partition_count=1,
            partition_size=1,
            sort_mode="asc",
        )

    # Basic auth carries the token; supplying it via the framework auth config redacts the
    # token from any raised error. Repeated 401/403s trip HiBob's WAF, so auth errors must
    # fail loud (raise_for_status) rather than retry — the client only retries 429/5xx.
    api_endpoint: Endpoint = {
        "path": config.path,
        "method": config.method,
        # A missing data key is a legit "no rows" answer (not a shape error), so the selector
        # stays optional — an absent key yields an empty page, matching the old behaviour.
        "data_selector": config.data_key,
    }
    if config.body is not None:
        # Copy, because the cursor paginator writes the cursor into the request body.
        api_endpoint["json"] = {**config.body}
    params = {**(config.params or {})}
    if config.since_days_ago is not None:
        params["since"] = _since(config.since_days_ago)
    if params:
        api_endpoint["params"] = params

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HIBOB_BASE_URL,
            "auth": {"type": "http_basic", "username": service_user_id, "password": service_user_token},
            "paginator": _paginator(config),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": api_endpoint,
            }
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)
    mapper = PAGE_MAPPERS.get(config.row_shape)

    return SourceResponse(
        name=endpoint,
        items=(lambda: _map_pages(resource, mapper)) if mapper else (lambda: resource),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
