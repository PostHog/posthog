from datetime import UTC, datetime
from typing import Any

from jsonpath_ng import DatumInContext, JSONPath
from requests import HTTPError, RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.vwo.settings import (
    API_ORIGIN,
    ENDPOINTS,
    VWOEndpoint,
)


@frozen
class VWOResumeConfig:
    paginator_state: dict[str, Any]


class VWOCollectionSelector(JSONPath):
    # The campaign example is malformed. Accept flat and partialCollection envelopes without selecting nested goals.
    def find(self, data: Any) -> list[DatumInContext]:
        if not isinstance(data, dict) or "_data" not in data:
            raise ValueError("VWO returned no data envelope. Check the token permissions and API response.")
        rows = data["_data"]
        if isinstance(rows, dict) and "partialCollection" in rows:
            rows = rows["partialCollection"]
        if rows is None or rows == {}:
            rows = []
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("VWO returned an unsupported collection. Check the API response.")
        return [DatumInContext(rows)]


def client_config(api_token: str, api_version: str) -> ClientConfig:
    return {
        "base_url": f"{API_ORIGIN}/{api_version}/",
        "auth": {"type": "api_key", "api_key": api_token, "name": "token", "location": "header"},
        "headers": {"Accept": "application/json"},
        "request_timeout": (10, 30),
        "retry_budget_seconds": 180,
        "retry_after_max_seconds": 60,
        "allow_redirects": False,
        "allowed_hosts": [],
    }


def endpoint_config(endpoint: VWOEndpoint) -> Endpoint:
    return {
        "data_selector": "_data" if endpoint.singleton else VWOCollectionSelector(),
        "data_selector_required": True,
        "paginator": {"type": "offset", "limit": endpoint.page_size, "total_path": "_data.totalCount"}
        if endpoint.paginated
        else "single_page",
    }


def normalize_row(endpoint: VWOEndpoint, row: dict[str, Any]) -> dict[str, Any]:
    if endpoint.partition_field:
        value = row.get(endpoint.partition_field)
        row["created_at"] = datetime.fromtimestamp(float(value), tz=UTC) if value is not None else None
    if endpoint.name == "variations":
        # Some variation responses omit sectionId. Zero keeps the composite key non-null.
        row["sectionId"] = row.get("sectionId") or 0
    return row


def validate_credentials(api_token: str, account_id: str, api_version: str) -> tuple[bool, str | None]:
    config = client_config(api_token, api_version)
    client = RESTClient(
        base_url=config["base_url"],
        auth=APIKeyAuth(api_key=api_token, name="token", location="header"),
        request_timeout=config["request_timeout"],
        retry_budget_seconds=config["retry_budget_seconds"],
        retry_after_max_seconds=config["retry_after_max_seconds"],
        allow_redirects=False,
        allowed_hosts=[],
    )
    try:
        page = next(
            client.paginate(path=f"accounts/{account_id}", data_selector="_data", paginator=SinglePagePaginator())
        )
        if not page or not isinstance(page[0], dict) or "id" not in page[0]:
            return False, "VWO returned no workspace. Check the workspace ID and token permissions."
        return True, None
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, "VWO rejected the API token. Generate a new token and reconnect."
        if status == 403:
            return False, "The VWO token cannot read this workspace. Check the token permissions and workspace ID."
        if status == 404:
            return False, "VWO could not find this workspace. Check the workspace ID."
        return False, "VWO rejected the connection request. Check the workspace ID and token permissions."
    except (RequestException, RESTClientRetryableError, ValueError):
        return False, "Could not connect to VWO. Try again."


def vwo_source(
    api_token: str,
    account_id: str,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VWOResumeConfig],
) -> SourceResponse:
    metadata = schema_for_resource(ENDPOINTS, endpoint)
    client = client_config(api_token, api_version)
    initial_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = resume.paginator_state

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(VWOResumeConfig(paginator_state=state))

    if metadata.fanout:
        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint,
            fanout=metadata.fanout,
            client_config=client,
            path_format_values={"account_id": account_id},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=endpoint_config(ENDPOINTS[metadata.fanout.parent_name]),
            child_endpoint_extra=endpoint_config(metadata),
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )
        assert isinstance(resource, Resource)
    else:
        config: RESTAPIConfig = {
            "client": client,
            "resources": [
                {
                    "name": endpoint,
                    "table_name": endpoint,
                    "write_disposition": "replace",
                    "table_format": "delta",
                    "endpoint": {**endpoint_config(metadata), "path": metadata.path.format(account_id=account_id)},
                }
            ],
        }
        resource = rest_api_resource(
            config, team_id, job_id, None, resume_hook=save_checkpoint, initial_paginator_state=initial_state
        )
    resource.add_map(lambda row: normalize_row(metadata, row))
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(metadata.primary_keys),
        partition_mode="datetime" if metadata.partition_field else None,
        partition_keys=["created_at"] if metadata.partition_field else None,
        partition_format="month" if metadata.partition_field else None,
        sort_mode=None,
    )
