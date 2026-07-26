import re
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Request, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2Auth,
    OAuth2AuthRequestError,
    strip_oauth2_permanent_marker,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    make_parent_key_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id.settings import (
    ENTRA_ENDPOINTS,
    EntraEndpointConfig,
)

GRAPH_HOST = "graph.microsoft.com"
LOGIN_HOST = "login.microsoftonline.com"
GRAPH_DEFAULT_VERSION = "v1.0"
# Application-permission (app-only) flow: the tenant's admin consents once and `.default` asks for
# every permission already granted to the app registration.
GRAPH_DEFAULT_SCOPE = "https://graph.microsoft.com/.default"
# (connect, read). Graph answers directory reads quickly; the read budget is generous enough for a
# throttled 999-row page without letting a stalled request pin an import worker forever.
REQUEST_TIMEOUT = (10.0, 120.0)

# The tenant id lands in the token endpoint's URL path, so it must not be able to escape that path
# segment (a `/` or `..` would retarget the client secret at another endpoint or host). Entra
# accepts a GUID, a verified domain, or `organizations`/`common` — all of which fit this shape.
_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# Same reasoning for the version segment of the Graph base URL.
_API_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,15}$")


@dataclasses.dataclass
class MicrosoftEntraIdResumeConfig:
    """Resume state for both endpoint shapes this source syncs.

    Top-level endpoints resume from the OData ``@odata.nextLink`` they stopped on. The
    ``GroupMembers`` fan-out instead records which group paths finished, the group in progress, and
    that group's own paginator cursor — the shape the shared dependent-resource resume hook emits.
    """

    next_url: Optional[str] = None
    completed: Optional[list[str]] = None
    current: Optional[str] = None
    child_state: Optional[dict[str, Any]] = None


class ODataNextLinkPaginator(BaseNextUrlPaginator):
    """Follows OData v4 ``@odata.nextLink`` until Graph stops returning one.

    The link is absolute and already carries every query parameter of the original request
    (including `$filter` and `$select`), which is why the base class drops the request params when
    it follows one. Host-pinning in the REST client rejects a link that points off Graph.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        next_link = body.get("@odata.nextLink") if isinstance(body, dict) else None
        if isinstance(next_link, str) and next_link:
            self._next_url = next_link
            self._has_next_page = True
        else:
            self._has_next_page = False

    def __str__(self) -> str:
        return "ODataNextLinkPaginator(@odata.nextLink)"


def token_url(tenant_id: str) -> str:
    if not _TENANT_ID_RE.match(tenant_id):
        raise ValueError(
            "Directory (tenant) ID must be a tenant GUID or a verified domain name — "
            "it cannot contain slashes or other URL characters."
        )
    return f"https://{LOGIN_HOST}/{tenant_id}/oauth2/v2.0/token"


def graph_base_url(api_version: str) -> str:
    if not _API_VERSION_RE.match(api_version):
        raise ValueError(f"Unsupported Microsoft Graph API version: {api_version!r}")
    return f"https://{GRAPH_HOST}/{api_version}"


def build_graph_auth(tenant_id: str, client_id: str, client_secret: str) -> OAuth2Auth:
    """Client-credentials auth against the tenant's token endpoint.

    The framework auth mints the ~1h access token lazily, caches it for the run, re-mints on
    expiry, and registers the secret values for log/error redaction — so nothing here needs to
    manage tokens itself.
    """
    return OAuth2Auth(
        token_url=token_url(tenant_id),
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        scopes=GRAPH_DEFAULT_SCOPE,
    )


def prime_access_token(auth: OAuth2Auth) -> None:
    """Force the lazy token exchange so a credential problem surfaces here, not mid-probe."""
    prepared = Request(method="GET", url=f"https://{GRAPH_HOST}/").prepare()
    auth(prepared)


def odata_datetime(value: Any) -> Optional[str]:
    """Render a watermark as the UTC ISO 8601 literal an OData datetime comparison expects."""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day, tzinfo=UTC)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def odata_ge_filter(field: str) -> Callable[[Any], Optional[str]]:
    """Build the ``$filter`` value for a watermark, e.g. ``activityDateTime ge 2024-01-01T00:00:00Z``.

    Returning None on the first sync (no watermark) drops the parameter from the query string
    entirely, so the run is unfiltered rather than sent a malformed filter expression.
    """

    def convert(value: Any) -> Optional[str]:
        stamp = odata_datetime(value)
        return f"{field} ge {stamp}" if stamp else None

    return convert


def _resolve_incremental_field(config: EntraEndpointConfig, requested: Optional[str]) -> Optional[str]:
    """Honour the user's chosen cursor field, falling back to the endpoint's advertised one."""
    advertised = {field["field"] for field in config.incremental_fields}
    if requested in advertised:
        return requested
    return config.incremental_filter_field


def _client_config(tenant_id: str, client_id: str, client_secret: str, api_version: str) -> ClientConfig:
    return {
        "base_url": graph_base_url(api_version),
        "headers": {"Accept": "application/json"},
        "auth": build_graph_auth(tenant_id, client_id, client_secret),
        # Pagination follows absolute links out of the response body, so pin them to Graph and
        # refuse redirects — a tampered `@odata.nextLink` must not carry the bearer token off-host.
        "allowed_hosts": [GRAPH_HOST],
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT,
    }


def _list_params(config: EntraEndpointConfig, select: Optional[str] = None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    projection = select if select is not None else config.select
    if projection:
        params["$select"] = projection
    if config.page_size is not None:
        params["$top"] = config.page_size
    return params


def _list_endpoint(config: EntraEndpointConfig, select: Optional[str] = None) -> Endpoint:
    return {
        "path": config.path,
        "params": _list_params(config, select),
        "data_selector": "value",
        # Every Graph collection response wraps its rows in `value`; a body without it means the
        # response shape changed, which should fail loud rather than sync zero rows.
        "data_selector_required": True,
        "paginator": ODataNextLinkPaginator(),
    }


def membership_row_mapper(parent_name: str, parent_id_column: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Normalize a `/groups/{id}/members` row into a membership row.

    ``@odata.type`` is Graph's discriminator for the heterogeneous directoryObject collection; the
    leading `@` makes it a poor warehouse column, so it moves to ``member_type``. The parent id
    arrives under the shared fan-out injection's prefixed key and moves to the endpoint's declared
    ``parent_id_column``, the first half of the composite primary key.
    """
    injected_key = make_parent_key_name(parent_name, "id")

    def mapper(row: dict[str, Any]) -> dict[str, Any]:
        row[parent_id_column] = row.pop(injected_key, None)
        row["member_type"] = row.pop("@odata.type", None)
        return row

    return mapper


def _initial_paginator_state(
    manager: ResumableSourceManager[MicrosoftEntraIdResumeConfig], is_fanout: bool
) -> Optional[dict[str, Any]]:
    if not manager.can_resume():
        return None
    resume = manager.load_state()
    if resume is None:
        return None
    if is_fanout:
        if not resume.completed and resume.current is None:
            return None
        return {
            "completed": list(resume.completed or []),
            "current": resume.current,
            "child_state": resume.child_state,
        }
    return {"next_url": resume.next_url} if resume.next_url else None


def _save_checkpoint(
    manager: ResumableSourceManager[MicrosoftEntraIdResumeConfig], is_fanout: bool
) -> Callable[[Optional[dict[str, Any]]], None]:
    def save(state: Optional[dict[str, Any]]) -> None:
        # Called after a page is yielded, so a crash re-yields the last page (merge dedupes)
        # rather than skipping it. Nothing to persist once the walk is finished.
        if not state:
            return
        if is_fanout:
            manager.save_state(
                MicrosoftEntraIdResumeConfig(
                    completed=list(state.get("completed") or []),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )
            return
        next_url = state.get("next_url")
        if next_url:
            manager.save_state(MicrosoftEntraIdResumeConfig(next_url=str(next_url)))

    return save


def _fanout_config(
    config: EntraEndpointConfig,
    parent: EntraEndpointConfig,
    client_config: ClientConfig,
) -> RESTAPIConfig:
    parent_resource: EndpointResource = {
        "name": parent.name,
        "table_name": parent.name,
        "write_disposition": "replace",
        # Only the group ids are needed to fan out, so keep the parent projection minimal.
        "endpoint": _list_endpoint(parent, select="id"),
        "table_format": "delta",
    }
    child_endpoint: Endpoint = {
        "path": config.path,
        "params": {
            "parent_id": {"type": "resolve", "resource": parent.name, "field": "id"},
            **_list_params(config),
        },
        "data_selector": "value",
        "data_selector_required": True,
        "paginator": ODataNextLinkPaginator(),
    }
    if config.parent_id_column is None:
        raise ValueError(f"Fan-out endpoint {config.name} must declare a parent_id_column")
    child_resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "include_from_parent": ["id"],
        "data_map": membership_row_mapper(parent.name, config.parent_id_column),
        "endpoint": child_endpoint,
        "table_format": "delta",
    }
    return {
        "client": client_config,
        "resource_defaults": {},
        "resources": [parent_resource, child_resource],
    }


def microsoft_entra_id_source(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MicrosoftEntraIdResumeConfig],
    api_version: str = GRAPH_DEFAULT_VERSION,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = ENTRA_ENDPOINTS[endpoint]
    client_config = _client_config(tenant_id, client_id, client_secret, api_version)
    is_fanout = config.parent is not None

    cursor_field = _resolve_incremental_field(config, incremental_field) if should_use_incremental_field else None
    # Server-side filtering only: never inject a watermark on an endpoint with no `$filter` support,
    # or on a full-refresh sync.
    last_value = db_incremental_field_last_value if cursor_field else None

    initial_state = _initial_paginator_state(resumable_source_manager, is_fanout)
    resume_hook = _save_checkpoint(resumable_source_manager, is_fanout)

    if config.parent is not None:
        resources = rest_api_resources(
            _fanout_config(config, ENTRA_ENDPOINTS[config.parent], client_config),
            team_id,
            job_id,
            last_value,
            resume_hook=resume_hook,
            initial_paginator_state=initial_state,
        )
        resource = next(item for item in resources if item.name == config.name)
    else:
        endpoint_config = _list_endpoint(config)
        if cursor_field:
            endpoint_config["incremental"] = {
                "start_param": "$filter",
                "cursor_path": cursor_field,
                "convert": odata_ge_filter(cursor_field),
            }
        resource_config: EndpointResource = {
            "name": config.name,
            "table_name": config.name,
            "write_disposition": ({"disposition": "merge", "strategy": "upsert"} if cursor_field else "replace"),
            "endpoint": endpoint_config,
            "table_format": "delta",
        }
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [resource_config],
        }
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            last_value,
            resume_hook=resume_hook,
            initial_paginator_state=initial_state,
        )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def _probe_url(api_version: str, config: Optional[EntraEndpointConfig]) -> str:
    base = graph_base_url(api_version)
    if config is None:
        # No schema in context: the cheapest read that proves the token reaches Graph at all.
        return f"{base}/users?{urlencode({'$top': 1, '$select': 'id'})}"
    # `$top` only where the endpoint documents paging support — the small collections
    # (`/organization`, `/directoryRoles`, `/subscribedSkus`) reject unsupported query parameters.
    query = f"?{urlencode({'$top': 1})}" if config.page_size is not None else ""
    return f"{base}{config.permission_probe_path}{query}"


def validate_credentials(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    schema_name: Optional[str] = None,
    api_version: str = GRAPH_DEFAULT_VERSION,
) -> tuple[bool, Optional[str]]:
    try:
        graph_base_url(api_version)
        auth = build_graph_auth(tenant_id, client_id, client_secret)
    except ValueError as e:
        return False, str(e)

    try:
        prime_access_token(auth)
    except OAuth2AuthRequestError as e:
        return False, (
            "Microsoft Entra ID rejected the app credentials: "
            f"{strip_oauth2_permanent_marker(str(e))}. Check the directory (tenant) ID, "
            "application (client) ID and client secret."
        )
    except Exception:
        return False, "Could not reach the Microsoft identity platform to get an access token. Please try again."

    config = ENTRA_ENDPOINTS.get(schema_name) if schema_name else None
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=auth.secret_values()),
        _probe_url(api_version, config),
        auth=auth,
        allow_redirects=False,
    )
    if ok:
        return True, None

    if status == 403:
        # A valid token that just lacks a scope. At source-create the user may only intend to sync
        # tables they did grant, so don't block creation; a per-schema check does reject it.
        if config is None:
            return True, None
        return False, (
            f"The app registration is missing the `{config.required_permission}` application "
            "permission (with admin consent) needed to read this table."
        )
    if status == 401:
        return False, "Microsoft Graph rejected the access token. Reconnect with a valid client secret."
    if status is None:
        return False, "Could not reach Microsoft Graph. Please try again."
    return False, f"Microsoft Graph returned HTTP {status} while validating access."


def check_endpoint_permissions(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    endpoints: list[str],
    api_version: str = GRAPH_DEFAULT_VERSION,
) -> dict[str, Optional[str]]:
    """Per-table access check for the schema picker.

    Graph application permissions are granular (User.Read.All, Group.Read.All, AuditLog.Read.All,
    ...), so a tenant commonly consents to a subset. Only a real denial (403) counts as a missing
    permission — a throttle, 5xx, or network blip must not be reported as one.
    """
    results: dict[str, Optional[str]] = dict.fromkeys(endpoints)
    try:
        graph_base_url(api_version)
        auth = build_graph_auth(tenant_id, client_id, client_secret)
        prime_access_token(auth)
    except Exception:
        return results

    def session_factory() -> Session:
        return make_tracked_session(redact_values=auth.secret_values())

    for name in endpoints:
        config = ENTRA_ENDPOINTS.get(name)
        if config is None:
            continue
        ok, status = validate_via_probe(
            session_factory,
            _probe_url(api_version, config),
            auth=auth,
            allow_redirects=False,
        )
        if not ok and status == 403:
            results[name] = (
                f"Grant the `{config.required_permission}` application permission (with admin "
                "consent) to sync this table."
            )
    return results
