import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import create_auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kestra import KestraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kestra.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    PAGE_SIZE,
    PERMISSION_ERROR,
    PRIMARY_KEYS,
)


@frozen
class KestraResumeState:
    page: int
    start_date: str | None
    end_date: str


class KestraPaginator(PageNumberPaginator):
    def __init__(self) -> None:
        super().__init__(base_page=1, stop_after_empty_page=False)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if not isinstance(body.get("results"), list) or not isinstance(body.get("total"), int):
            raise ValueError("Kestra returned an invalid page. Expected results and a total count.")
        # Trigger pages can be empty when their flows no longer exist, even before the final page.
        self.maximum_page = max(1, (body["total"] + PAGE_SIZE - 1) // PAGE_SIZE)
        super().update_state(response, data)


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
    endpoint = schema_for_resource(ENDPOINTS, schema_name or "flows")
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


def normalize_execution(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "start_date": datetime.fromisoformat(row["state"]["startDate"].replace("Z", "+00:00"))}


def normalize_trigger(row: dict[str, Any]) -> dict[str, Any]:
    state = row["state"]
    return {**row, "namespace": state["namespace"], "flow_id": state["flowId"], "trigger_id": state["triggerId"]}


def kestra_source(
    config: KestraSourceConfig, inputs: SourceInputs, manager: ResumableSourceManager[KestraResumeState]
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    client = client_config(config, inputs.team_id)
    start_date = None
    if inputs.schema_name == "executions" and inputs.should_use_incremental_field:
        watermark = inputs.db_incremental_field_last_value
        if watermark is not None:
            start_date = watermark.isoformat() if isinstance(watermark, datetime) else str(watermark)
    resume = manager.load_state() if manager.can_resume() else None
    if resume is None:
        resume = KestraResumeState(page=1, start_date=start_date, end_date=datetime.now(UTC).isoformat())
    params: dict[str, Any] = {"size": PAGE_SIZE}
    if inputs.schema_name == "executions":
        params.update(
            {
                "sort": "state.startDate:asc",
                "dateFilter": "START_DATE",
                "filters[endDate][LESS_THAN_OR_EQUAL_TO]": resume.end_date,
            }
        )
        if resume.start_date is not None:
            params["filters[startDate][GREATER_THAN_OR_EQUAL_TO]"] = resume.start_date
    elif inputs.schema_name == "flows":
        params["sort"] = ["namespace:asc", "id:asc"]
    else:
        params["sort"] = ["namespace:asc", "flowId:asc", "triggerId:asc"]

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(
                KestraResumeState(page=int(state["page"]), start_date=resume.start_date, end_date=resume.end_date)
            )

    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [
            {
                "name": inputs.schema_name,
                "endpoint": {
                    "path": endpoint,
                    "params": params,
                    "data_selector": "results",
                    "data_selector_required": True,
                    "paginator": KestraPaginator(),
                },
            }
        ],
    }
    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": resume.page},
    )
    if inputs.schema_name == "executions":
        resource.add_map(normalize_execution)
    elif inputs.schema_name == "triggers":
        resource.add_map(normalize_trigger)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[inputs.schema_name],
        sort_mode="asc" if inputs.schema_name == "executions" else "desc",
        on_complete=manager.clear_state,
    )
