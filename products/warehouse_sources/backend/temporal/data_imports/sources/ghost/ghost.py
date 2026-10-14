import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import jwt
from requests import PreparedRequest
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.ghost.settings import ENDPOINTS, REQUEST_TIMEOUT

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ghost import (
        GhostSourceConfig,
    )

AUTH_ERROR = "Your Ghost Admin API key is invalid or expired. Create a new key in Ghost settings and reconnect."
PERMISSION_ERROR = "Your Ghost Admin API key cannot read this table. Check the integration permissions in Ghost."
KEY_ERROR = "Enter a Ghost Admin API key in the id:secret format from a custom integration."
DOMAIN_ERROR = "Enter your Ghost admin domain or HTTPS URL without credentials, a query, or a fragment."


class GhostConfigError(ValueError):
    pass


@frozen
class GhostResumeConfig:
    page: int = 1
    finished: bool = False


class GhostAdminAuth(AuthConfigBase):
    def __init__(self, api_key: str) -> None:
        if not re.fullmatch(r"[0-9a-fA-F]{24}:[0-9a-fA-F]{64}", api_key):
            raise GhostConfigError(KEY_ERROR)
        self._api_key = api_key
        self._key_id, self._secret = api_key.split(":")

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        issued_at = int(datetime.now(UTC).timestamp())
        token = jwt.encode(
            {"iat": issued_at, "exp": issued_at + 300, "aud": "/admin/"},
            bytes.fromhex(self._secret),
            algorithm="HS256",
            headers={"kid": self._key_id},
        )
        request.headers["Authorization"] = f"Ghost {token}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self._api_key, self._secret)


def ghost_base_url(admin_domain: str) -> str:
    value = admin_domain.strip().rstrip("/")
    try:
        parts = urlsplit(value if "://" in value else f"https://{value}")
    except ValueError:
        raise GhostConfigError(DOMAIN_ERROR) from None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or any(character in value for character in ("\\", "%", "?", "#"))
        or any(character.isspace() for character in value)
    ):
        raise GhostConfigError(DOMAIN_ERROR)
    try:
        if parts.port is not None and parts.port != 443:
            raise GhostConfigError(DOMAIN_ERROR)
    except ValueError:
        raise GhostConfigError(DOMAIN_ERROR) from None
    path = parts.path.rstrip("/")
    if path.endswith("/ghost/api/admin"):
        path = path.removesuffix("/ghost/api/admin")
    if any(segment in (".", "..") for segment in path.split("/")):
        raise GhostConfigError(DOMAIN_ERROR)
    return f"https://{parts.netloc}{path}/ghost/api/admin/"


def client_config(config: "GhostSourceConfig", api_version: str) -> ClientConfig:
    return {
        "base_url": ghost_base_url(config.admin_domain),
        "auth": GhostAdminAuth(config.admin_api_key),
        "headers": {"Accept-Version": api_version, "Accept": "application/json"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT,
    }


def get_resource(name: str) -> EndpointResource:
    endpoint = schema_for_resource(ENDPOINTS, name)
    params: dict[str, Any] = dict(endpoint.params)
    if endpoint.paginated:
        params.update({"limit": 100, "order": "created_at asc,id asc"})
    return {
        "name": name,
        "write_disposition": "replace",
        "endpoint": {
            "path": f"{name}/",
            "params": params,
            "data_selector": name,
            "data_selector_required": True,
            "paginator": PageNumberPaginator(base_page=1, total_path="meta.pagination.pages")
            if endpoint.paginated
            else "single_page",
        },
    }


def probe_credentials(
    config: "GhostSourceConfig", api_version: str, schema_name: str | None
) -> tuple[bool, str | None]:
    name = schema_name or "posts"
    endpoint = schema_for_resource(ENDPOINTS, name)
    client = RESTClient(
        base_url=ghost_base_url(config.admin_domain),
        auth=GhostAdminAuth(config.admin_api_key),
        headers={"Accept-Version": api_version, "Accept": "application/json"},
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=REQUEST_TIMEOUT,
    )
    params: dict[str, Any] = dict(endpoint.params)
    if ENDPOINTS[name].paginated:
        params.update({"limit": 1, "page": 1})
    try:
        next(
            client.paginate(
                path=f"{name}/",
                params=params,
                paginator=SinglePagePaginator(),
                data_selector=name,
                data_selector_required=True,
            )
        )
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


def ghost_source(
    config: "GhostSourceConfig",
    inputs: "SourceInputs",
    manager: "ResumableSourceManager[GhostResumeConfig]",
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        manager.save_state(GhostResumeConfig(page=int(state["page"]) if state else 1, finished=state is None))

    resource: Resource | list[dict[str, Any]]
    if resume and resume.finished:
        resource = []
    else:
        rest_config: RESTAPIConfig = {
            "client": client_config(config, api_version),
            "resources": [get_resource(inputs.schema_name)],
        }
        resource = rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"page": resume.page} if resume else None,
        )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else list(endpoint.primary_keys),
        partition_mode="datetime" if endpoint.partition_key else "md5",
        partition_format="month" if endpoint.partition_key else None,
        partition_count=None if endpoint.partition_key else 16,
        sort_mode=None,
    )
