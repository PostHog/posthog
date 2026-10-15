import re
import copy
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import SplitResult, urlsplit

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana_irm.settings import (
    GRAFANA_IRM_ENDPOINTS,
    INCIDENT_PAGE_SIZE,
    ONCALL_PAGE_SIZE,
    GrafanaIRMEndpointConfig,
)

# Grafana IRM is a Grafana Cloud product: both the stack and the OnCall API live under this domain.
# Pinning to it keeps the token from being sent to any host outside Grafana Cloud.
GRAFANA_CLOUD_DOMAIN = "grafana.net"
# Plain DNS labels only: urlsplit keeps characters like `\` or `%` in the hostname, and requests then
# resolves a different host than the one checked here.
_GRAFANA_CLOUD_HOSTNAME = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+" + re.escape(GRAFANA_CLOUD_DOMAIN))
INCIDENT_API_PATH = "/api/plugins/grafana-irm-app/resources/api/v1"
REQUEST_TIMEOUT_SECONDS = 60


class GrafanaIRMConfigError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class GrafanaIRMResumeConfig:
    page: Optional[int] = None
    cursor: Optional[str] = None


def _parse_grafana_cloud_url(url: str, label: str) -> SplitResult:
    """Return the URL as bare ``https://<host><path>``, or raise ``GrafanaIRMConfigError``."""
    value = url.strip()
    if "://" not in value:
        value = f"https://{value}"
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise GrafanaIRMConfigError(f"The {label} is not a valid URL.")
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or parsed.username or parsed.password or port not in (None, 443):
        raise GrafanaIRMConfigError(f"The {label} must be a plain https:// URL.")
    if not _GRAFANA_CLOUD_HOSTNAME.fullmatch(hostname):
        raise GrafanaIRMConfigError(f"The {label} must be a Grafana Cloud URL ending in .{GRAFANA_CLOUD_DOMAIN}.")
    return SplitResult(scheme="https", netloc=hostname, path=parsed.path.rstrip("/"), query="", fragment="")


def normalize_stack_url(url: str) -> str:
    """``yourstack.grafana.net/a/grafana-irm-app`` -> ``https://yourstack.grafana.net``."""
    return _parse_grafana_cloud_url(url, "Grafana stack URL")._replace(path="").geturl()


def normalize_oncall_api_url(url: str) -> str:
    """Keep the path (``https://oncall-prod-us-central-0.grafana.net/oncall``) but drop a pasted ``/api/v1`` suffix."""
    parsed = _parse_grafana_cloud_url(url, "OnCall API URL")
    return parsed._replace(path=parsed.path.removesuffix("/api/v1")).geturl()


class IncidentCursorPaginator(BasePaginator):
    """Cursor pagination for the Incident RPC API.

    The cursor travels inside the POST body as ``{"nextValue": ..., "hasMore": ...}`` and the
    response echoes the next one, which the built-in cursor paginator can't express.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_value: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if self._next_value is not None:
            # Copy so the endpoint's shared body template never carries a cursor into another request.
            request.json = {**(request.json or {}), "cursor": {"nextValue": self._next_value, "hasMore": True}}

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            cursor = response.json().get("cursor") or {}
        except Exception:
            cursor = {}
        next_value = cursor.get("nextValue")
        if cursor.get("hasMore") and next_value:
            self._next_value = next_value
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._next_value} if self._has_next_page and self._next_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor:
            self._next_value = str(cursor)
            self._has_next_page = True


def _oncall_paginator() -> PageNumberPaginator:
    # A page past the end returns the last page again instead of an empty one, so `total_pages` is
    # the only reliable stop signal.
    return PageNumberPaginator(base_page=1, page_param="page", total_path="total_pages")


def _base_url(config: GrafanaIRMEndpointConfig, stack_url: str, oncall_api_url: str) -> str:
    return oncall_api_url if config.api == "oncall" else f"{stack_url}{INCIDENT_API_PATH}"


def _headers(config: GrafanaIRMEndpointConfig, stack_url: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if config.api == "oncall":
        # With a service account token, OnCall resolves the stack from this header.
        headers["X-Grafana-URL"] = stack_url
    return headers


def _drop_fields(fields: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def drop(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in fields}

    return drop


def _resource_config(
    config: GrafanaIRMEndpointConfig, token: str, stack_url: str, oncall_api_url: str
) -> RESTAPIConfig:
    endpoint: Endpoint = {
        "path": config.path,
        "data_selector": config.data_selector,
        "data_selector_required": True,
    }
    if config.api == "oncall":
        endpoint["method"] = "get"
        endpoint["params"] = {**config.params, "perpage": ONCALL_PAGE_SIZE}
    else:
        endpoint["method"] = "post"
        endpoint["json"] = copy.deepcopy(config.json)

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }
    if config.dropped_fields:
        resource["data_map"] = _drop_fields(config.dropped_fields)

    return {
        "client": {
            "base_url": _base_url(config, stack_url, oncall_api_url),
            "headers": _headers(config, stack_url),
            "auth": {"type": "bearer", "token": token},
            "paginator": _oncall_paginator() if config.api == "oncall" else IncidentCursorPaginator(),
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
        },
        "resources": [resource],
    }


def _incident_client(token: str, stack_url: str) -> RESTClient:
    return RESTClient(
        base_url=f"{stack_url}{INCIDENT_API_PATH}",
        headers={"Accept": "application/json"},
        auth=BearerTokenAuth(token),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _incident_activity_pages(client: RESTClient) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every incident and yield its activity timeline page by page.

    The activity query takes the incident ID in the POST body, which the declarative fan-out can
    only bind into the URL path, so this walks both levels with the same client.
    """
    incidents = GRAFANA_IRM_ENDPOINTS["incidents"]
    activity = GRAFANA_IRM_ENDPOINTS["incident_activity"]
    incident_query = {"query": {"limit": INCIDENT_PAGE_SIZE, "orderField": "createdTime", "orderDirection": "ASC"}}

    for incident_page in client.paginate(
        incidents.path,
        method="post",
        json=incident_query,
        paginator=IncidentCursorPaginator(),
        data_selector=incidents.data_selector,
        data_selector_required=True,
    ):
        for incident in incident_page:
            incident_id = incident.get("incidentID")
            if not incident_id:
                continue
            body = copy.deepcopy(activity.json)
            body["query"]["incidentID"] = incident_id
            for activity_page in client.paginate(
                activity.path,
                method="post",
                json=body,
                paginator=IncidentCursorPaginator(),
                data_selector=activity.data_selector,
                data_selector_required=True,
                data_selector_empty_ok=True,
            ):
                if activity_page:
                    yield activity_page


def grafana_irm_source(
    token: str,
    stack_url: str,
    oncall_api_url: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GrafanaIRMResumeConfig],
) -> SourceResponse:
    config = GRAFANA_IRM_ENDPOINTS[endpoint]
    stack_url = normalize_stack_url(stack_url)
    oncall_api_url = normalize_oncall_api_url(oncall_api_url)

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "week",
            "partition_keys": [config.partition_key],
        }

    if endpoint == "incident_activity":
        client = _incident_client(token, stack_url)
        return SourceResponse(
            name=endpoint,
            items=lambda: _incident_activity_pages(client),
            primary_keys=list(config.primary_keys),
            **partition_kwargs,
        )

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            state = {"page": resume.page, "cursor": resume.cursor}
            initial_paginator_state = {key: value for key, value in state.items() if value is not None} or None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if not state:
            return
        if state.get("page") is not None:
            resumable_source_manager.save_state(GrafanaIRMResumeConfig(page=int(state["page"])))
        elif state.get("cursor"):
            resumable_source_manager.save_state(GrafanaIRMResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        _resource_config(config, token, stack_url, oncall_api_url),
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(config.primary_keys),
        **partition_kwargs,
    )


def _probe(session: requests.Session, method: str, url: str, **kwargs: Any) -> Optional[int]:
    # Only the status matters, so stream and never read the body.
    try:
        with session.request(method, url, timeout=10, allow_redirects=False, stream=True, **kwargs) as response:
            return response.status_code
    except requests.exceptions.RequestException:
        return None


def validate_credentials(
    token: str, stack_url: str, oncall_api_url: str, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    """Probe both IRM APIs with one cheap request each.

    A 403 means the token is genuine but lacks a permission. Accept it at source creation, since the
    user may only sync some tables, and fail only when a specific table is being checked.
    """
    try:
        stack_url = normalize_stack_url(stack_url)
        oncall_api_url = normalize_oncall_api_url(oncall_api_url)
    except GrafanaIRMConfigError as e:
        return False, str(e)

    config = GRAFANA_IRM_ENDPOINTS.get(schema_name) if schema_name else None
    probe_oncall = config is None or config.api == "oncall"
    probe_incident = config is None or config.api == "incident"
    session = make_tracked_session(redact_values=(token,))
    auth_header = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    if probe_oncall:
        oncall_path = config.path if config is not None else GRAFANA_IRM_ENDPOINTS["alert_groups"].path
        status = _probe(
            session,
            "GET",
            f"{oncall_api_url}{oncall_path}",
            params={"perpage": 1},
            headers={**auth_header, "X-Grafana-URL": stack_url},
        )
        if status is None:
            return False, "Couldn't reach the OnCall API. Check the OnCall API URL."
        if status == 401:
            return False, "Grafana rejected the token. Check the service account token and the Grafana stack URL."
        if status == 403 and config is not None:
            return False, "Your service account token doesn't have permission to read this table."
        if status == 404:
            return (
                False,
                "The OnCall API URL doesn't point to an OnCall API. Copy it from IRM > Settings > Admin & API.",
            )
        if status not in (200, 403):
            return False, f"The OnCall API returned an unexpected response (HTTP {status})."

    if probe_incident:
        status = _probe(
            session,
            "POST",
            f"{stack_url}{INCIDENT_API_PATH}{GRAFANA_IRM_ENDPOINTS['incidents'].path}",
            json={"query": {"limit": 1}},
            headers=auth_header,
        )
        if status is None:
            return False, "Couldn't reach your Grafana stack. Check the Grafana stack URL."
        if status == 401:
            return False, "Grafana rejected the token. Check the service account token and the Grafana stack URL."
        if status == 403 and config is not None:
            return False, "Your service account token doesn't have permission to read incidents."
        if status == 404:
            return False, "Grafana IRM isn't enabled on this Grafana stack."
        if status not in (200, 403):
            return False, f"The Grafana Incident API returned an unexpected response (HTTP {status})."

    return True, None
