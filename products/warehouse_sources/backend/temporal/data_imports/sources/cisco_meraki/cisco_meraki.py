import re
import json
import hashlib
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, urlsplit

from requests import HTTPError, PreparedRequest, Response, Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_meraki.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    EVENT_LOG_FLOOR,
    EVENT_PRODUCT_TYPES,
    NOT_FOUND_ERROR,
    ORGANIZATION_ERROR,
    PERMISSION_ERROR,
    REGION_ERROR,
    REGION_HOSTS,
    MerakiEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_adapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
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
    # Network-level tables resume by network: the child paths already synced, the one in progress, and its
    # paginator state. See `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed_paths: list[str] | None = None
    current_path: str | None = None
    child_state: dict[str, Any] | None = None


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
        "base_url": f"https://{host}/api/{api_version}/",
        # Meraki supports this header across shard redirects, where requests removes bearer authentication.
        "auth": {"type": "api_key", "name": "X-Cisco-Meraki-API-Key", "api_key": config.api_key, "location": "header"},
        "paginator": "header_link",
        "session": _MerakiSession(allowed_domain, config.api_key),
        "request_timeout": (10, 60),
    }


def _organization_path(path: str, config: "CiscoMerakiSourceConfig") -> str:
    return path.replace("{organization_id}", config.organization_id)


def validate_credentials(
    config: "CiscoMerakiSourceConfig", api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    try:
        settings = client_config(config, api_version)
    except ValueError as error:
        return False, str(error)

    endpoint = schema_for_resource(ENDPOINTS, schema_name) if schema_name is not None else None
    if endpoint is not None and endpoint.fanout is not None:
        # Network-level tables need the same read access as the networks they fan out over.
        endpoint = ENDPOINTS[endpoint.fanout.parent_name]
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
                path=_organization_path(endpoint.path if endpoint else "organizations/{organization_id}", config),
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


class _EventLogPaginator(HeaderLinkPaginator):
    """Walks a network event log from the newest page to older pages, which is the order Meraki pages it in.

    Meraki pages the log by time window, so an empty page can still link to older events. The walk stops when a
    page reaches past the watermark, or when the older page starts before the watermark or the log floor.
    """

    def __init__(self, stop_before: datetime | None) -> None:
        super().__init__(links_next_key="prev")
        self._stop_before = stop_before or EVENT_LOG_FLOOR

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if data and self._reaches_watermark(data):
            self._has_next_page = False
            return
        prev_link = response.links.get("prev")
        ending_before = _ending_before(prev_link.get("url")) if prev_link else None
        if ending_before is None and not data:
            # An empty page whose older link carries no time cannot show that the walk moves toward the floor.
            self._has_next_page = False
            return
        if ending_before is not None and ending_before < self._stop_before:
            self._has_next_page = False
            return
        super().update_state(response, data)

    def _reaches_watermark(self, events: list[Any]) -> bool:
        for event in events:
            occurred_at = parse_datetime_value(event.get("occurredAt")) if isinstance(event, dict) else None
            if occurred_at is not None and occurred_at < self._stop_before:
                return True
        return False


def _ending_before(url: str | None) -> datetime | None:
    values = parse_qs(urlsplit(url).query).get("endingBefore") if url else None
    return parse_datetime_value(values[0]) if values else None


def _network_product_types(network: dict[str, Any]) -> list[dict[str, Any]]:
    product_types = network.get("productTypes") or []
    return [
        {**network, "productType": product_type}
        for product_type in product_types
        if product_type in EVENT_PRODUCT_TYPES
    ]


def _with_event_id(event: dict[str, Any]) -> dict[str, Any]:
    content = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)
    return {"id": hashlib.sha256(content.encode()).hexdigest(), **event}


def _network_source(
    config: "CiscoMerakiSourceConfig",
    endpoint: MerakiEndpoint,
    api_version: str,
    team_id: int,
    job_id: str,
    manager: "ResumableSourceManager[CiscoMerakiResumeConfig]",
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    assert endpoint.fanout is not None
    resume = manager.load_state() if manager.can_resume() else None
    initial_state = (
        {"completed": resume.completed_paths or [], "current": resume.current_path, "child_state": resume.child_state}
        if resume is not None and (resume.completed_paths or resume.current_path)
        else None
    )

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(
                CiscoMerakiResumeConfig(
                    completed_paths=state.get("completed"),
                    current_path=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    is_event_log = endpoint.name == "network_events"
    incremental = is_event_log and should_use_incremental_field
    stop_before = parse_datetime_value(db_incremental_field_last_value) if incremental else None
    child_endpoint_extra: dict[str, Any] = {"data_selector": endpoint.data_selector}
    if is_event_log:
        child_endpoint_extra["paginator"] = _EventLogPaginator(stop_before)

    resource = cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint.name,
            fanout=endpoint.fanout,
            client_config=client_config(config, api_version),
            path_format_values={"organization_id": config.organization_id},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            should_use_incremental_field=incremental,
            # The event log has no time filter, so the paginator bounds an incremental read instead.
            incremental_config_factory=lambda _field: None,
            parent_endpoint_extra={"data_selector": "$"},
            child_endpoint_extra=cast(Any, child_endpoint_extra),
            parent_data_map=_network_product_types if is_event_log else None,
            page_size_param="perPage",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )
    if is_event_log:
        resource = resource.add_map(_with_event_id)

    return SourceResponse(
        name=endpoint.name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        on_complete=manager.clear_state,
        # Each network's event log arrives newest first, so the watermark advances only when the sync completes.
        sort_mode="desc" if is_event_log else "asc",
        partition_mode="datetime" if is_event_log else None,
        partition_format="month" if is_event_log else None,
        partition_keys=["occurredAt"] if is_event_log else None,
    )


def cisco_meraki_source(
    config: "CiscoMerakiSourceConfig",
    endpoint_name: str,
    api_version: str,
    team_id: int,
    job_id: str,
    manager: "ResumableSourceManager[CiscoMerakiResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, endpoint_name)
    if endpoint.fanout is not None:
        return _network_source(
            config,
            endpoint,
            api_version,
            team_id,
            job_id,
            manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    rest_config: RESTAPIConfig = {
        "client": client_config(config, api_version),
        "resources": [
            {
                "name": endpoint_name,
                "endpoint": {
                    "path": _organization_path(endpoint.path, config),
                    "data_selector": "$",
                    "params": {"perPage": endpoint.page_size},
                },
            }
        ],
    }
    resume = manager.load_state() if manager.can_resume() else None
    if resume and resume.completed:
        return SourceResponse(
            name=endpoint_name,
            items=lambda: iter(()),
            primary_keys=list(endpoint.primary_keys),
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
        primary_keys=list(endpoint.primary_keys),
        on_complete=manager.clear_state,
    )
