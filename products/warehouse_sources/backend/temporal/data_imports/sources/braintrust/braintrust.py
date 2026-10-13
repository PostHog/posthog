from typing import Any
from urllib.parse import urlsplit

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.braintrust.settings import (
    AUTH_ERRORS,
    ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braintrust import (
    BraintrustSourceConfig,
)


@frozen
class BraintrustResumeConfig:
    cursor: str


def validated_api_url(api_url: str, team_id: int) -> str:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (  # noqa: PLC0415 -- Keep Django models off the config import path.
        ValidateDatabaseHostMixin,
    )

    error = "Enter an HTTPS API URL without a path, query, or credentials."
    try:
        parsed = urlsplit(api_url.strip())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise ValueError(error)
    except ValueError:
        raise ValueError(error) from None
    valid, _ = ValidateDatabaseHostMixin().is_database_host_valid(parsed.hostname, team_id)
    if not valid:
        raise ValueError("The Braintrust API host must resolve to a public IP address.")
    return f"https://{parsed.netloc}"


def validate_credentials(config: BraintrustSourceConfig, team_id: int) -> tuple[bool, str | None]:
    if not config.api_key.strip():
        return False, AUTH_ERRORS[401]
    try:
        base_url = validated_api_url(config.api_url, team_id)
    except ValueError as error:
        return False, str(error)
    client = RESTClient(
        base_url=base_url,
        auth=BearerTokenAuth(config.api_key),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=(10, 60),
    )
    try:
        list(
            client.paginate(
                path="v1/project",
                params={"limit": 1},
                paginator=SinglePagePaginator(),
                data_selector="objects",
                data_selector_required=True,
                data_selector_malformed_retryable=True,
            )
        )
    except HTTPError as error:
        if error.response is not None and error.response.status_code in AUTH_ERRORS:
            return False, AUTH_ERRORS[error.response.status_code]
        raise
    return True, None


def braintrust_source(
    config: BraintrustSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BraintrustResumeConfig],
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    base_url = validated_api_url(config.api_url, team_id)
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "auth": {"type": "bearer", "token": config.api_key},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": (10, 60),
            "paginator": {
                "type": "cursor",
                "cursor_path": "objects[-1].id",
                "cursor_param": "starting_after",
                "raise_on_repeated_cursor": True,
            },
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": f"v1/{path}",
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "objects",
                    "data_selector_required": True,
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(BraintrustResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.cursor} if resume else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        sort_mode="desc",
        on_complete=resumable_source_manager.clear_state,
    )
