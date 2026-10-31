from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qdrant import QdrantSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qdrant.settings import (
    ACCOUNT_ERROR,
    ACCOUNTS_PATH,
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    PERMISSION_ERROR,
    USAGE_METRICS_LOOKBACK,
    QdrantEndpoint,
    QdrantParent,
)


@frozen
class QdrantResumeConfig:
    cursor: str


def account_id(config: QdrantSourceConfig) -> str:
    try:
        return str(UUID(config.account_id))
    except ValueError as error:
        raise ValueError(ACCOUNT_ERROR) from error


def endpoint_config(endpoint: str) -> QdrantEndpoint:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown Qdrant table: {endpoint}")
    return ENDPOINTS[endpoint]


def _account_path(path: str, account: str) -> str:
    return path.replace("{account_id}", account)


def validate_credentials(config: QdrantSourceConfig, schema_name: str | None = None) -> tuple[bool, str | None]:
    try:
        account = account_id(config)
    except ValueError:
        return False, ACCOUNT_ERROR

    if not config.api_key.strip() or not config.api_key.isascii() or any(c in config.api_key for c in "\r\n"):
        return False, AUTH_ERROR

    path, params = ACCOUNTS_PATH, {}
    if schema_name:
        endpoint = endpoint_config(schema_name)
        # A fan-out table needs the same permission as its parent listing, which has no path params to fill.
        probe: QdrantEndpoint | QdrantParent = endpoint.parent or endpoint
        path = _account_path(probe.path, account)
        params = {"pageSize": 1} if probe.paginated else {}
    client = RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=f"apikey {config.api_key}"),
        paginator=SinglePagePaginator(),
        request_timeout=30,
        allow_redirects=False,
        allowed_hosts=[],
    )
    try:
        rows = next(client.paginate(path=path, params=params, data_selector="items"))
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


def _list_endpoint(path: str, paginated: bool) -> Endpoint:
    if not paginated:
        return {"path": path, "data_selector": "items", "paginator": "single_page"}
    return {
        "path": path,
        "data_selector": "items",
        "params": {"pageSize": PAGE_SIZE},
        "paginator": {
            "type": "cursor",
            "cursor_path": "nextPageToken",
            "cursor_param": "pageToken",
            "raise_on_repeated_cursor": True,
        },
    }


def usage_metrics_since(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> str:
    since = datetime.now(UTC) - USAGE_METRICS_LOOKBACK
    last_value = parse_datetime_value(db_incremental_field_last_value) if should_use_incremental_field else None
    if last_value is not None and last_value > since:
        since = last_value
    return since.isoformat().replace("+00:00", "Z")


def usage_metric_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    cluster_id = response.get("cluster_id")
    rows: list[dict[str, Any]] = []

    def add_series(node_id: str, series: dict[str, Any]) -> None:
        for metric, points in series.items():
            if metric == "nodes" or not isinstance(points, list):
                continue
            for point in points:
                rows.append(
                    {
                        "cluster_id": cluster_id,
                        # Cluster-wide series have no node; an empty id keeps the primary key non-null.
                        "node_id": node_id,
                        "metric": metric,
                        "timestamp": point.get("timestamp"),
                        "value": point.get("value"),
                    }
                )

    add_series("", response)
    for node in response.get("nodes") or []:
        add_series(node.get("nodeId") or "", node)
    return rows


def _fanout_resource(
    client_config: ClientConfig,
    endpoint: str,
    config: QdrantEndpoint,
    parent: QdrantParent,
    account: str,
    child_params: dict[str, Any],
    incremental: bool,
    team_id: int,
    job_id: str,
) -> Any:
    child_endpoint = _list_endpoint(_account_path(config.path, account), config.paginated)
    if endpoint == "cluster_usage_metrics":
        child_endpoint["data_selector"] = "$"
    child_endpoint["params"] = {
        **(child_endpoint.get("params") or {}),
        **child_params,
        **{
            param: {"type": "resolve", "resource": parent.name, "field": field}
            for param, field in parent.path_params.items()
        },
    }
    if parent.ignored_statuses:
        child_endpoint["response_actions"] = [
            {"status_code": status, "action": "ignore"} for status in parent.ignored_statuses
        ]

    def child_row_map(row: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        for field, column in parent.include.items():
            row[column] = row.pop(f"_{parent.name}_{field}", None)
        return usage_metric_rows(row) if endpoint == "cluster_usage_metrics" else row

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {"name": parent.name, "endpoint": _list_endpoint(_account_path(parent.path, account), parent.paginated)},
            {
                "name": endpoint,
                "table_name": endpoint,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
                "endpoint": child_endpoint,
                "include_from_parent": list(parent.include),
                "data_map": child_row_map,
            },
        ],
    }
    resources = rest_api_resources(rest_config, team_id, job_id, None)
    return next(resource for resource in resources if resource.name == endpoint)


def qdrant_source(
    config: QdrantSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[QdrantResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    settings = endpoint_config(endpoint)
    account = account_id(config)
    client_config: ClientConfig = {
        "base_url": BASE_URL,
        "auth": {"type": "api_key", "name": "Authorization", "api_key": f"apikey {config.api_key}"},
        "request_timeout": 30,
        "allow_redirects": False,
        "allowed_hosts": [],
    }

    if settings.parent is not None:
        child_params = (
            {"since": usage_metrics_since(should_use_incremental_field, db_incremental_field_last_value)}
            if endpoint == "cluster_usage_metrics"
            else {}
        )
        resource = _fanout_resource(
            client_config,
            endpoint,
            settings,
            settings.parent,
            account,
            child_params,
            should_use_incremental_field,
            team_id,
            job_id,
        )
    else:
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resources": [
                {
                    "name": endpoint,
                    "table_name": endpoint,
                    "write_disposition": "replace",
                    "endpoint": _list_endpoint(_account_path(settings.path, account), settings.paginated),
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
        primary_keys=list(settings.primary_keys),
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if settings.partition_key else None,
        partition_format="month" if settings.partition_key else None,
        sort_mode=None,
    )
