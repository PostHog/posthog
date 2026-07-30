import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.settings import SNYK_ENDPOINTS, SnykScope

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


@dataclasses.dataclass
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


def _incremental_params(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    """Build the server-side incremental filter param marker for an endpoint, if applicable.

    ``links.next`` carries all query params forward, so applying the watermark filter to the first
    page keeps every subsequent page bounded too. The value is filled in per-run by the framework
    from ``db_incremental_field_last_value`` via ``_format_datetime`` (which returns ``None`` on the
    first sync so the filter is dropped).
    """
    config = SNYK_ENDPOINTS[endpoint]
    if not (should_use_incremental_field and config.incremental_param_by_field):
        return {}
    field = incremental_field or config.default_incremental_field
    filter_param = config.incremental_param_by_field.get(field) if field else None
    if not filter_param:
        return {}
    return {filter_param: {"type": "incremental", "cursor_path": field, "convert": _format_datetime}}


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
        params: dict[str, Any] = {"version": SNYK_REST_VERSION, "limit": endpoint_config.page_size}

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

        # PER_ORG endpoints.
        params.update(_incremental_params(endpoint, should_use_incremental_field, incremental_field))

        if single_org is not None:
            # Single-org: hit the org's collection directly, skipping the /orgs enumeration.
            child_endpoint: Endpoint = {
                "path": endpoint_config.path.format(org_id=single_org),
                "params": params,
                "data_selector": "data",
                "paginator": SnykJSONAPIPaginator(host),
            }
            return _build_simple(
                client,
                endpoint,
                child_endpoint,
                _single_org_flatten_map(single_org),
                resumable_source_manager,
                resume,
                team_id,
                job_id,
                db_incremental_field_last_value,
            )

        # Fan out over every org the token can see.
        return _build_fanout(
            client,
            endpoint,
            endpoint_config.path,
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


def _build_fanout(
    client: ClientConfig,
    endpoint: str,
    child_path: str,
    child_params: dict[str, Any],
    manager: ResumableSourceManager[SnykResumeConfig],
    resume: SnykResumeConfig | None,
    host: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    parent_resource: EndpointResource = {
        "name": _PARENT_ORGS,
        "endpoint": {
            "path": "/orgs",
            "params": {"version": SNYK_REST_VERSION, "limit": SNYK_ENDPOINTS[_PARENT_ORGS].page_size},
            "data_selector": "data",
            "paginator": SnykJSONAPIPaginator(host),
        },
    }
    child_endpoint: Endpoint = {
        "path": child_path,
        "params": {**child_params, "org_id": {"type": "resolve", "resource": _PARENT_ORGS, "field": "id"}},
        "data_selector": "data",
        "paginator": SnykJSONAPIPaginator(host),
    }
    child_resource: EndpointResource = {
        "name": endpoint,
        "endpoint": child_endpoint,
        "include_from_parent": ["id"],
        "data_map": _child_flatten_map,
    }
    config: RESTAPIConfig = {"client": client, "resource_defaults": {}, "resources": [parent_resource, child_resource]}

    # Only the framework's fan-out resume state round-trips here; an old single-collection bookmark
    # (next_url/org_id without fanout_state) starts fresh and the merge dedupes any re-pulled rows.
    initial_state = resume.fanout_state if resume is not None else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            manager.save_state(SnykResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
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
