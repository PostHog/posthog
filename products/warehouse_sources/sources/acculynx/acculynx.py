from collections.abc import Callable, Iterator
from dataclasses import field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any
from urllib.parse import quote

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.sources.acculynx.settings import (
    API_ORIGIN,
    ENDPOINTS,
    MAX_JOB_RECORDS,
    PAGE_SIZE,
    PARENT_ENDPOINTS,
    AcculynxEndpoint,
)
from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    ClientConfig,
    Endpoint,
    EndpointResource,
    OffsetPaginator,
    Resource,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceInputs,
    SourceResponse,
    create_auth,
    create_response_hooks,
    frozen,
    parse_datetime_value,
    rename_parent_fields,
    rest_api_resource,
    rest_api_resources,
    schema_for_resource,
)


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
        # Advance by returned rows so a short non-empty page does not skip records.
        self.limit = len(data) if data else size
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


def _job_endpoint(window: DateWindow, params: dict[str, Any] | None) -> Endpoint:
    # The API requires startDate < endDate. Filter the extra day out of single-day windows.
    query_start = window.start if window.start < window.end else window.start - timedelta(days=1)
    return _endpoint(
        ENDPOINTS["jobs"],
        {
            **(params or {}),
            "startDate": query_start.isoformat(),
            "endDate": window.end.isoformat(),
            "dateFilterType": "CreatedDate",
        },
        jobs=True,
    )


def _lead_history_pages(
    parents: Resource,
    client: RESTClient,
    manager: ResumableSourceManager[AcculynxResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    endpoint = ENDPOINTS["lead_history"]
    hooks = create_response_hooks([{"status_code": 404, "action": "ignore"}], resource_name="lead_history")
    seen: set[str] = set()
    for page in parents:
        for parent in page:
            lead_id = parent["id"]
            if lead_id in seen:
                continue
            seen.add(lead_id)
            done = manager.with_namespace(f"lead_history:{lead_id}")
            if not done.can_resume():
                history = next(
                    client.paginate(
                        path=_bind_path(endpoint.path, {"leadId": quote(lead_id, safe="")}),
                        paginator=SinglePagePaginator(),
                        data_selector=endpoint.data_selector,
                        data_selector_required=True,
                        hooks=hooks,
                    ),
                    [],
                )
                rows = [{**action, "lead_id": lead_id} for action in history]
                done.save_state(AcculynxResumeConfig(finished=True))
                if rows:
                    yield rows
            manager.safe_point()


def _save_lead_history_window(
    manager: ResumableSourceManager[AcculynxResumeConfig], state: AcculynxResumeConfig
) -> None:
    manager.save_state(state)
    manager.safe_point()


def _job_pages(
    client: ClientConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[AcculynxResumeConfig] | None = None,
    *,
    params: dict[str, Any] | None = None,
    history_client: RESTClient | None = None,
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

        if history_client is not None:
            # Lead promotions shift the listing offsets. Resume the window from its start.
            checkpoint(None)
        config: RESTAPIConfig = {"client": client, "resources": [_resource("jobs", _job_endpoint(window, params))]}
        resource = rest_api_resource(
            config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=checkpoint if history_client is None else None,
            initial_paginator_state=initial_state if history_client is None else None,
        ).add_filter(partial(_in_job_window, window=window))
        try:
            if history_client is None:
                yield from resource
            else:
                assert manager is not None
                yield from _lead_history_pages(resource, history_client, manager)
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
            state = AcculynxResumeConfig(windows=[list(w) for w in windows], finished=not windows)
            if history_client is None:
                manager.save_state(state)
            else:
                _save_lead_history_window(manager, state)


def _payment_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for category in ("receivedPayments", "paidPayments", "additionalExpenses"):
        group = row.get(category)
        if not isinstance(group, dict) or not isinstance(group.get(category), list):
            raise ValueError("AccuLynx returned an unexpected payments response.")
        for payment in group[category]:
            rows.append({**payment, "job_id": row["job_id"], "payment_category": category})
    return rows


def _fanout_chain(name: str) -> list[str]:
    chain = [name]
    while (fanout := PARENT_ENDPOINTS[chain[0]].fanout) is not None:
        chain.insert(0, fanout.parent_name)
    return chain


def _fanout_resource(
    name: str,
    client: ClientConfig,
    inputs: SourceInputs,
    params: dict[str, Any],
    checkpoint: Callable[[dict[str, Any] | None], None],
    initial_state: dict[str, Any] | None,
) -> Resource:
    resources: list[str | EndpointResource] = []
    chain = _fanout_chain(name)
    root_child = PARENT_ENDPOINTS[chain[1]].fanout
    assert root_child is not None
    for level in chain:
        config = PARENT_ENDPOINTS[level]
        fanout = config.fanout
        if fanout is None:
            parent = _resource(level, _endpoint(config, root_child.parent_params))
            if level == "jobs":
                # Job date windows must also apply to the parent walk, or child tables hit the same offset cap.
                parent["data_iterator"] = partial(_job_pages, client, inputs, params=root_child.parent_params)
            resources.append(parent)
            continue
        endpoint = _endpoint(
            config,
            {
                **(params if level == name else {}),
                **fanout.child_params,
                fanout.resolve_param: {
                    "type": "resolve",
                    "resource": fanout.parent_name,
                    "field": fanout.resolve_field,
                },
            },
        )
        # A job can have no financial record, and a listed parent can be deleted before its child is fetched.
        endpoint["response_actions"] = [
            *(endpoint.get("response_actions") or []),
            {"status_code": 404, "action": "ignore"},
        ]
        child = _resource(level, endpoint)
        child["include_from_parent"] = fanout.include_from_parent
        resources.append(child)
    fanout = ENDPOINTS[name].fanout
    assert fanout is not None
    built = rest_api_resources(
        {"client": client, "resources": resources},
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=checkpoint,
        initial_paginator_state=initial_state,
    )
    resource = next(r for r in built if r.name == name)
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

    def items() -> Resource | Iterator[list[dict[str, Any]]]:
        if inputs.schema_name != "lead_history":
            return _pages(inputs.schema_name, client, inputs, manager, appointments)
        fanout = ENDPOINTS["lead_history"].fanout
        assert fanout is not None
        history_client = RESTClient(
            base_url=client.get("base_url"),
            headers=client.get("headers"),
            auth=create_auth(client.get("auth")),
            request_timeout=client.get("request_timeout"),
            allowed_hosts=client.get("allowed_hosts"),
            allow_redirects=False,
        )
        return Resource(
            partial(_job_pages, client, inputs, manager, params=fanout.parent_params, history_client=history_client),
            name="lead_history",
            hints={},
        )

    return SourceResponse(
        name=inputs.schema_name,
        items=items,
        primary_keys=list(config.primary_keys),
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        sort_mode="asc" if inputs.schema_name == "jobs" else None,
    )


def _bind_path(path: str, bindings: dict[str, str]) -> str:
    for param, value in bindings.items():
        path = path.replace("{" + param + "}", value)
    return path


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
        params: dict[str, Any] = dict(config.params)
        if config.offset_param:
            params["pageSize"] = 1
        if config.fanout:
            # Bind each level's path parameters from the first row of the level above it.
            bindings: dict[str, str] = {}
            chain = _fanout_chain(schema_name or "jobs")
            for parent_name, child_name in zip(chain, chain[1:]):
                parent = PARENT_ENDPOINTS[parent_name]
                child_fanout = PARENT_ENDPOINTS[child_name].fanout
                assert child_fanout is not None
                parents = next(
                    client.paginate(
                        path=_bind_path(parent.path, bindings),
                        params={"pageSize": 1, **child_fanout.parent_params},
                        paginator=SinglePagePaginator(),
                        data_selector=parent.data_selector,
                        data_selector_required=True,
                    ),
                    [],
                )
                if not parents:
                    return True, None
                bindings[child_fanout.resolve_param] = parents[0][child_fanout.resolve_field]
            path = _bind_path(path, bindings)
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
