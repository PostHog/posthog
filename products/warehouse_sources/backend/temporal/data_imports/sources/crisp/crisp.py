import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.crisp.settings import ENDPOINTS, CrispEndpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crisp import CrispSourceConfig


@frozen
class CrispResumeConfig:
    paginator_state: dict[str, Any]
    started_at: str | None = None


class CrispPathPaginator(PageNumberPaginator):
    def __init__(self, page_size: int | None = None) -> None:
        super().__init__(base_page=1)
        self.page_size = page_size

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if self.page_size is not None and data is not None and len(data) < self.page_size:
            self._has_next_page = False
            return
        super().update_state(response, data)

    def init_request(self, request: Request) -> None:
        self.update_request(request)

    def update_request(self, request: Request) -> None:
        if request.url is None:
            raise ValueError("Crisp pagination requires a request URL")
        request.url = f"{request.url.rsplit('/', 1)[0]}/{self.page}"


class CrispMessagesPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self.timestamp_before: int | None = None

    def init_request(self, request: Request) -> None:
        self.update_request(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if not data:
            self._has_next_page = False
            return
        oldest = min(int(row["timestamp"]) for row in data)
        if self.timestamp_before is not None and oldest >= self.timestamp_before:
            raise ValueError("Crisp message pagination did not advance")
        self.timestamp_before = oldest

    def update_request(self, request: Request) -> None:
        if self.timestamp_before is not None:
            if request.params is None:
                request.params = {}
            request.params["timestamp_before"] = self.timestamp_before

    def get_resume_state(self) -> dict[str, Any] | None:
        return {"timestamp_before": self.timestamp_before} if self.has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self.timestamp_before = int(state["timestamp_before"])


def client_config(config: CrispSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": f"https://api.crisp.chat/{api_version}/",
        "auth": {"type": "http_basic", "username": config.token_identifier, "password": config.token_key},
        "headers": {"X-Crisp-Tier": "website", "Accept": "application/json"},
        # operators/list returns pending-invitation credentials that the sample scrubbers do not redact.
        "capture": False,
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 60),
        # Crisp sends no Retry-After with a 429, and the default five tries end before its
        # rate limit clears. Nine tries keep one request waiting inside the retry budget.
        "max_retries": 9,
        "retry_budget_seconds": 240,
        "retry_after_max_seconds": 120,
    }


def endpoint_config(endpoint: CrispEndpoint, website_id: str) -> Endpoint:
    response_actions: list[ResponseAction] = [
        {
            "status_code": 200,
            "json_field": "error",
            "json_values": [True],
            "action": "raise",
            "message": "Crisp returned an API error",
        }
    ]
    if endpoint.name in ("conversations", "people"):
        response_actions.append({"status_code": 416, "action": "ignore"})
    paginator: BasePaginator
    if endpoint.pagination == "messages":
        paginator = CrispMessagesPaginator()
    elif endpoint.pagination == "single":
        paginator = SinglePagePaginator()
    else:
        # Other lists have no documented page size, so a short page cannot prove that they ended.
        per_page = endpoint.params.get("per_page")
        paginator = CrispPathPaginator(page_size=int(per_page) if per_page is not None else None)
    return {
        "path": endpoint.path.replace("{website_id}", quote(website_id, safe="")),
        "params": dict(endpoint.params),
        "paginator": paginator,
        "data_selector": "data",
        "data_selector_required": True,
        "response_actions": response_actions,
    }


def format_updated_since(value: datetime) -> str:
    utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def list_params(endpoint: CrispEndpoint, inputs: SourceInputs) -> dict[str, Any]:
    if not (inputs.should_use_incremental_field and endpoint.updated_since_param):
        return dict(endpoint.params)
    params: dict[str, Any] = dict(endpoint.incremental_params)
    if inputs.db_incremental_field_last_value is not None:
        params[endpoint.updated_since_param] = format_updated_since(inputs.db_incremental_field_last_value)
    return params


def resource_config(endpoint: CrispEndpoint, website_id: str, inputs: SourceInputs) -> EndpointResource:
    config = endpoint_config(endpoint, website_id)
    config["params"] = list_params(endpoint, inputs)
    return {
        "name": endpoint.name,
        "table_name": endpoint.name,
        "write_disposition": "replace",
        "endpoint": config,
    }


def parent_path_map(
    field: str, included: list[str], updated_before: datetime | None = None
) -> Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]:
    cutoff_ms = updated_before.timestamp() * 1000 if updated_before is not None else None

    def encode_path(row: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        # A resumed attempt skips the conversations that an earlier attempt finished, even when they
        # changed since then. Messages of a conversation that changed after the run started could move
        # the watermark past that change, so the next run reads the conversation instead.
        updated_at = row.get("updated_at")
        if cutoff_ms is not None and isinstance(updated_at, int | float) and updated_at > cutoff_ms:
            return []
        # The fan-out fails on a parent row that lacks an included field.
        return {**dict.fromkeys(included), **row, "_path_id": quote(str(row[field]), safe="")}

    return encode_path


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    for name in ("created_at", "updated_at", "conversation_updated_at", "timestamp", "dispatched_at", "waiting_since"):
        value = row.get(name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[name] = datetime.fromtimestamp(value / 1000, tz=UTC)
    return row


def normalize_operator(row: dict[str, Any]) -> dict[str, Any]:
    # Pending invitations include credentials, so only joined operators enter the warehouse.
    return {"type": row["type"], **row["details"]}


def credential_resource(config: CrispSourceConfig, team_id: int, api_version: str, schema_name: str | None) -> Resource:
    if schema_name is None:
        endpoint: Endpoint = {
            "path": f"website/{quote(config.website_id, safe='')}",
            "paginator": "single_page",
            "data_selector": "data",
            "data_selector_required": True,
        }
    else:
        settings = schema_for_resource(ENDPOINTS, schema_name)
        if settings.fanout is not None:
            settings = ENDPOINTS[settings.fanout.parent_name]
        endpoint = endpoint_config(settings, config.website_id)
        endpoint["paginator"] = "single_page"
    client = client_config(config, api_version)
    # The probe runs inside a web request, so it keeps the default retries to answer before the gateway timeout.
    client.pop("max_retries")
    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [{"name": "credential_probe", "endpoint": endpoint}],
    }
    return rest_api_resource(rest_config, team_id, "crisp_credential_probe", None)


def crisp_source(
    config: CrispSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[CrispResumeConfig],
    api_version: str,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, inputs.schema_name)
    resume = manager.load_state()
    incremental = inputs.should_use_incremental_field and bool(settings.incremental_fields)
    defer_changed = incremental and settings.fanout is not None
    started_at = (
        datetime.fromisoformat(resume.started_at)
        if resume is not None and resume.started_at is not None
        else datetime.now(UTC)
    )

    def save_state(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(
                CrispResumeConfig(paginator_state=state, started_at=started_at.isoformat() if defer_changed else None)
            )

    initial_state = resume.paginator_state if resume is not None else None
    if settings.fanout is not None:
        parent = ENDPOINTS[settings.fanout.parent_name]
        parent_endpoint = endpoint_config(parent, config.website_id)
        parent_endpoint.pop("params", None)
        child_endpoint = endpoint_config(settings, config.website_id)
        child_endpoint.pop("params", None)
        child_endpoint["response_actions"] = [
            *settings.fanout.child_response_actions,
            *(child_endpoint.get("response_actions") or []),
        ]
        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=settings.name,
            fanout=dataclasses.replace(settings.fanout, parent_params=list_params(parent, inputs))
            if incremental
            else settings.fanout,
            client_config=client_config(config, api_version),
            path_format_values={"website_id": quote(config.website_id, safe="")},
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value if incremental else None,
            should_use_incremental_field=incremental,
            incremental_field=inputs.incremental_field,
            # The watermark filters the parent list, so it binds to no child request param.
            incremental_config_factory=lambda _field: None,
            parent_endpoint_extra=parent_endpoint,
            child_endpoint_extra=child_endpoint,
            parent_data_map=parent_path_map(
                settings.fanout.resolve_param,
                settings.fanout.include_from_parent,
                started_at if defer_changed else None,
            ),
            page_size_param=None,
            resume_hook=save_state,
            initial_paginator_state=initial_state,
        )
        assert isinstance(resource, Resource)
    else:
        rest_config: RESTAPIConfig = {
            "client": client_config(config, api_version),
            "resources": [resource_config(settings, config.website_id, inputs)],
        }
        resource = rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None,
            resume_hook=save_state,
            initial_paginator_state=initial_state,
        )
    if settings.name == "operators":
        resource.add_filter(lambda row: row.get("type") in ("operator", "sandbox"))
        resource.add_map(normalize_operator)
    resource.add_map(normalize_row)
    return SourceResponse(
        name=settings.name,
        items=lambda: resource,
        primary_keys=list(settings.primary_keys),
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if settings.partition_key else None,
        partition_format="month" if settings.partition_key else None,
        # "desc" moves the watermark only when the run completes. Crisp does not document the
        # direction of its date order, so a watermark from a partial run could skip rows.
        sort_mode="desc" if settings.pagination == "messages" or inputs.should_use_incremental_field else None,
        on_complete=manager.clear_state,
    )
