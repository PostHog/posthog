from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

from requests import PreparedRequest

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import reach_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.settings import (
    MY_HOURS_ENDPOINTS,
    PROJECT_TASKS_ENDPOINT,
    TIME_LOGS_ENDPOINT,
    TIME_LOGS_FIRST_DATE,
    TIME_LOGS_WINDOW_DAYS,
)

MY_HOURS_BASE_URL = "https://api2.myhours.com/api"
# Cheap list endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/Clients"


class MyHoursApiKeyAuth(AuthConfigBase):
    """My Hours expects the literal ``apikey `` prefix before the key on the Authorization header;
    omitting it (or using ``Bearer``) returns 400/401. Framework ``bearer``/``api_key`` auth can't
    emit that scheme, so this thin auth carries the raw key (declared secret so it's redacted from
    every logged URL/header and every raised error message)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"apikey {self.api_key}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.api_key,) if self.api_key else ()


def _headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": MY_HOURS_BASE_URL,
        "headers": _headers(),
        "auth": MyHoursApiKeyAuth(api_key),
        # The list endpoints are unpaginated: a single request returns the whole collection.
        "paginator": SinglePagePaginator(),
    }


@frozen
class _TimeLogWindow:
    date_from: date
    date_to: date


def _start_date(last_value: Any) -> date:
    if isinstance(last_value, datetime):
        return last_value.date()
    if isinstance(last_value, date):
        return last_value
    if isinstance(last_value, str):
        return datetime.fromisoformat(last_value).date()
    return TIME_LOGS_FIRST_DATE


def _time_log_windows(start: date, today: date) -> Iterator[_TimeLogWindow]:
    # A watermark past today (a log booked ahead) still re-reads the current window.
    start = max(min(start, today), TIME_LOGS_FIRST_DATE)
    while start <= today:
        end = min(start + timedelta(days=TIME_LOGS_WINDOW_DAYS - 1), today)
        yield _TimeLogWindow(date_from=start, date_to=end)
        start = end + timedelta(days=1)


def _time_log_pages(client: RESTClient, start: date) -> Iterator[list[dict[str, Any]]]:
    # One day past today in UTC covers accounts in timezones already on the next day.
    today = datetime.now(UTC).date() + timedelta(days=1)
    for window in _time_log_windows(start, today):
        rows: list[dict[str, Any]] = []
        for page in client.paginate(
            path=MY_HOURS_ENDPOINTS[TIME_LOGS_ENDPOINT].path,
            method="put",
            json={
                "options": {
                    "dateFrom": window.date_from.isoformat(),
                    "dateTo": window.date_to.isoformat(),
                    "logType": "Time",
                    "userIds": [],
                    "clientIds": [],
                    "projectIds": [],
                    "taskNames": [],
                    "tagNames": [],
                    "statuses": [],
                }
            },
            data_selector="data",
            data_selector_malformed_retryable=True,
        ):
            rows.extend(page)
        if not rows:
            reach_safe_point()
            continue
        # The report's row order is not documented. Sorting each window keeps the incremental
        # watermark ascending across batches.
        rows.sort(key=lambda row: row.get("date") or "")
        yield rows


def _flatten_task_lists(task_list: dict[str, Any]) -> list[dict[str, Any]]:
    shared = {
        "projectId": task_list.get("projectId"),
        "taskListName": task_list.get("listName"),
        "taskListNo": task_list.get("listNo"),
    }
    tasks = [
        *(task_list.get("incompletedTasks") or []),
        *(task_list.get("completedTasks") or []),
        *(task_list.get("archivedTasks") or []),
    ]
    return [{**task, **shared} for task in tasks]


def my_hours_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = MY_HOURS_ENDPOINTS[endpoint]

    if endpoint == TIME_LOGS_ENDPOINT:
        client = RESTClient(
            base_url=MY_HOURS_BASE_URL,
            headers=_headers(),
            auth=MyHoursApiKeyAuth(api_key),
            paginator=SinglePagePaginator(),
        )
        start = _start_date(db_incremental_field_last_value if should_use_incremental_field else None)
        return SourceResponse(
            name=endpoint,
            items=lambda: _time_log_pages(client, start),
            primary_keys=config.primary_keys,
            partition_count=1,
            partition_size=1,
        )

    if config.fanout is not None:
        resource = cast(
            Resource,
            build_dependent_resource(
                endpoint_configs=MY_HOURS_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=_client_config(api_key),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                page_size_param=None,
            ),
        )
        if endpoint == PROJECT_TASKS_ENDPOINT:
            resource = resource.add_map(_flatten_task_lists)
        return SourceResponse(
            name=endpoint,
            items=lambda: resource,
            primary_keys=config.primary_keys,
            partition_count=1,
            partition_size=1,
        )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # My Hours list endpoints return a bare JSON array. A 200 whose body isn't a
                    # list is treated as transient (a truncating proxy / stray error object) and the
                    # request is reissued, matching the hand-rolled retryable behavior.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers={"Authorization": f"apikey {api_key}", **_headers()}, redact_values=(api_key,)
    )
    try:
        response = session.get(f"{MY_HOURS_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to My Hours: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"My Hours returned HTTP {response.status_code}"

    return 200, None
