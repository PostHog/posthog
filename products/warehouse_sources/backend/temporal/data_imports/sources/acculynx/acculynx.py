from collections.abc import Callable, Iterator
from dataclasses import field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.acculynx.settings import (
    API_ORIGIN,
    ENDPOINTS,
    MAX_JOB_RECORDS,
    PAGE_SIZE,
    PARENT_ENDPOINTS,
    AcculynxEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse


@frozen
class DateWindow:
    start: date
    end: date


@frozen
class AcculynxResumeConfig:
    windows: list[list[str]] = field(default_factory=list)
    paginator_state: dict[str, Any] | None = None
    finished: bool = False


def appointment_range(start: str | None, end: str | None) -> DateWindow:
    try:
        start_date = date.fromisoformat(start or "2000-01-01")
        end_date = date.fromisoformat(end) if end else datetime.now(UTC).date() + timedelta(days=90)
    except ValueError:
        raise ValueError("Enter appointment dates in YYYY-MM-DD format.") from None
    if start_date >= end_date:
        raise ValueError("The appointment end date must be after the start date.")
    return DateWindow(start=start_date, end=end_date)


class JobWindowTooLarge(Exception):
    pass


class AcculynxOffsetPaginator(OffsetPaginator):
    def __init__(self, offset_param: str, *, jobs: bool = False) -> None:
        super().__init__(limit=PAGE_SIZE, offset_param=offset_param, limit_param="pageSize", total_path="count")
        self.jobs = jobs

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        count, size, offset = body.get("count"), body.get("pageSize"), body.get("pageStartIndex")
        if not isinstance(count, int) or count < 0 or not isinstance(size, int) or size <= 0:
            raise ValueError("AccuLynx returned invalid pagination metadata.")
        if offset != self.offset:
            raise ValueError("AccuLynx returned an unexpected page offset. Check the API pagination parameters.")
        if self.jobs and count > MAX_JOB_RECORDS:
            raise JobWindowTooLarge()
        # The response page size can be lower than requested; advancing by the request size skips rows.
        self.limit = size
        super().update_state(response, data)


def _client_config(api_key: str, api_version: str) -> ClientConfig:
    return {
        "base_url": f"{API_ORIGIN}/api/{api_version}/",
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        "request_timeout": (10, 60),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _endpoint(config: AcculynxEndpoint, params: dict[str, Any] | None = None, *, jobs: bool = False) -> Endpoint:
    endpoint: Endpoint = {
        "path": config.path,
        "params": {**config.params, **(params or {})},
        "data_selector": config.data_selector,
        "data_selector_required": True,
        "paginator": AcculynxOffsetPaginator(config.offset_param, jobs=jobs) if config.offset_param else "single_page",
    }
    if config.offset_param:
        endpoint["response_actions"] = [{"status_code": 416, "action": "ignore"}]
    return endpoint


def _resource(name: str, endpoint: Endpoint) -> EndpointResource:
    return {
        "name": name,
        "table_name": name,
        "write_disposition": "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def _in_job_window(row: dict[str, Any], window: DateWindow) -> bool:
    created = parse_datetime_value(row.get("createdDate"))
    if created is None:
        raise ValueError("AccuLynx returned a job without a valid createdDate.")
    return window.start <= created.date() <= window.end


def _job_pages(
    client: ClientConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[AcculynxResumeConfig] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    saved = manager.load_state() if manager and manager.can_resume() else None
    if saved and saved.finished:
        return
    windows = saved.windows if saved and saved.windows else [["1900-01-01", datetime.now(UTC).date().isoformat()]]
    initial_state = saved.paginator_state if saved else None
    while windows:
        window = DateWindow(start=date.fromisoformat(windows[0][0]), end=date.fromisoformat(windows[0][1]))

        def checkpoint(state: dict[str, Any] | None, pending: list[list[str]] = windows) -> None:
            if manager:
                manager.save_state(AcculynxResumeConfig(windows=[list(w) for w in pending], paginator_state=state))

        # The API requires startDate < endDate. Filter the extra day out of single-day windows.
        query_start = window.start if window.start < window.end else window.start - timedelta(days=1)
        endpoint = _endpoint(
            ENDPOINTS["jobs"],
            {
                "startDate": query_start.isoformat(),
                "endDate": window.end.isoformat(),
                "dateFilterType": "CreatedDate",
            },
            jobs=True,
        )
        config: RESTAPIConfig = {"client": client, "resources": [_resource("jobs", endpoint)]}
        resource = rest_api_resource(
            config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=checkpoint,
            initial_paginator_state=initial_state,
        ).add_filter(lambda row, current=window: _in_job_window(row, current))
        try:
            yield from resource
        except JobWindowTooLarge:
            if window.start == window.end:
                raise ValueError("AccuLynx job date window exceeds the 100,000-record offset limit.") from None
            midpoint = window.start + (window.end - window.start) // 2
            windows = [
                [window.start.isoformat(), midpoint.isoformat()],
                [(midpoint + timedelta(days=1)).isoformat(), window.end.isoformat()],
                *windows[1:],
            ]
            inputs.logger.info("acculynx_job_window_split", start=window.start.isoformat(), end=window.end.isoformat())
        else:
            windows = windows[1:]
        initial_state = None
        if manager:
            manager.save_state(AcculynxResumeConfig(windows=[list(w) for w in windows], finished=not windows))


def _payment_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for category in ("receivedPayments", "paidPayments", "additionalExpenses"):
        group = row.get(category)
        if not isinstance(group, dict) or not isinstance(group.get(category), list):
            raise ValueError("AccuLynx returned an unexpected payments response.")
        for payment in group[category]:
            rows.append({**payment, "job_id": row["job_id"], "payment_category": category})
    return rows


def _fanout_resource(
    name: str,
    client: ClientConfig,
    inputs: SourceInputs,
    params: dict[str, Any],
    checkpoint: Callable[[dict[str, Any] | None], None],
    initial_state: dict[str, Any] | None,
) -> Resource:
    config = ENDPOINTS[name]
    fanout = config.fanout
    assert fanout is not None
    parent = _resource(fanout.parent_name, _endpoint(PARENT_ENDPOINTS[fanout.parent_name]))
    if fanout.parent_name == "jobs":
        # Job date windows must also apply to the parent walk, or child tables hit the same offset cap.
        parent["data_iterator"] = lambda: _job_pages(client, inputs)
    child_endpoint = _endpoint(
        config,
        {
            **params,
            fanout.resolve_param: {"type": "resolve", "resource": fanout.parent_name, "field": fanout.resolve_field},
        },
    )
    # A job can have no financial record, and a listed parent can be deleted before its child is fetched.
    child_endpoint["response_actions"] = [
        *(child_endpoint.get("response_actions") or []),
        {"status_code": 404, "action": "ignore"},
    ]
    child = _resource(name, child_endpoint)
    child["include_from_parent"] = fanout.include_from_parent
    resources = rest_api_resources(
        {"client": client, "resources": [parent, child]},
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=checkpoint,
        initial_paginator_state=initial_state,
    )
    resource = next(r for r in resources if r.name == name)
    resource.add_map(rename_parent_fields(fanout.parent_name, fanout.parent_field_renames))
    return resource.add_map(_payment_rows) if name == "payments" else resource


def _pages(
    name: str,
    client: ClientConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[AcculynxResumeConfig],
    appointments: DateWindow,
) -> Iterator[list[dict[str, Any]]]:
    if name == "jobs":
        yield from _job_pages(client, inputs, manager)
        return
    saved = manager.load_state() if manager.can_resume() else None
    if saved and saved.finished:
        return
    if name == "calendar_appointments":
        windows = saved.windows if saved and saved.windows else []
        if not windows:
            start = appointments.start
            while start <= appointments.end:
                end = min(start + timedelta(days=89), appointments.end)
                windows.append([start.isoformat(), end.isoformat()])
                start = end + timedelta(days=1)
    else:
        windows = [["", ""]]
    initial_state = saved.paginator_state if saved else None
    while windows:

        def checkpoint(state: dict[str, Any] | None, pending: list[list[str]] = windows) -> None:
            manager.save_state(AcculynxResumeConfig(windows=[list(w) for w in pending], paginator_state=state))

        params: dict[str, Any] = {}
        if name == "calendar_appointments":
            params = {"startDate": windows[0][0], "endDate": windows[0][1], "eventType": "All"}
        if ENDPOINTS[name].fanout:
            resource = _fanout_resource(name, client, inputs, params, checkpoint, initial_state)
        else:
            resource = rest_api_resource(
                {"client": client, "resources": [_resource(name, _endpoint(ENDPOINTS[name], params))]},
                inputs.team_id,
                inputs.job_id,
                None,
                resume_hook=checkpoint,
                initial_paginator_state=initial_state,
            )
        yield from resource
        windows = windows[1:]
        initial_state = None
        manager.save_state(AcculynxResumeConfig(windows=[list(w) for w in windows], finished=not windows))


def acculynx_source(
    *,
    api_key: str,
    api_version: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[AcculynxResumeConfig],
    appointments: DateWindow,
) -> SourceResponse:
    config = schema_for_resource(ENDPOINTS, inputs.schema_name)
    client = _client_config(api_key, api_version)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: _pages(inputs.schema_name, client, inputs, manager, appointments),
        primary_keys=list(config.primary_keys),
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        sort_mode="asc" if inputs.schema_name == "jobs" else None,
    )


def validate_credentials(
    api_key: str,
    api_version: str,
    schema_name: str | None,
    appointments: DateWindow,
) -> tuple[bool, str | None]:
    if not api_key or not api_key.isascii() or any(c.isspace() for c in api_key):
        return False, "Enter an AccuLynx API key without spaces or unsupported characters."
    client = RESTClient(
        base_url=f"{API_ORIGIN}/api/{api_version}/",
        auth=BearerTokenAuth(api_key),
        request_timeout=(10, 30),
        allowed_hosts=[],
        allow_redirects=False,
    )
    try:
        config = ENDPOINTS[schema_name or "jobs"]
        path = config.path
        params: dict[str, Any] = {**config.params, "pageSize": 1}
        if config.fanout:
            parent = PARENT_ENDPOINTS[config.fanout.parent_name]
            parents = next(
                client.paginate(
                    path=parent.path,
                    params={"pageSize": 1},
                    paginator=SinglePagePaginator(),
                    data_selector="items",
                    data_selector_required=True,
                ),
                [],
            )
            if not parents:
                return True, None
            path = path.replace("{" + config.fanout.resolve_param + "}", parents[0][config.fanout.resolve_field])
        if schema_name == "calendar_appointments":
            params.update(
                startDate=appointments.start.isoformat(),
                endDate=min(
                    appointments.start + timedelta(days=89),
                    appointments.end,
                ).isoformat(),
            )
        next(
            client.paginate(
                path=path,
                params=params,
                paginator=SinglePagePaginator(),
                data_selector=config.data_selector,
                data_selector_required=True,
            ),
            [],
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, "Your AccuLynx API key is invalid or deactivated. Create a new key and reconnect."
        if status == 403:
            if schema_name is None:
                return True, None
            return (
                False,
                "Your AccuLynx API key cannot access this table. Check its permissions with your administrator.",
            )
        if status == 404 and schema_name and ENDPOINTS[schema_name].fanout:
            return True, None
        raise
    return True, None
