from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.ynab.settings import ENDPOINTS

AUTH_ERROR = "Your YNAB personal access token is invalid or expired. Create a new token and reconnect."
PERMISSION_ERROR = "Your YNAB token cannot access this resource. Check its permissions and reconnect."


@frozen
class YnabResumeConfig:
    completed: list[str]


def validate_credentials(api_key: str, api_version: str, schema_name: str | None) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=f"https://api.ynab.com/{api_version}/",
        auth=BearerTokenAuth(token=api_key),
    )
    try:
        list(client.paginate(path="user", paginator=SinglePagePaginator(), data_selector="data.user"))
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        raise
    finally:
        client.session.close()
    return True, None


def ynab_source(
    api_key: str,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[YnabResumeConfig],
) -> SourceResponse:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    client_config: ClientConfig = {
        "base_url": f"https://api.ynab.com/{api_version}/",
        "auth": {"type": "bearer", "token": api_key},
        "paginator": "single_page",
    }

    if endpoint_config.fanout is not None:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

        def save_checkpoint(state: dict[str, Any] | None) -> None:
            # Single-page children are complete only after their batch has been yielded.
            if state is not None and state.get("current") is None:
                resumable_source_manager.save_state(YnabResumeConfig(completed=state["completed"]))

        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param=None,
            parent_endpoint_extra={"data_selector": "data.plans", "data_selector_required": True},
            child_endpoint_extra={
                "data_selector": endpoint_config.data_selector,
                # Wildcard selectors have no matches when every category group is empty.
                "data_selector_required": endpoint != "categories",
            },
            resume_hook=save_checkpoint,
            initial_paginator_state={"completed": resume.completed} if resume else None,
        )
    else:
        config: RESTAPIConfig = {
            "client": client_config,
            "resources": [
                {
                    "name": endpoint,
                    "table_name": endpoint,
                    "write_disposition": "replace",
                    "table_format": "delta",
                    "endpoint": {
                        "path": endpoint_config.path,
                        "data_selector": endpoint_config.data_selector,
                        "data_selector_required": True,
                    },
                }
            ],
        }
        resource = rest_api_resource(config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(endpoint_config.primary_keys),
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        sort_mode=None,
        supports_resume=endpoint_config.fanout is not None,
    )
