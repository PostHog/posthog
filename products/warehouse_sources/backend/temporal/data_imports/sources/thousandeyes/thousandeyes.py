from datetime import UTC, datetime, timedelta
from typing import Any

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.thousandeyes import (
    ThousandeyesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thousandeyes.settings import (
    ENDPOINTS,
    HISTORY_DAYS,
)

AUTH_ERRORS = {
    "401 Client Error": "ThousandEyes rejected the API token. Create a new token in Users and Roles > Profile.",
    "403 Client Error": "ThousandEyes denied access. Check your permissions and account group ID.",
}


@frozen
class ThousandeyesResumeConfig:
    paginator_state: dict[str, Any] | None
    start_date: str
    end_date: str


def client_config(config: ThousandeyesSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": f"https://api.thousandeyes.com/{api_version}/",
        "auth": {"type": "bearer", "token": config.api_token},
        "paginator": {"type": "json_response", "next_url_path": "_links.next.href"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": 60,
    }


def account_params(config: ThousandeyesSourceConfig) -> dict[str, Any]:
    return {"aid": config.account_group_id} if config.account_group_id else {}


def validate_credentials(config: ThousandeyesSourceConfig, api_version: str) -> tuple[bool, str | None]:
    api: RESTAPIConfig = {
        "client": {**client_config(config, api_version), "max_retries": 1},
        "resources": [
            {
                "name": "validation",
                "endpoint": {
                    "path": "alerts",
                    "params": {**account_params(config), "max": 1},
                    "data_selector": "alerts",
                    "paginator": "single_page",
                },
            }
        ],
    }
    try:
        list(rest_api_resources(api, 0, "", None)[0])
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status in (401, 403):
            return False, AUTH_ERRORS[f"{status} Client Error"]
        raise
    return True, None


def live_test(row: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    return [] if row.get("savedEvent") else {"testId": row["testId"]}


def result_row(row: dict[str, Any]) -> dict[str, Any]:
    row["testId"] = row.pop("_http_tests_testId")
    row["agentId"] = row["agent"]["agentId"]
    return row


def thousandeyes_source(
    config: ThousandeyesSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[ThousandeyesResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    is_results = inputs.schema_name == "http_server_results"
    resume = manager.load_state() if manager.can_resume() else None
    end = datetime.now(UTC).replace(microsecond=0)
    start = end - timedelta(days=HISTORY_DAYS)
    if is_results and inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
        watermark = parse_datetime_value(inputs.db_incremental_field_last_value)
        if watermark is None:
            raise ValueError("Invalid ThousandEyes result timestamp. Reset this table and try again.")
        # Re-read recent rounds because agents can report their measurements late.
        start = max(start, watermark - timedelta(minutes=5))
    start_date = resume.start_date if resume else start.isoformat().replace("+00:00", "Z")
    end_date = resume.end_date if resume else end.isoformat().replace("+00:00", "Z")
    params = account_params(config)
    if is_results or endpoint.alert_state:
        params.update(startDate=start_date, endDate=end_date)
    if endpoint.alert_state:
        params["state"] = endpoint.alert_state
    resources: list[str | EndpointResource] = []
    if is_results:
        resources.append(
            {
                "name": "http_tests",
                "endpoint": {"path": "tests/http-server", "params": account_params(config), "data_selector": "tests"},
                "data_map": live_test,
            }
        )
        params["testId"] = {"type": "resolve", "resource": "http_tests", "field": "testId"}
    resource: EndpointResource = {
        "name": inputs.schema_name,
        "endpoint": {"path": endpoint.path, "params": params, "data_selector": endpoint.selector},
    }
    if is_results:
        resource["include_from_parent"] = ["testId"]
        resource["data_map"] = result_row
    resources.append(resource)

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        manager.save_state(ThousandeyesResumeConfig(paginator_state=state, start_date=start_date, end_date=end_date))

    api: RESTAPIConfig = {"client": client_config(config, api_version), "resources": resources}
    built = rest_api_resources(
        api,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.paginator_state if resume else None,
    )
    selected = next(item for item in built if item.name == inputs.schema_name)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: selected,
        primary_keys=list(endpoint.primary_keys),
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
