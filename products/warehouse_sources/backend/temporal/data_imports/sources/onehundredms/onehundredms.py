from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import jwt
from requests import PreparedRequest

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.settings import (
    API_BASE_URL,
    ENDPOINTS,
    PARTITION_KEY,
    PRIMARY_KEYS,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onehundredms import (
        OneHundredMsSourceConfig,
    )


@frozen
class OneHundredMsResumeConfig:
    cursor: str


class ManagementTokenAuth(BearerTokenAuth):
    def __init__(self, app_access_key: str, app_secret: str) -> None:
        super().__init__()
        self.app_access_key = app_access_key
        self.app_secret = app_secret
        self.expires_at = 0

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        now = int(datetime.now(UTC).timestamp())
        if self.token is None or now >= self.expires_at - 60:
            self.expires_at = now + 24 * 60 * 60
            self.token = jwt.encode(
                {
                    "access_key": self.app_access_key,
                    "type": "management",
                    "version": 2,
                    "jti": str(uuid4()),
                    "iat": now,
                    "nbf": now,
                    "exp": self.expires_at,
                },
                self.app_secret,
                algorithm="HS256",
            )
        return super().__call__(request)

    def secret_values(self) -> tuple[str, ...]:
        return (self.app_access_key, self.app_secret, *super().secret_values())


def validate_credentials(config: OneHundredMsSourceConfig, api_version: str, schema_name: str | None) -> None:
    path = schema_for_resource(ENDPOINTS, schema_name or "sessions")
    client = RESTClient(
        base_url=f"{API_BASE_URL}/{api_version}/",
        auth=ManagementTokenAuth(config.app_access_key, config.app_secret),
        paginator=SinglePagePaginator(),
        max_retry_attempts=1,
        request_timeout=(10, 30),
        allow_redirects=False,
    )
    next(client.paginate(path=path, params={"limit": 10}, data_selector="data"))


def onehundredms_source(
    config: OneHundredMsSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[OneHundredMsResumeConfig],
    api_version: str,
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, inputs.schema_name)
    params: dict[str, Any] = {"limit": 100}
    incremental = inputs.schema_name == "sessions" and inputs.should_use_incremental_field
    if inputs.schema_name == "sessions":
        params["active"] = "false"
        if incremental and inputs.db_incremental_field_last_value is not None:
            value = inputs.db_incremental_field_last_value
            timestamp = (
                value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            )
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            params["after"] = timestamp.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": "data",
        "data_selector_required": True,
    }
    resource_config: EndpointResource = {
        "name": inputs.schema_name,
        "table_format": "delta",
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        "endpoint": endpoint_config,
    }
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{API_BASE_URL}/{api_version}/",
            "auth": ManagementTokenAuth(config.app_access_key, config.app_secret),
            "paginator": JSONResponseCursorPaginator(
                cursor_path="last", cursor_param="start", raise_on_repeated_cursor=True
            ),
            "allow_redirects": False,
            "request_timeout": (10, 60),
        },
        "resources": [resource_config],
    }
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            manager.save_state(OneHundredMsResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.cursor} if resume else None,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS,
        partition_keys=[PARTITION_KEY],
        partition_mode="datetime",
        partition_format="month",
        # The API offers no ascending sort, so advance the watermark only after the complete scan.
        sort_mode="desc",
    )
