from typing import Any

from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.survicate import (
    SurvicateSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.survicate.settings import (
    AUTH_ERRORS,
    ENDPOINTS,
    PRIMARY_KEYS,
)


@frozen
class SurvicateResumeConfig:
    state: dict[str, Any]


class SurvicatePaginator(BaseNextUrlPaginator):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        pagination = response.json()["pagination_data"]
        if not pagination["has_more"]:
            self._advance_to(None)
            return
        next_url = pagination.get("next_url")
        if not isinstance(next_url, str) or not next_url.startswith("/") or next_url.startswith("//"):
            raise ValueError("Survicate returned an invalid pagination link.")
        # Survicate links are relative to the versioned base, even with a leading slash.
        self._advance_to(self.base_url + next_url)


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=f"https://data-api.survicate.com/{api_version}",
        auth=APIKeyAuth(api_key=f"Basic {api_key}"),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=30,
    )
    try:
        next(
            client.paginate(
                path="surveys",
                params={"items_per_page": 1},
                paginator=SinglePagePaginator(),
                data_selector="data",
                data_selector_required=True,
            ),
            None,
        )
    except HTTPError as error:
        if error.response is not None and error.response.status_code in AUTH_ERRORS:
            return False, AUTH_ERRORS[error.response.status_code]
        raise
    return True, None


def survicate_source(
    config: SurvicateSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SurvicateResumeConfig],
    api_version: str,
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, inputs.schema_name)
    base_url = f"https://data-api.survicate.com/{api_version}"
    params: dict[str, Any] = {"items_per_page": 100}
    incremental = inputs.schema_name == "responses" and inputs.should_use_incremental_field
    if incremental and inputs.db_incremental_field_last_value is not None:
        watermark = parse_datetime_value(inputs.db_incremental_field_last_value)
        if watermark is None:
            raise ValueError("The Survicate response timestamp is invalid. Reset the table sync.")
        # The older, inclusive bound is named end because responses arrive newest first.
        params["end"] = watermark.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if inputs.schema_name == "responses" and config.attribute_names:
        attributes = [name.strip() for name in config.attribute_names.split(",") if name.strip()]
        if attributes:
            params["attributes[]"] = attributes

    resource: EndpointResource = {
        "name": inputs.schema_name,
        "endpoint": {"path": path, "params": params},
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
    }
    resources: list[str | EndpointResource] = [resource]
    if inputs.schema_name != "surveys":
        params["survey_id"] = {"type": "resolve", "resource": "surveys", "field": "id"}
        resource["include_from_parent"] = ["id"]
        resource["data_map"] = rename_parent_fields("surveys", {"id": "survey_id"})
        resources.insert(
            0,
            {
                "name": "surveys",
                "endpoint": {"path": "surveys", "params": {"items_per_page": 100}},
                "write_disposition": "replace",
            },
        )
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "auth": APIKeyAuth(api_key=f"Basic {config.api_key}"),
            "paginator": SurvicatePaginator(base_url),
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 30,
        },
        "resource_defaults": {"endpoint": {"data_selector": "data", "data_selector_required": True}},
        "resources": resources,
    }
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        manager.safe_point()
        if state is not None:
            manager.save_state(SurvicateResumeConfig(state=state))

    built = rest_api_resources(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.state if resume else None,
    )
    result = next(item for item in built if item.name == inputs.schema_name)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: result,
        primary_keys=PRIMARY_KEYS[inputs.schema_name],
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
