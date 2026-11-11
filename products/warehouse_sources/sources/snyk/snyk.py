import re
import json
import hashlib
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Response

from products.warehouse_sources.sources.sdk import (
    BaseNextUrlPaginator,
    ClientConfig,
    Endpoint,
    EndpointResource,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    rest_api_resources,
    validate_via_probe,
)
from products.warehouse_sources.sources.snyk.settings import SNYK_ENDPOINTS, SnykEndpointConfig, SnykScope

# Snyk regional stacks are independent and don't share data; the region selects which API host
# the token is sent to. The set is a fixed allow-list, so the host can't be retargeted.
SNYK_REGION_HOSTS = {
    "us": "https://api.snyk.io",
    "eu": "https://api.eu.snyk.io",
    "au": "https://api.au.snyk.io",
}
DEFAULT_REGION = "us"

# Every Snyk REST call requires a dated ``version`` query param; omitting it is an error.
# This is a GA version that includes the issues endpoint's ``updated_after``/``created_after``
# filters. Snyk keeps GA versions available through a long deprecation window.
SNYK_REST_VERSION = "2024-10-15"

# Snyk org ids are UUIDs. The configured org id is interpolated into a URL path, so reject
# anything that could alter the path shape before it gets near a request.
_ORG_ID_RE = re.compile(r"^[a-zA-Z0-9-]+$")

# The parent resource name used when fanning out per-org endpoints over every org.
_PARENT_ORGS = "organizations"
_PARENT_ID_KEY = f"_{_PARENT_ORGS}_id"
_PARENT_GROUP_ID_KEY = f"_{_PARENT_ORGS}_group_id"


@dataclasses.dataclass(frozen=False)
class SnykResumeConfig:
    # Next page URL (from the JSON:API ``links.next``) to fetch on resume, for the single-collection
    # (organizations / single-org) endpoints. Optional so old saved states and the fan-out shape below
    # both parse under ``dataclass(**saved)``.
    next_url: str | None = None
    # The fan-out org a saved single-collection bookmark belonged to. Retained for backward
    # compatibility with states written before the framework migration; unused on load.
    org_id: str | None = None
    # The framework's fan-out resume state
    # (``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...}}``)
    # for the multi-org fan-out endpoints. ``None`` when only the old-shape fields are set — in that
    # case the fan-out starts fresh (the merge dedupes any re-pulled rows).
    fanout_state: dict[str, Any] | None = None


def base_url(region: Optional[str]) -> str:
    return SNYK_REGION_HOSTS.get(region or DEFAULT_REGION, SNYK_REGION_HOSTS[DEFAULT_REGION])


def _format_datetime(value: Any) -> Any:
    """Format an incremental cursor value as RFC 3339 with a ``Z`` suffix for Snyk filters.

    Returns ``None`` for a ``None`` value so the framework drops the filter param entirely on the
    first sync (no watermark yet) rather than sending an empty/``None`` filter.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_same_host(url: str, host: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == urlparse(host).netloc


def _next_page_url(host: str, payload: Any) -> str | None:
    """Resolve the JSON:API ``links.next`` value into an absolute URL on the resolved host.

    Snyk returns ``links.next`` either as a string or a ``{"href": ...}`` object, and as a
    relative path that may or may not carry the ``/rest`` prefix depending on API version. Only
    same-host absolute URLs are followed, so a tampered response can't point our authenticated
    request at another server (SSRF) and leak the token header.
    """
    links = payload.get("links") if isinstance(payload, dict) else None
    next_link = links.get("next") if isinstance(links, dict) else None
    if isinstance(next_link, dict):
        next_link = next_link.get("href")
    if not isinstance(next_link, str) or not next_link:
        return None
    if next_link.startswith("http"):
        return next_link if _is_same_host(next_link, host) else None
    if not next_link.startswith("/"):
        next_link = f"/{next_link}"
    if not next_link.startswith("/rest/"):
        next_link = f"/rest{next_link}"
    return f"{host}{next_link}"


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Lift a JSON:API record's ``attributes`` object to the root, keeping ``id``/``type``."""
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        item.pop("attributes")
        for key, value in attributes.items():
            item.setdefault(key, value)
    return item


def _validated_org_id(organization_id: str) -> str:
    org_id = organization_id.strip()
    if not _ORG_ID_RE.match(org_id):
        raise ValueError(f"Invalid Snyk organization id: {organization_id!r}")
    return org_id


class SnykJSONAPIPaginator(BaseNextUrlPaginator):
    """Follow the JSON:API ``links.next`` link, resolving relative / ``{"href": ...}`` forms to an
    absolute same-host URL. An off-host (or otherwise unusable) next link stops pagination — the
    authenticated request is never pointed at another origin. Resume support (seed / snapshot the
    next-page URL) is inherited from ``BaseNextUrlPaginator``.
    """

    def __init__(self, host: str) -> None:
        super().__init__()
        self._host = host

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        next_url = _next_page_url(self._host, payload) if payload is not None else None
        if next_url:
            self._next_url = next_url
            self._has_next_page = True
        else:
            self._has_next_page = False


def _flatten_map(item: dict[str, Any]) -> dict[str, Any]:
    return _flatten_item(item)


def _child_flatten_map(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a fan-out child row and rename the injected parent id to ``organization_id``."""
    item = _flatten_item(item)
    if _PARENT_ID_KEY in item:
        item["organization_id"] = item.pop(_PARENT_ID_KEY)
    return item


def _single_org_flatten_map(org_id: str) -> Any:
    def _map(item: dict[str, Any]) -> dict[str, Any]:
        item = _flatten_item(item)
        item["organization_id"] = org_id
        return item

    return _map


def _retention_start(retention_days: int) -> datetime:
    # Round up to a midnight, so the window stays inside retention and is the same all day.
    start = datetime.now(UTC) - timedelta(days=retention_days - 1)
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def _not_before(floor: datetime) -> Callable[[Any], Any]:
    """Format a window start, raised to ``floor`` so the request never asks for data past retention."""

    def _convert(value: Any) -> Any:
        if isinstance(value, datetime):
            value = max(value if value.tzinfo else value.replace(tzinfo=UTC), floor)
        return _format_datetime(value if value is not None else floor)

    return _convert


def _incremental_params(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    """Build the server-side incremental filter param marker for an endpoint, if applicable.

    ``links.next`` carries all query params forward, so applying the watermark filter to the first
    page keeps every subsequent page bounded too. The value is filled in per-run by the framework
    from ``db_incremental_field_last_value`` via ``_format_datetime`` (which returns ``None`` on the
    first sync so the filter is dropped). An endpoint with a retention window gets the start of that
    window instead, also on a full refresh.
    """
    config = SNYK_ENDPOINTS[endpoint]
    floor = _retention_start(config.retention_days) if config.retention_days else None
    if should_use_incremental_field and config.incremental_param_by_field:
        field = incremental_field or config.default_incremental_field
        filter_param = config.incremental_param_by_field.get(field) if field else None
        if filter_param:
            return {
                filter_param: {
                    "type": "incremental",
                    "cursor_path": field,
                    "convert": _not_before(floor) if floor else _format_datetime,
                }
            }
    if floor and config.window_start_param:
        return {config.window_start_param: _format_datetime(floor)}
    return {}


def _synthetic_id(item: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Hash the listed fields into a stable ``id``, so a re-fetched record merges onto its row."""
    values = [item.get(field) for field in fields]
    item["id"] = hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
    return item


def _with_synthetic_id(config: SnykEndpointConfig, data_map: Callable[[dict[str, Any]], dict[str, Any]]) -> Any:
    if not config.synthetic_id_fields:
        return data_map

    def _map(item: dict[str, Any]) -> dict[str, Any]:
        return _synthetic_id(data_map(item), config.synthetic_id_fields)

    return _map


def _base_params(config: SnykEndpointConfig) -> dict[str, Any]:
    return {"version": SNYK_REST_VERSION, config.page_size_param: config.page_size}


def _client_config(host: str, api_token: str) -> ClientConfig:
    return {
        "base_url": f"{host}/rest",
        # Only non-secret headers here; the token rides in framework `auth` so it's redacted from
        # logs and raised error messages.
        "headers": {"Accept": "application/vnd.api+json"},
        # Snyk's custom `Authorization: token <token>` scheme, expressed as an api-key header. The
        # framework redacts the api-key value (`token <token>`) everywhere it can surface.
        "auth": {"type": "api_key", "api_key": f"token {api_token}", "name": "Authorization", "location": "header"},
        # Pin every request — including paginator next-page links and seeded resume URLs — to the
        # resolved Snyk host so a tampered `links.next` or resume URL can't exfiltrate the token.
        "allowed_hosts": [],
    }


def snyk_source(
    region: Optional[str],
    api_token: str,
    organization_id: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SnykResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = SNYK_ENDPOINTS[endpoint]

    # Validate a configured single org id up front — it's interpolated into a URL path, so a
    # path-altering value must be rejected before any request is made.
    single_org: str | None = None
    if organization_id and organization_id.strip():
        single_org = _validated_org_id(organization_id)

    def build_resource() -> Resource:
        host = base_url(region)
        client = _client_config(host, api_token)
        params = _base_params(endpoint_config)
        params.update(_incremental_params(endpoint, should_use_incremental_field, incremental_field))

        resume: SnykResumeConfig | None = (
            resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        )

        if endpoint_config.scope == SnykScope.ORGANIZATION:
            if single_org is not None:
                # A single-org connection fetches that one org directly (a single JSON:API object)
                # instead of enumerating every org the token can reach.
                simple_endpoint: Endpoint = {
                    "path": f"/orgs/{single_org}",
                    "params": {"version": SNYK_REST_VERSION},
                    "data_selector": "data",
                    "paginator": SinglePagePaginator(),
                }
                return _build_simple(
                    client,
                    endpoint,
                    simple_endpoint,
                    _flatten_map,
                    resumable_source_manager,
                    None,
                    team_id,
                    job_id,
                    None,
                )
            # Top-level organizations collection.
            list_endpoint: Endpoint = {
                "path": endpoint_config.path,
                "params": params,
                "data_selector": "data",
                "paginator": SnykJSONAPIPaginator(host),
            }
            return _build_simple(
                client, endpoint, list_endpoint, _flatten_map, resumable_source_manager, resume, team_id, job_id, None
            )

        if endpoint_config.scope == SnykScope.PER_GROUP:
            return _build_group_fanout(
                client,
                endpoint_config,
                params,
                resumable_source_manager,
                resume,
                host,
                single_org,
                team_id,
                job_id,
                db_incremental_field_last_value,
            )

        if endpoint_config.scope == SnykScope.PER_ORG_CHILD:
            return _build_org_child_fanout(
                client,
                endpoint_config,
                params,
                resumable_source_manager,
                resume,
                host,
                single_org,
                team_id,
                job_id,
            )

        # PER_ORG endpoints.
        if single_org is not None:
            # Single-org: hit the org's collection directly, skipping the /orgs enumeration.
            child_endpoint: Endpoint = {
                "path": endpoint_config.path.format(org_id=single_org),
                "params": params,
                "data_selector": endpoint_config.data_selector,
                "paginator": SnykJSONAPIPaginator(host),
            }
            return _build_simple(
                client,
                endpoint,
                child_endpoint,
                _with_synthetic_id(endpoint_config, _single_org_flatten_map(single_org)),
                resumable_source_manager,
                resume,
                team_id,
                job_id,
                db_incremental_field_last_value,
            )

        # Fan out over every org the token can see.
        return _build_fanout(
            client,
            endpoint_config,
            params,
            resumable_source_manager,
            resume,
            host,
            team_id,
            job_id,
            db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=build_resource,
        primary_keys=endpoint_config.primary_keys,
        # Snyk documents no sort param on these endpoints and the response order is undefined —
        # and the multi-org fan-out breaks any global ordering anyway. "desc" defers the watermark
        # write to sync completion (max value seen), which is the safe semantic for unordered data;
        # "asc" would checkpoint a max-so-far watermark mid-sync and could skip rows on retry.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def _build_simple(
    client: ClientConfig,
    endpoint: str,
    endpoint_config: Endpoint,
    data_map: Any,
    manager: ResumableSourceManager[SnykResumeConfig],
    resume: SnykResumeConfig | None,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    resource: EndpointResource = {"name": endpoint, "endpoint": endpoint_config, "data_map": data_map}
    config: RESTAPIConfig = {"client": client, "resource_defaults": {}, "resources": [resource]}

    initial_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_url:
        # A tampered resume URL that points off-host is rejected by the client's host-pinning
        # (allowed_hosts) before the authenticated request leaves the process.
        initial_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            manager.save_state(SnykResumeConfig(next_url=state["next_url"]))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )


def _orgs_endpoint(host: str, single_org: str | None) -> Endpoint:
    if single_org is not None:
        return {
            "path": f"/orgs/{single_org}",
            "params": {"version": SNYK_REST_VERSION},
            "data_selector": "data",
            "paginator": SinglePagePaginator(),
        }
    return {
        "path": "/orgs",
        "params": {"version": SNYK_REST_VERSION, "limit": SNYK_ENDPOINTS[_PARENT_ORGS].page_size},
        "data_selector": "data",
        "paginator": SnykJSONAPIPaginator(host),
    }


def _fanout_resume(
    manager: ResumableSourceManager[SnykResumeConfig], resume: SnykResumeConfig | None
) -> tuple[Optional[dict[str, Any]], Callable[[Optional[dict[str, Any]]], None]]:
    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            manager.save_state(SnykResumeConfig(fanout_state=state))

    return (resume.fanout_state if resume is not None else None), save_checkpoint


def _build_fanout(
    client: ClientConfig,
    endpoint_config: SnykEndpointConfig,
    child_params: dict[str, Any],
    manager: ResumableSourceManager[SnykResumeConfig],
    resume: SnykResumeConfig | None,
    host: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    endpoint = endpoint_config.name
    parent_resource: EndpointResource = {"name": _PARENT_ORGS, "endpoint": _orgs_endpoint(host, None)}
    child_endpoint: Endpoint = {
        "path": endpoint_config.path,
        "params": {**child_params, "org_id": {"type": "resolve", "resource": _PARENT_ORGS, "field": "id"}},
        "data_selector": endpoint_config.data_selector,
        "paginator": SnykJSONAPIPaginator(host),
    }
    child_resource: EndpointResource = {
        "name": endpoint,
        "endpoint": child_endpoint,
        "include_from_parent": ["id"],
        "data_map": _with_synthetic_id(endpoint_config, _child_flatten_map),
    }
    config: RESTAPIConfig = {"client": client, "resource_defaults": {}, "resources": [parent_resource, child_resource]}

    # Only the framework's fan-out resume state round-trips here; an old single-collection bookmark
    # (next_url/org_id without fanout_state) starts fresh and the merge dedupes any re-pulled rows.
    initial_state, save_checkpoint = _fanout_resume(manager, resume)

    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return next(r for r in resources if r.name == endpoint)


def _first_org_of_each_group() -> Callable[[dict[str, Any]], bool]:
    """Keep one org row per group, so each group's endpoint is fetched once.

    Personal orgs have no group and are dropped. The group id goes into a URL path, so a value that
    could alter the path shape is dropped too.
    """
    seen: set[str] = set()

    def _keep(item: dict[str, Any]) -> bool:
        attributes = item.get("attributes")
        group_id = attributes.get("group_id") if isinstance(attributes, dict) else None
        if not isinstance(group_id, str) or not _ORG_ID_RE.match(group_id) or group_id in seen:
            return False
        seen.add(group_id)
        return True

    return _keep


def _group_child_map(item: dict[str, Any]) -> dict[str, Any]:
    item = _flatten_item(item)
    if _PARENT_GROUP_ID_KEY in item:
        item["group_id"] = item.pop(_PARENT_GROUP_ID_KEY)
    return item


def _org_child_map(parent_name: str, parent_id_column: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    parent_id_key = f"_{parent_name}_id"
    parent_org_key = f"_{parent_name}_organization_id"

    def _map(item: dict[str, Any]) -> dict[str, Any]:
        item = _flatten_item(item)
        if parent_id_key in item:
            item[parent_id_column] = item.pop(parent_id_key)
        if parent_org_key in item:
            item["organization_id"] = item.pop(parent_org_key)
        return item

    return _map


def _build_group_fanout(
    client: ClientConfig,
    endpoint_config: SnykEndpointConfig,
    child_params: dict[str, Any],
    manager: ResumableSourceManager[SnykResumeConfig],
    resume: SnykResumeConfig | None,
    host: str,
    single_org: str | None,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    endpoint = endpoint_config.name
    # The parent row is flattened before the child reads it, so `group_id` is a root field.
    parent_resource: EndpointResource = {
        "name": _PARENT_ORGS,
        "endpoint": _orgs_endpoint(host, single_org),
        "data_map": _flatten_map,
    }
    child_resource: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": endpoint_config.path,
            "params": {
                **child_params,
                "group_id": {"type": "resolve", "resource": _PARENT_ORGS, "field": "group_id"},
            },
            "data_selector": endpoint_config.data_selector,
            "paginator": SnykJSONAPIPaginator(host),
        },
        "include_from_parent": ["group_id"],
        "data_map": _with_synthetic_id(endpoint_config, _group_child_map),
    }
    config: RESTAPIConfig = {"client": client, "resource_defaults": {}, "resources": [parent_resource, child_resource]}
    initial_state, save_checkpoint = _fanout_resume(manager, resume)

    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    next(r for r in resources if r.name == _PARENT_ORGS).add_filter(_first_org_of_each_group())
    return next(r for r in resources if r.name == endpoint)


def _build_org_child_fanout(
    client: ClientConfig,
    endpoint_config: SnykEndpointConfig,
    child_params: dict[str, Any],
    manager: ResumableSourceManager[SnykResumeConfig],
    resume: SnykResumeConfig | None,
    host: str,
    single_org: str | None,
    team_id: int,
    job_id: str,
) -> Resource:
    endpoint = endpoint_config.name
    parent_name = endpoint_config.parent_endpoint
    parent_id_column = endpoint_config.parent_id_column
    if parent_name is None or parent_id_column is None:
        raise ValueError(f"Snyk endpoint {endpoint} has no parent endpoint")
    parent_config = SNYK_ENDPOINTS[parent_name]

    parent_resource: EndpointResource
    resource_list: list[str | EndpointResource] = []
    if single_org is not None:
        parent_resource = {
            "name": parent_name,
            "endpoint": {
                "path": parent_config.path.format(org_id=single_org),
                "params": _base_params(parent_config),
                "data_selector": parent_config.data_selector,
                "paginator": SnykJSONAPIPaginator(host),
            },
            "data_map": _single_org_flatten_map(single_org),
        }
    else:
        # Two fan-out levels (orgs -> parent -> child). The framework does not resume a chained
        # fan-out, so an interrupted run starts again and the merge dedupes.
        resource_list.append({"name": _PARENT_ORGS, "endpoint": _orgs_endpoint(host, None)})
        parent_resource = {
            "name": parent_name,
            "endpoint": {
                "path": parent_config.path,
                "params": {
                    **_base_params(parent_config),
                    "org_id": {"type": "resolve", "resource": _PARENT_ORGS, "field": "id"},
                },
                "data_selector": parent_config.data_selector,
                "paginator": SnykJSONAPIPaginator(host),
            },
            "include_from_parent": ["id"],
            "data_map": _child_flatten_map,
        }
    resource_list.append(parent_resource)
    resource_list.append(
        {
            "name": endpoint,
            "endpoint": {
                "path": endpoint_config.path,
                "params": {
                    **child_params,
                    "org_id": {"type": "resolve", "resource": parent_name, "field": "organization_id"},
                    parent_id_column: {"type": "resolve", "resource": parent_name, "field": "id"},
                },
                "data_selector": endpoint_config.data_selector,
                "paginator": SnykJSONAPIPaginator(host),
            },
            "include_from_parent": ["id", "organization_id"],
            "data_map": _org_child_map(parent_name, parent_id_column),
        }
    )
    config: RESTAPIConfig = {"client": client, "resource_defaults": {}, "resources": resource_list}
    initial_state, save_checkpoint = _fanout_resume(manager, resume)

    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return next(r for r in resources if r.name == endpoint)


def validate_credentials(
    region: Optional[str], api_token: str, organization_id: Optional[str] = None
) -> tuple[bool, str | None]:
    """Confirm the token is genuine with a single cheap probe.

    ``/rest/self`` validates the token alone; when a single org is configured, probing that org
    also confirms the token can reach it on the selected region.
    """
    host = base_url(region)
    if organization_id and organization_id.strip():
        try:
            org_id = _validated_org_id(organization_id)
        except ValueError:
            return False, "Snyk organization ID is invalid — copy it from your organization settings."
        url = f"{host}/rest/orgs/{org_id}?version={SNYK_REST_VERSION}"
    else:
        url = f"{host}/rest/self?version={SNYK_REST_VERSION}"

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers={"Authorization": f"token {api_token}", "Accept": "application/vnd.api+json"},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Snyk API token. Check the token and the selected region, then try again."
    if status in (403, 404):
        return False, "Your Snyk token can't access this organization. Check the organization ID and region."
    if status is None:
        return False, "Could not reach the Snyk API. Check the selected region and your network, then try again."
    return False, f"Snyk API error: {status}"
