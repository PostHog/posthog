import dataclasses
from collections.abc import Callable, Iterable
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_chained_resource,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    _looks_like_json,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.settings import (
    FRESHCHAT_ENDPOINTS,
    PER_PAGE,
    PRIMARY_KEYS,
    SKIP_MISSING_PARENT,
    FreshchatEndpointConfig,
)

VALIDATE_TIMEOUT = 10

# All documented Freshchat API hosts live under these Freshworks-owned domains: account
# subdomains and regional hosts (api.freshchat.com, api.eu.freshchat.com, ...) under
# freshchat.com, Freshsales Suite accounts under myfreshworks.com.
ALLOWED_HOST_SUFFIXES = ("freshchat.com", "myfreshworks.com")

HOST_NOT_ALLOWED_ERROR = "Freshchat domain is not allowed"


class FreshchatHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class FreshchatResumeConfig:
    # The next page number to fetch. Freshchat uses page/items_per_page pagination, so a single
    # integer is enough to pick back up. Endpoints are full refresh (no time window), so re-entering
    # a page and deduping on the primary key is safe. Does not cover the chained fan-out, which
    # `build_chained_resource` cannot checkpoint.
    page: int


def normalize_domain(domain: str) -> str:
    """Normalize the Freshchat host the user supplied.

    Accepts a bare account name ("acme" -> "acme.freshchat.com"), a full host
    ("acme.freshchat.com", "acme.myfreshworks.com", "api.eu.freshchat.com"), or a URL with a
    scheme/path. Freshchat's base host varies by account and data center, so we keep whatever
    host the user gives and only default the domain when they pass a bare account name.
    """
    d = domain.strip().lower().removeprefix("https://").removeprefix("http://")
    d = d.split("/")[0].strip().rstrip("/")
    if "." not in d:
        d = f"{d}.freshchat.com"
    return d


def is_allowed_host(host: str) -> bool:
    """Only Freshworks-owned hosts are reachable: account subdomains and regional API hosts live
    under freshchat.com, Freshsales Suite accounts under myfreshworks.com. The domain is fully
    customer-controlled, so anything else (e.g. an internal hostname) is refused — the stored
    token plus scheduled syncs would otherwise let a user aim authenticated GETs at arbitrary
    hosts (SSRF)."""
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES)


def _base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}/v2"


def build_base_params(config: FreshchatEndpointConfig) -> dict[str, Any]:
    """Query params shared across every page of one sync (everything except `page`)."""
    params: dict[str, Any] = {}
    if config.paginated:
        params["items_per_page"] = str(PER_PAGE)
        if config.accepts_sort_order:
            # Explicit stable sort so page boundaries don't skip/duplicate rows if the API's
            # implicit default order shifts while we page.
            params["sort_order"] = "asc"
    params.update(config.extra_params)
    return params


def _paginator_for(config: FreshchatEndpointConfig) -> BasePaginator:
    if not config.paginated:
        # Single-object and whole-collection endpoints are one request, no pagination params.
        return SinglePagePaginator()
    # Freshchat pages by 1-based page number. Where the response reports the page count the
    # paginator stops right after the last page (no extra empty request); otherwise it stops on
    # the first empty page. Either way it is resumable by page number.
    return PageNumberPaginator(base_page=1, page=1, page_param="page", total_path=config.total_pages_path)


def _client_config(api_key: str, domain: str) -> ClientConfig:
    return {
        "base_url": _base_url(domain),
        # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
        # logs and error messages; only the non-secret Accept header is set here so the API
        # returns JSON rather than an HTML error page.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        # Pin every request (including any paginator/resume URL) to the account host and reject
        # redirects — a 3xx from the allowed host could otherwise carry the token off-host (SSRF).
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _endpoint_config(
    config: FreshchatEndpointConfig,
    extra_params: Optional[dict[str, Any]] = None,
    response_actions: Optional[list[ResponseAction]] = None,
) -> Endpoint:
    endpoint: Endpoint = {
        "path": config.path,
        "params": {**build_base_params(config), **(extra_params or {})},
        # Freshchat wraps list rows (and the single configuration object) under a resource key;
        # the extractor unwraps a single matched object into one row.
        "data_selector": config.data_key,
        "paginator": _paginator_for(config),
    }
    if response_actions:
        endpoint["response_actions"] = response_actions
    return endpoint


def _resource(config: FreshchatEndpointConfig, endpoint: Endpoint) -> EndpointResource:
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def _resolve_param(resource_name: str, field_name: str) -> dict[str, Any]:
    return {"type": "resolve", "resource": resource_name, "field": field_name}


def _fanout_resource(
    config: FreshchatEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_paginator_state: Optional[dict[str, Any]],
) -> Iterable[Any]:
    """Build a users -> per-user child fan-out and return the child."""
    fanout = config.fanout
    assert fanout is not None
    parent_config = FRESHCHAT_ENDPOINTS[fanout.parent_name]
    # The parent's mandatory filter and page-size params live on its own endpoint config.
    fanout = dataclasses.replace(fanout, parent_params=build_base_params(parent_config))

    return build_dependent_resource(
        endpoint_configs=FRESHCHAT_ENDPOINTS,
        child_endpoint=config.name,
        fanout=fanout,
        client_config=client_config,
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        # Freshchat's page-size param rides in each endpoint's own params.
        page_size_param=None,
        parent_endpoint_extra={
            "paginator": _paginator_for(parent_config),
            "data_selector": parent_config.data_key,
        },
        child_endpoint_extra={
            "paginator": _paginator_for(config),
            "data_selector": config.data_key,
        },
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )


def _chained_fanout_resource(
    config: FreshchatEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
) -> Iterable[Any]:
    """Build a users -> conversations -> messages chain and return the child."""
    chained = config.chained_fanout
    assert chained is not None
    middle_config = FRESHCHAT_ENDPOINTS[chained.parent_name]
    middle_fanout = middle_config.fanout
    if middle_fanout is None:
        raise ValueError(f"'{chained.parent_name}' does not fan out from a top-level endpoint")
    root_config = FRESHCHAT_ENDPOINTS[middle_fanout.parent_name]

    root_resource = _resource(root_config, _endpoint_config(root_config))
    middle_resource = _resource(
        middle_config,
        _endpoint_config(
            middle_config,
            extra_params={middle_fanout.resolve_param: _resolve_param(root_config.name, middle_fanout.resolve_field)},
            response_actions=SKIP_MISSING_PARENT,
        ),
    )
    child_resource = _resource(
        config,
        _endpoint_config(
            config,
            extra_params={chained.resolve_param: _resolve_param(middle_config.name, chained.resolve_field)},
            response_actions=SKIP_MISSING_PARENT,
        ),
    )
    child_resource["include_from_parent"] = chained.include_from_parent

    return build_chained_resource(
        resources=[root_resource, middle_resource, child_resource],
        child_name=config.name,
        parent_name=middle_config.name,
        parent_field_renames=chained.parent_field_renames,
        client_config=client_config,
        team_id=team_id,
        job_id=job_id,
    )


def _source_response(
    config: FreshchatEndpointConfig,
    items: Callable[[], Iterable[Any]],
    supports_resume: bool = True,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=PRIMARY_KEYS[config.name],
        supports_resume=supports_resume,
        # Every endpoint is full refresh, so this only describes the order rows arrive in.
        sort_mode="asc",
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def freshchat_source(
    api_key: str,
    domain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FreshchatResumeConfig],
) -> SourceResponse:
    config = FRESHCHAT_ENDPOINTS[endpoint]

    # Re-check at run time (not just at source-create) so an edited or previously-saved domain
    # can't aim the stored token at a non-Freshworks host (SSRF). The base host is implicitly
    # trusted by the client's allowlist, so this suffix check on the domain itself is the real
    # boundary.
    normalized = normalize_domain(domain)
    if not is_allowed_host(normalized):
        raise FreshchatHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)

    client_config = _client_config(api_key, domain)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(FreshchatResumeConfig(page=int(state["page"])))

    if config.chained_fanout is not None:
        # A two-level chain takes no resume state: one hook consumed at two levels would corrupt
        # the saved page. The table is full refresh, so a retry restarts it.
        chained = _chained_fanout_resource(config, client_config, team_id, job_id)
        return _source_response(config, lambda: chained, supports_resume=False)

    if config.fanout is not None:
        dependent = _fanout_resource(config, client_config, team_id, job_id, save_checkpoint, initial_paginator_state)
        return _source_response(config, lambda: dependent)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [_resource(config, _endpoint_config(config))],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Freshchat endpoint is full refresh
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, lambda: resource)


def _returned_json(response: Response) -> bool:
    """Classify the probe body the way the sync path classifies a page body.

    An empty body is not a mismatch: the REST client reads an empty 2xx as a valid empty page. A
    body that starts as a JSON value but is cut short is a truncated read, which the sync path
    retries, so it must not be reported here as the wrong host either.
    """
    if not response.content or not response.content.strip():
        return True
    return _looks_like_json(response.content)


def validate_credentials(domain: str, api_key: str) -> tuple[Optional[int], bool]:
    """Probe the Freshchat API. Returns ``(status code, whether the body was JSON)``.

    The status is ``None`` on a connection error. A Freshworks portal domain serves the web app on
    these paths and answers the probe with 200 and HTML, so the status alone cannot tell an API host
    from a host that only serves a UI. The body has to be JSON for the domain to be usable.

    Hits the account-configuration endpoint, the cheapest resource any valid token can read.
    """
    try:
        # Redirects pinned off on the session so a 3xx can't carry the token to another host.
        session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
        response = session.get(
            f"{_base_url(domain)}/accounts/configuration",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=VALIDATE_TIMEOUT,
            allow_redirects=False,
        )
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return None, False

    return response.status_code, _returned_json(response)
