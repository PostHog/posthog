from typing import Any
from uuid import UUID

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qdrant import QdrantSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qdrant.settings import (
    ACCOUNT_ERROR,
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    PARTITION_KEY,
    PERMISSION_ERROR,
    PRIMARY_KEYS,
)


@frozen
class QdrantResumeConfig:
    cursor: str


def account_id(config: QdrantSourceConfig) -> str:
    try:
        return str(UUID(config.account_id))
    except ValueError as error:
        raise ValueError(ACCOUNT_ERROR) from error


def endpoint_path(endpoint: str, account: str) -> str:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown Qdrant table: {endpoint}")
    return ENDPOINTS[endpoint].format(account_id=account)


def validate_credentials(config: QdrantSourceConfig, schema_name: str | None = None) -> tuple[bool, str | None]:
    try:
        account = account_id(config)
    except ValueError:
        return False, ACCOUNT_ERROR

    if not config.api_key.strip() or not config.api_key.isascii() or any(c in config.api_key for c in "\r\n"):
        return False, AUTH_ERROR

    path = endpoint_path(schema_name, account) if schema_name else "/api/account/v1/accounts"
    client = RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=f"apikey {config.api_key}"),
        paginator=SinglePagePaginator(),
        request_timeout=30,
        allow_redirects=False,
        allowed_hosts=[],
    )
    try:
        rows = next(client.paginate(path=path, params={"pageSize": 1} if schema_name else {}, data_selector="items"))
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return False, PERMISSION_ERROR
        if status == 404:
            return False, ACCOUNT_ERROR
        raise

    if schema_name is None and not any(row.get("id") == account for row in rows):
        return False, "The Qdrant key cannot access this account. Check the account ID and key permissions."
    return True, None


def qdrant_source(
    config: QdrantSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[QdrantResumeConfig],
) -> SourceResponse:
    path = endpoint_path(endpoint, account_id(config))
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "Authorization", "api_key": f"apikey {config.api_key}"},
            "request_timeout": 30,
            "allow_redirects": False,
            "allowed_hosts": [],
        },
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "write_disposition": "replace",
                "endpoint": {
                    "path": path,
                    "data_selector": "items",
                    "params": {"pageSize": PAGE_SIZE},
                    "paginator": {
                        "type": "cursor",
                        "cursor_path": "nextPageToken",
                        "cursor_param": "pageToken",
                        "raise_on_repeated_cursor": True,
                    },
                },
            }
        ],
    }
    initial_state = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = {"cursor": resume.cursor}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(QdrantResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=endpoint,
        on_complete=resumable_source_manager.clear_state,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS,
        partition_keys=[PARTITION_KEY],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
    )
