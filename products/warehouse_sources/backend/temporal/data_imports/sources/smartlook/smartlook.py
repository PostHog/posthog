from typing import Any

from requests.exceptions import HTTPError, RequestException
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientNonRetryableError,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartlook import (
    SmartlookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlook.settings import (
    ENDPOINTS,
    SmartlookEndpoint,
)

REGION_URLS = {"eu": "https://api.eu.smartlook.cloud", "us": "https://api.us.smartlook.cloud"}


@frozen
class SmartlookResumeConfig:
    paginator_state: dict[str, Any]


def client_config(config: SmartlookSourceConfig) -> ClientConfig:
    if config.region not in REGION_URLS:
        raise ValueError("Select the EU or US region from your Smartlook project settings.")
    return {
        "base_url": REGION_URLS[config.region],
        "auth": {"type": "bearer", "token": config.api_token},
        "headers": {"Accept": "application/json"},
        "paginator": {"type": "json_response", "next_url_path": "_links.nextPage"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 30),
        "retry_budget_seconds": 180,
        "retry_after_max_seconds": 60,
    }


def validate_credentials(config: SmartlookSourceConfig) -> tuple[bool, str | None]:
    connection = client_config(config)
    client = RESTClient(
        base_url=connection["base_url"],
        auth=BearerTokenAuth(token=config.api_token),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=(10, 15),
        max_retry_attempts=1,
        session=make_tracked_session(retry=Retry(total=0), redact_values=(config.api_token,)),
    )
    try:
        next(client.paginate("/api/v1/me", paginator=SinglePagePaginator(), data_selector="$"))
        return True, None
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, "Smartlook rejected the API token. Create a new token in your project settings."
        if status == 403:
            return False, "Smartlook denied API access. Check the token, project region, and REST API access."
        return False, "Smartlook could not validate the token. Try again later."
    except RESTClientRetryableError:
        return False, "Smartlook is unavailable or reached its API request limit. Try again later."
    except RESTClientNonRetryableError:
        return False, "Smartlook returned an invalid response. Check the project region and try again."
    except RequestException:
        return False, "Could not connect to Smartlook. Check the project region and try again."


def endpoint_config(endpoint: SmartlookEndpoint, api_version: str) -> Endpoint:
    result: Endpoint = {
        "path": endpoint.path.replace("{api_version}", api_version),
        "method": endpoint.method,
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
    }
    if endpoint.method == "POST":
        assert endpoint.sort_field is not None
        result["json"] = {"filters": [], "sort": {endpoint.sort_field: "asc"}}
    return result


def smartlook_source(
    config: SmartlookSourceConfig,
    manager: ResumableSourceManager[SmartlookResumeConfig],
    inputs: SourceInputs,
    api_version: str,
) -> SourceResponse:
    settings = ENDPOINTS[inputs.schema_name]
    connection = client_config(config)
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(SmartlookResumeConfig(paginator_state=state))

    if settings.fanout is not None:
        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=settings.name,
            fanout=settings.fanout,
            client_config=connection,
            path_format_values={"api_version": api_version},
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=endpoint_config(ENDPOINTS[settings.fanout.parent_name], api_version),
            child_endpoint_extra=endpoint_config(settings, api_version),
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )
    else:
        endpoint = endpoint_config(settings, api_version)
        endpoint["params"] = {"limit": settings.page_size}
        rest_config: RESTAPIConfig = {
            "client": connection,
            "resources": [
                {
                    "name": settings.name,
                    "endpoint": endpoint,
                    "write_disposition": "replace",
                    "table_format": "delta",
                }
            ],
        }
        resource = rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )
    return SourceResponse(
        name=settings.name,
        items=lambda: resource,
        primary_keys=list(settings.primary_keys),
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if settings.partition_key else None,
        partition_format="month" if settings.partition_key else None,
    )
