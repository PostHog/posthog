from datetime import UTC, datetime
from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.abnormal_security.settings import (
    ENDPOINTS,
    REGION_HOSTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resources
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
    RESTAPIConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.abnormalsecurity import (
    AbnormalSecuritySourceConfig,
)

AUTH_ERRORS = {
    "401 Client Error": "Your Abnormal API token is invalid or expired. Create a new token and reconnect.",
    "403 Client Error": "Abnormal denied access. Check your token permissions, product licenses, and IP allowlist.",
}


@frozen
class AbnormalSecurityResumeConfig:
    filter_value: str
    paginator_state: dict[str, Any]


def client_config(config: AbnormalSecuritySourceConfig, api_version: str | None = None) -> ClientConfig:
    if config.region not in REGION_HOSTS:
        raise ValueError("Select a supported Abnormal region: US or EU.")
    version = api_version or "v1"
    if version != "v1":
        raise ValueError("Unsupported Abnormal API version. Use v1.")
    return {
        "base_url": f"{REGION_HOSTS[config.region]}/{version}/",
        "auth": {"type": "bearer", "token": config.api_key},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": 60,
        "capture": False,
        "paginator": {
            "type": "cursor",
            "cursor_path": "nextPageNumber",
            "cursor_param": "pageNumber",
            "raise_on_repeated_cursor": True,
        },
    }


def validate_credentials(
    config: AbnormalSecuritySourceConfig, team_id: int, api_version: str | None = None
) -> tuple[bool, str | None]:
    try:
        resource = rest_api_resources(
            {
                "client": client_config(config, api_version),
                "resources": [
                    {
                        "name": "credential_check",
                        "endpoint": {
                            "path": "threats",
                            "params": {
                                "pageSize": 1,
                                "filter": f"receivedTime lte {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
                            },
                            "data_selector": "threats",
                            "data_selector_required": True,
                            "paginator": "single_page",
                        },
                    }
                ],
            },
            team_id,
            "",
            None,
        )[0]
        next(iter(resource), None)
    except ValueError as error:
        return False, str(error)
    except HTTPError as error:
        for pattern, message in AUTH_ERRORS.items():
            if pattern in str(error):
                return False, message
        raise
    return True, None


def abnormal_security_source(
    config: AbnormalSecuritySourceConfig,
    manager: ResumableSourceManager[AbnormalSecurityResumeConfig],
    inputs: SourceInputs,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    resume = manager.load_state() if manager.can_resume() else None
    if resume:
        filter_value = resume.filter_value
    else:
        start = datetime(1970, 1, 1, tzinfo=UTC)
        if endpoint.incremental_field and inputs.should_use_incremental_field:
            watermark = inputs.db_incremental_field_last_value
            if watermark is not None:
                parsed = parse_datetime_value(watermark)
                if parsed is None:
                    raise ValueError("Invalid Abnormal incremental timestamp. Reset the table and try again.")
                start = parsed
        lower = start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        upper = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Without a filter, Abnormal returns only the top 100 records and ignores pagination.
        filter_value = f"{endpoint.filter_field} gte {lower} lte {upper}"

    parent_name = f"{inputs.schema_name}_ids" if endpoint.detail_path else inputs.schema_name
    params: dict[str, Any] = {"filter": filter_value, "pageSize": 100, "pageNumber": 1}
    if inputs.schema_name == "threats":
        params["source"] = "all"
    resources: list[str | EndpointResource] = [
        {
            "name": parent_name,
            "endpoint": {
                "path": endpoint.path,
                "params": params,
                "data_selector": endpoint.selector,
                "data_selector_required": True,
            },
        }
    ]
    if endpoint.detail_path:
        resources.append(
            {
                "name": inputs.schema_name,
                "endpoint": {
                    "path": endpoint.detail_path,
                    "params": {"id": {"type": "resolve", "resource": parent_name, "field": endpoint.primary_key}},
                    "data_selector": "$",
                    # Threat details contain a limited message sample; the table grain is one campaign.
                    "paginator": "single_page",
                },
            }
        )
    rest_config: RESTAPIConfig = {"client": client_config(config, inputs.api_version), "resources": resources}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(AbnormalSecurityResumeConfig(filter_value=filter_value, paginator_state=state))

    resource = rest_api_resources(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.paginator_state if resume else None,
    )[-1]
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=[endpoint.primary_key],
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        # The API does not guarantee ascending order, so the watermark must use the batch maximum.
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
