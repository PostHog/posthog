import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from requests import HTTPError, PreparedRequest, Response, Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_meraki.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    NOT_FOUND_ERROR,
    ORGANIZATION_ERROR,
    PERMISSION_ERROR,
    REGION_ERROR,
    REGION_HOSTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_adapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ciscomeraki import (
        CiscoMerakiSourceConfig,
    )


@frozen
class CiscoMerakiResumeConfig:
    next_url: str | None = None
    completed: bool = False


class _MerakiSession(Session):
    """Keep credentialed redirects, pagination links, and resume URLs on Meraki-owned HTTPS hosts."""

    def __init__(self, allowed_domain: str, api_key: str) -> None:
        super().__init__()
        self._allowed_domain = allowed_domain
        adapter = make_tracked_adapter(redact_values=(api_key,))
        self.mount("https://", adapter)
        self.mount("http://", adapter)

    def send(self, request: PreparedRequest, **kwargs: Any) -> Response:
        split = urlsplit(request.url or "")
        hostname = (split.hostname or "").lower()
        if (
            split.scheme.lower() != "https"
            or split.port not in (None, 443)
            or (hostname != self._allowed_domain and not hostname.endswith(f".{self._allowed_domain}"))
        ):
            raise ValueError("Refusing to send Cisco Meraki credentials to an unapproved destination")
        return super().send(request, **kwargs)


def client_config(config: "CiscoMerakiSourceConfig", api_version: str) -> ClientConfig:
    host = REGION_HOSTS.get(config.region)
    if host is None:
        raise ValueError(REGION_ERROR)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", config.organization_id):
        raise ValueError(ORGANIZATION_ERROR)

    allowed_domain = host.removeprefix("api.")
    return {
        "base_url": f"https://{host}/api/{api_version}/organizations/{config.organization_id}/",
        # Meraki supports this header across shard redirects, where requests removes bearer authentication.
        "auth": {"type": "api_key", "name": "X-Cisco-Meraki-API-Key", "api_key": config.api_key, "location": "header"},
        "paginator": "header_link",
        "session": _MerakiSession(allowed_domain, config.api_key),
        "request_timeout": (10, 60),
    }


def validate_credentials(
    config: "CiscoMerakiSourceConfig", api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    try:
        settings = client_config(config, api_version)
    except ValueError as error:
        return False, str(error)

    endpoint = schema_for_resource(ENDPOINTS, schema_name) if schema_name is not None else None
    client = RESTClient(
        base_url=settings["base_url"],
        auth=APIKeyAuth(api_key=config.api_key, name="X-Cisco-Meraki-API-Key"),
        paginator=SinglePagePaginator(),
        session=settings["session"],
        request_timeout=(10, 30),
    )
    try:
        next(
            client.paginate(
                path=endpoint.path if endpoint else settings["base_url"].rstrip("/"),
                params={"perPage": 4} if endpoint else {},
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        if status == 404:
            return False, NOT_FOUND_ERROR
        raise
    return True, None


def cisco_meraki_source(
    config: "CiscoMerakiSourceConfig",
    endpoint_name: str,
    api_version: str,
    team_id: int,
    job_id: str,
    manager: "ResumableSourceManager[CiscoMerakiResumeConfig]",
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, endpoint_name)
    rest_config: RESTAPIConfig = {
        "client": client_config(config, api_version),
        "resources": [
            {
                "name": endpoint_name,
                "endpoint": {"path": endpoint.path, "data_selector": "$", "params": {"perPage": endpoint.page_size}},
            }
        ],
    }
    resume = manager.load_state() if manager.can_resume() else None
    if resume and resume.completed:
        return SourceResponse(
            name=endpoint_name,
            items=lambda: iter(()),
            primary_keys=[endpoint.primary_key],
            on_complete=manager.clear_state,
        )

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        manager.save_state(
            CiscoMerakiResumeConfig(next_url=str(state["next_url"]))
            if state and state.get("next_url")
            else CiscoMerakiResumeConfig(completed=True)
        )

    resource = rest_api_resource(
        rest_config,
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"next_url": resume.next_url} if resume and resume.next_url else None,
    )
    return SourceResponse(
        name=endpoint_name,
        items=lambda: resource,
        primary_keys=[endpoint.primary_key],
        on_complete=manager.clear_state,
    )
