from typing import Any
from urllib.parse import urlsplit

from requests import PreparedRequest, Request

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.looker import LookerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.looker.settings import ENDPOINTS, PAGE_SIZE

REQUEST_TIMEOUT = (10.0, 30.0)


@frozen
class LookerResumeConfig:
    offset: int


class LookerAuth(OAuth2Auth):
    def _build_token_request_body(self) -> dict[str, str]:
        # Looker login accepts API credentials without an OAuth grant_type parameter.
        return {"client_id": self.client_id or "", "client_secret": self.client_secret or ""}

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        super().__call__(request)
        request.headers["Authorization"] = f"token {self.token}"
        return request


def api_base_url(instance_url: str, api_version: str) -> str:
    value = instance_url.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        valid_port = parsed.port is None or parsed.port > 0
    except ValueError:
        raise ValueError("Enter a valid HTTPS URL for your Looker API instance.") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not valid_port
        or not value.isascii()
        or any(character.isspace() for character in value)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/api", f"/api/{api_version}")
    ):
        raise ValueError(
            "Enter the HTTPS instance URL, with its API port. Remove any credentials, query, or other path."
        )
    return f"https://{parsed.netloc}/api/{api_version}"


def create_auth(config: LookerSourceConfig, team_id: int, api_version: str) -> LookerAuth:
    base_url = api_base_url(config.instance_url, api_version)
    host_allowed, error = _is_host_safe(urlsplit(base_url).hostname or "", team_id)
    if not host_allowed:
        raise ValueError(f"Looker host not allowed: {error}")
    return LookerAuth(
        token_url=f"{base_url}/login",
        client_id=config.client_id,
        client_secret=config.client_secret,
    )


def get_resource(endpoint: str, page_size: int = PAGE_SIZE) -> EndpointResource:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    params: dict[str, Any] = {}
    if settings.sorts:
        params["sorts"] = settings.sorts
    if settings.fields:
        params["fields"] = settings.fields
    if settings.active_only:
        params["deleted"] = "false"
    return {
        "name": endpoint,
        "table_name": endpoint,
        "primary_key": settings.primary_key,
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": {
            "path": settings.path,
            "params": params,
            "data_selector": "$",
            "data_selector_required": True,
            "paginator": {"type": "offset", "limit": page_size, "total_path": None}
            if settings.paginated
            else "single_page",
        },
    }


def rest_config(base_url: str, auth: LookerAuth, endpoint: str, page_size: int = PAGE_SIZE) -> RESTAPIConfig:
    return {
        "client": {
            "base_url": base_url,
            "auth": auth,
            "headers": {"Accept": "application/json"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT,
            "retry_budget_seconds": 120,
            "retry_after_max_seconds": 60,
            "capture": False,
        },
        "resources": [get_resource(endpoint, page_size)],
    }


def probe_credentials(config: LookerSourceConfig, team_id: int, api_version: str, schema_name: str | None) -> None:
    auth = create_auth(config, team_id, api_version)
    base_url = api_base_url(config.instance_url, api_version)
    if schema_name is None:
        auth(Request("GET", base_url).prepare())
        return
    resource_config = rest_config(base_url, auth, schema_name, page_size=1)
    resource_config["client"]["max_retries"] = 1
    resource = rest_api_resource(resource_config, team_id, "", None)
    next(iter(resource), None)


def looker_source(
    config: LookerSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[LookerResumeConfig],
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    auth = create_auth(config, team_id, api_version)
    initial_state: dict[str, Any] | None = None
    if settings.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = {"offset": resume.offset}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None and state.get("offset") is not None:
            resumable_source_manager.save_state(LookerResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config(api_base_url(config.instance_url, api_version), auth, endpoint),
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[settings.primary_key],
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if settings.partition_key else None,
        partition_format="month" if settings.partition_key else None,
        sort_mode=None,
        supports_resume=settings.paginated,
    )
