import re
import json
import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from requests import Request, Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import create_auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kestra import KestraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kestra.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    FANOUT_PARENTS,
    INCREMENTAL_FIELDS,
    LARGE_PAGE_SIZE,
    PAGE_SIZE,
    PERMISSION_ERROR,
    PRIMARY_KEYS,
)

INVALID_PAGE = "Kestra returned an invalid page. Expected results and a total count."


@frozen
class KestraResumeState:
    page: int
    start_date: str | None
    end_date: str
    cursor: str | None = None


class KestraPaginator(PageNumberPaginator):
    def __init__(self, page_size: int = PAGE_SIZE) -> None:
        super().__init__(base_page=1, stop_after_empty_page=False)
        self.page_size = page_size

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if not isinstance(body.get("results"), list) or not isinstance(body.get("total"), int):
            raise ValueError(INVALID_PAGE)
        # Trigger pages can be empty when their flows no longer exist, even before the final page.
        self.maximum_page = max(1, (body["total"] + self.page_size - 1) // self.page_size)
        super().update_state(response, data)


class KestraLogPaginator(BasePaginator):
    """Kestra log stores answer with offset pages and a total, or with a forward-only cursor."""

    def __init__(self) -> None:
        super().__init__()
        self.page = 1
        self.cursor: str | None = None

    def init_request(self, request: Request) -> None:
        self.update_request(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if not isinstance(body.get("results"), list):
            raise ValueError(INVALID_PAGE)
        next_cursor = body.get("nextCursor")
        if body.get("type") == "CURSOR" or next_cursor:
            if next_cursor and next_cursor == self.cursor:
                raise ValueError("Kestra returned the same log cursor twice.")
            self.cursor = next_cursor or None
            self._has_next_page = self.cursor is not None
            return
        total = body.get("total")
        if not isinstance(total, int):
            raise ValueError(INVALID_PAGE)
        self._has_next_page = self.page * LARGE_PAGE_SIZE < total
        self.page += 1

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        if self.cursor is None:
            request.params["page"] = self.page
        else:
            request.params.pop("page", None)
            request.params["cursor"] = self.cursor

    def get_resume_state(self) -> dict[str, Any] | None:
        if not self._has_next_page:
            return None
        return {"cursor": self.cursor} if self.cursor is not None else {"page": self.page}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        if state.get("cursor"):
            self.cursor = state["cursor"]
        elif state.get("page"):
            self.page = int(state["page"])


def client_config(config: KestraSourceConfig, team_id: int) -> ClientConfig:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (  # noqa: PLC0415 -- avoids loading Django models during config discovery
        ValidateDatabaseHostMixin,
    )

    host = config.host.strip().rstrip("/")
    try:
        parsed = urlsplit(host)
        valid_url = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and parsed.path == ""
            and not parsed.query
            and not parsed.fragment
            and parsed.port != 0
        )
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ValueError("Enter your Kestra HTTPS origin, without a path, query, or embedded credentials.")
    valid, _ = ValidateDatabaseHostMixin().is_database_host_valid(parsed.hostname or "", team_id)
    if not valid:
        raise ValueError("The Kestra host must resolve to a public address. Check your instance URL.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", config.tenant):
        raise ValueError("Enter a Kestra tenant ID with letters, digits, underscores, or hyphens.")
    client: ClientConfig = {
        "base_url": f"{host}/api/v1/{config.tenant}/",
        "allowed_hosts": [parsed.hostname or ""],
        "allow_redirects": False,
        "request_timeout": (10, 60),
    }
    auth = config.auth_method
    if auth.selection == "token":
        if not auth.api_token or not auth.api_token.strip():
            raise ValueError("Enter an API token.")
        client["auth"] = {"type": "bearer", "token": auth.api_token}
    elif auth.selection == "basic":
        if not auth.username or not auth.username.strip() or not auth.password or not auth.password.strip():
            raise ValueError("Enter a username and password.")
        client["auth"] = {"type": "http_basic", "username": auth.username, "password": auth.password}
    else:
        raise ValueError("Select API token or Basic authentication.")
    return client


def validate_credentials(config: KestraSourceConfig, team_id: int, schema_name: str | None) -> tuple[bool, str | None]:
    try:
        settings = client_config(config, team_id)
    except ValueError as error:
        return False, str(error)
    probe_name = schema_name or "flows"
    schema_for_resource(ENDPOINTS, probe_name)
    endpoint = ENDPOINTS[FANOUT_PARENTS.get(probe_name, probe_name)]
    client = RESTClient(
        base_url=settings["base_url"],
        auth=create_auth(settings["auth"]),
        allowed_hosts=settings["allowed_hosts"],
        allow_redirects=False,
        request_timeout=(10, 60),
    )
    try:
        next(
            client.paginate(
                endpoint,
                params={"page": 1, "size": 1},
                paginator=SinglePagePaginator(),
                data_selector="results",
                data_selector_required=True,
            ),
            None,
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        raise
    return True, None


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_execution(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "start_date": parse_timestamp(row["state"]["startDate"])}


def normalize_trigger(row: dict[str, Any]) -> dict[str, Any]:
    state = row["state"]
    return {**row, "namespace": state["namespace"], "flow_id": state["flowId"], "trigger_id": state["triggerId"]}


def entry_id(row: dict[str, Any]) -> str:
    # Kestra gives log and metric entries no identifier, so the key is a hash of the entry itself.
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


def normalize_log(row: dict[str, Any]) -> dict[str, Any]:
    timestamp = row.get("timestamp")
    return {
        **row,
        "entry_id": entry_id(row),
        "timestamp": parse_timestamp(timestamp) if isinstance(timestamp, str) else timestamp,
    }


def normalize_task_run(row: dict[str, Any]) -> dict[str, Any]:
    row["execution_start_date"] = row.pop("_executions_start_date")
    return row


def normalize_metric(row: dict[str, Any]) -> dict[str, Any]:
    execution_start_date = row.pop("_executions_start_date")
    return {**row, "entry_id": entry_id(row), "execution_start_date": execution_start_date}


def time_window_params(schema_name: str, start_date: str | None, end_date: str) -> dict[str, Any]:
    params: dict[str, Any] = {"filters[endDate][LESS_THAN_OR_EQUAL_TO]": end_date}
    if start_date is not None:
        params["filters[startDate][GREATER_THAN_OR_EQUAL_TO]"] = start_date
    if schema_name == "logs":
        params["sort"] = "timestamp:asc"
    else:
        params.update({"sort": "state.startDate:asc", "dateFilter": "START_DATE"})
    return params


def fanout_resources(schema_name: str, start_date: str | None, end_date: str) -> list[str | EndpointResource]:
    not_found_is_empty: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]
    if schema_name == "flow_revisions":
        return [
            {
                "name": "flows",
                "endpoint": {
                    "path": ENDPOINTS["flows"],
                    "params": {"size": PAGE_SIZE, "sort": ["namespace:asc", "id:asc"]},
                    "data_selector": "results",
                    "data_selector_required": True,
                    "paginator": KestraPaginator(),
                },
            },
            {
                "name": schema_name,
                "endpoint": {
                    "path": ENDPOINTS[schema_name],
                    "params": {
                        "namespace": {"type": "resolve", "resource": "flows", "field": "namespace"},
                        "id": {"type": "resolve", "resource": "flows", "field": "id"},
                    },
                    "data_selector_required": True,
                    "paginator": SinglePagePaginator(),
                    "response_actions": not_found_is_empty,
                },
            },
        ]
    resolve_execution = {"type": "resolve", "resource": "executions", "field": "id"}
    child_endpoint: Endpoint
    if schema_name == "task_runs":
        child_endpoint = {
            "path": ENDPOINTS[schema_name],
            "params": {"executionId": resolve_execution},
            "data_selector": "taskRunList",
            "paginator": SinglePagePaginator(),
            "response_actions": not_found_is_empty,
        }
    else:
        child_endpoint = {
            "path": ENDPOINTS[schema_name],
            "params": {"executionId": resolve_execution, "size": LARGE_PAGE_SIZE},
            "data_selector": "results",
            "data_selector_required": True,
            "paginator": KestraPaginator(LARGE_PAGE_SIZE),
            "response_actions": not_found_is_empty,
        }
    return [
        {
            "name": "executions",
            "endpoint": {
                "path": ENDPOINTS["executions"],
                "params": {"size": PAGE_SIZE, **time_window_params("executions", start_date, end_date)},
                "data_selector": "results",
                "data_selector_required": True,
                "paginator": KestraPaginator(),
            },
            "data_map": normalize_execution,
        },
        {"name": schema_name, "include_from_parent": ["start_date"], "endpoint": child_endpoint},
    ]


def kestra_source(
    config: KestraSourceConfig, inputs: SourceInputs, manager: ResumableSourceManager[KestraResumeState]
) -> SourceResponse:
    schema_for_resource(ENDPOINTS, inputs.schema_name)
    client = client_config(config, inputs.team_id)
    incremental = inputs.schema_name in INCREMENTAL_FIELDS
    start_date = None
    if incremental and inputs.should_use_incremental_field:
        watermark = inputs.db_incremental_field_last_value
        if watermark is not None:
            start_date = watermark.isoformat() if isinstance(watermark, datetime) else str(watermark)
    end_date = datetime.now(UTC).isoformat()

    if inputs.schema_name in FANOUT_PARENTS:
        # Fan-out tables do not resume: the framework would checkpoint every finished parent, which
        # grows with the number of executions or flows.
        resources = rest_api_resources(
            {"client": client, "resources": fanout_resources(inputs.schema_name, start_date, end_date)},
            inputs.team_id,
            inputs.job_id,
            None,
        )
        resource = next(r for r in resources if r.name == inputs.schema_name)
        if inputs.schema_name == "task_runs":
            resource.add_map(normalize_task_run)
        elif inputs.schema_name == "execution_metrics":
            resource.add_map(normalize_metric)
        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: resource,
            primary_keys=PRIMARY_KEYS[inputs.schema_name],
            sort_mode="asc" if incremental else "desc",
            on_complete=manager.clear_state,
        )

    resume = manager.load_state() if manager.can_resume() else None
    if resume is None:
        resume = KestraResumeState(page=1, start_date=start_date, end_date=end_date)
    params: dict[str, Any] = {"size": LARGE_PAGE_SIZE if inputs.schema_name == "logs" else PAGE_SIZE}
    if incremental:
        params.update(time_window_params(inputs.schema_name, resume.start_date, resume.end_date))
    elif inputs.schema_name == "flows":
        params["sort"] = ["namespace:asc", "id:asc"]
    else:
        params["sort"] = ["namespace:asc", "flowId:asc", "triggerId:asc"]

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(
                KestraResumeState(
                    page=int(state.get("page") or 1),
                    start_date=resume.start_date,
                    end_date=resume.end_date,
                    cursor=state.get("cursor"),
                )
            )

    paginator: BasePaginator = KestraLogPaginator() if inputs.schema_name == "logs" else KestraPaginator()
    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [
            {
                "name": inputs.schema_name,
                "endpoint": {
                    "path": ENDPOINTS[inputs.schema_name],
                    "params": params,
                    "data_selector": "results",
                    "data_selector_required": True,
                    "paginator": paginator,
                },
            }
        ],
    }
    initial_state: dict[str, Any] = {"page": resume.page}
    if resume.cursor is not None:
        initial_state["cursor"] = resume.cursor
    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    if inputs.schema_name == "executions":
        resource.add_map(normalize_execution)
    elif inputs.schema_name == "triggers":
        resource.add_map(normalize_trigger)
    elif inputs.schema_name == "logs":
        resource.add_map(normalize_log)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[inputs.schema_name],
        sort_mode="asc" if incremental else "desc",
        on_complete=manager.clear_state,
    )
