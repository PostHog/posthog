import dataclasses
from collections.abc import Callable
from typing import Any, Optional, cast
from urllib.parse import urlencode

import requests
from requests import PreparedRequest

from products.warehouse_sources.sources.sdk import (
    AuthConfigBase,
    ClientConfig,
    PageNumberPaginator,
    Resource,
    ResponseAction,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_chained_resource,
    make_tracked_session,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.sources.statuspage.settings import STATUSPAGE_ENDPOINTS, StatuspageEndpointConfig

STATUSPAGE_BASE_URL = "https://api.statuspage.io/v1"
# Every page-scoped endpoint fans out over the ids of this top-level listing.
_PARENT_ENDPOINT = "pages"

# Statuspage rate-limits paginated reads (60 requests/minute on a rolling 60s window) and returns
# 420/429 with a Retry-After header when exceeded. 429 and 5xx are retried by the shared client
# automatically; 420 is a vendor-specific code the client doesn't recognise, so we promote it to a
# retryable error via a response action. 8 attempts with bounded exponential backoff sits well above
# the 60s window so a throttle clears.
_MAX_ATTEMPTS = 8
# The client's own retry check only fires on 429/5xx status, so 420 (Statuspage's non-standard
# rate-limit code) is promoted to retryable here.
_RETRY_ACTIONS: list[ResponseAction] = [{"status_code": 420, "action": "retry"}]


class StatuspageAuth(AuthConfigBase):
    """Sends the static Manage API key with the required ``OAuth`` prefix.

    Despite the prefix this is a static API key, not an OAuth2 bearer token — that's the header format
    Statuspage's Manage API requires. Declaring it as an auth (rather than a hand-built header) lets the
    shared client scrub the key from every raised error message and HTTP log sample.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"OAuth {self.api_key}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.api_key,) if self.api_key else ()


@dataclasses.dataclass(frozen=False)
class StatuspageResumeConfig:
    # Legacy fields from the pre-framework implementation, retained (with defaults) so a checkpoint
    # written by the old code still parses via ``dataclass(**saved)``. They are no longer written; a
    # loaded state carrying only these starts fresh (a full re-read, deduped on the primary key).
    page: int = 1
    parent_page_id: Optional[str] = None
    # Simple-resource (``pages``) paginator snapshot: ``{"page": <next page to fetch>}``.
    paginator_state: Optional[dict[str, Any]] = None
    # Fan-out snapshot for a page-scoped endpoint:
    # ``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}``.
    fanout_state: Optional[dict[str, Any]] = None


def _promote_page_id(row: dict[str, Any]) -> dict[str, Any]:
    # include_from_parent injects the parent page's id as ``_pages_id``; expose it under the ``page_id``
    # column the composite primary key expects. A sync aggregates rows from every page the key can see,
    # and the bare resource id is only unique within its parent page.
    if "_pages_id" in row:
        row["page_id"] = row.pop("_pages_id")
    return row


def _page_scoped_parent(
    config: StatuspageEndpointConfig,
) -> Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]:
    keep = config.parent_filter

    def _map(row: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        row = _promote_page_id(row)
        if keep is not None and not keep(row):
            return []
        return row

    return _map


def _chained_resource(
    config: StatuspageEndpointConfig, client_config: ClientConfig, team_id: int, job_id: str
) -> Resource:
    """Fan out /pages -> a page-scoped listing -> one child request per listed row.

    The chain carries no resume state, so the source reports these endpoints as not resumable.
    """
    assert config.parent is not None and config.parent_param is not None
    pages = STATUSPAGE_ENDPOINTS[_PARENT_ENDPOINT]
    middle = STATUSPAGE_ENDPOINTS[config.parent]
    child_params: dict[str, Any] = {
        "page_id": {"type": "resolve", "resource": middle.name, "field": "page_id"},
        config.parent_param: {"type": "resolve", "resource": middle.name, "field": "id"},
    }
    child_endpoint: dict[str, Any] = {
        "path": config.path,
        "params": child_params,
        "response_actions": [
            *_RETRY_ACTIONS,
            *({"status_code": status, "action": "ignore"} for status in config.ignore_statuses),
        ],
    }
    if config.single_object:
        child_endpoint |= {"paginator": "single_page", "data_selector": None, "data_selector_required": False}
    else:
        child_params[config.page_size_param] = config.page_size

    return cast(
        Resource,
        build_chained_resource(
            resources=[
                {
                    "name": pages.name,
                    "endpoint": {
                        "path": pages.path,
                        "params": {pages.page_size_param: pages.page_size},
                        "response_actions": _RETRY_ACTIONS,
                    },
                },
                {
                    "name": middle.name,
                    "endpoint": {
                        "path": middle.path,
                        "params": {
                            "page_id": {"type": "resolve", "resource": pages.name, "field": "id"},
                            middle.page_size_param: middle.page_size,
                        },
                        "response_actions": _RETRY_ACTIONS,
                    },
                    "include_from_parent": ["id"],
                    "data_map": _page_scoped_parent(config),
                },
                {
                    "name": config.name,
                    "endpoint": cast(Any, child_endpoint),
                    "include_from_parent": list(config.parent_fields),
                },
            ],
            child_name=config.name,
            parent_name=middle.name,
            parent_field_renames=config.parent_fields,
            client_config=client_config,
            team_id=team_id,
            job_id=job_id,
        ),
    )


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": STATUSPAGE_BASE_URL,
        # Auth (the OAuth-prefixed key) is supplied via the framework auth so its value is redacted from
        # errors and logs; only the non-secret Content-Type header is set here.
        "headers": {"Content-Type": "application/json"},
        "auth": StatuspageAuth(api_key),
        # 1-based page number; stop on the first empty page. We deliberately do NOT stop on a short page:
        # if the API ignores the size param and returns fewer than per_page, that page is still not last.
        "paginator": PageNumberPaginator(base_page=1),
        "max_retries": _MAX_ATTEMPTS,
        # Keep the credentialed request pinned to the validated host — reject any redirect so it can't be
        # replayed against another origin.
        "allow_redirects": False,
    }


def statuspage_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[StatuspageResumeConfig],
) -> SourceResponse:
    config = STATUSPAGE_ENDPOINTS[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    client_config = _client_config(api_key)

    resource: Resource
    if config.parent is not None:
        resource = _chained_resource(config, client_config, team_id, job_id)
    elif not config.page_scoped:
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": {config.page_size_param: config.page_size},
                        "response_actions": _RETRY_ACTIONS,
                    },
                }
            ],
        }

        def save_simple(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash resumes at
            # the next page rather than re-reading from the top.
            if state is not None:
                resumable_source_manager.save_state(StatuspageResumeConfig(paginator_state=state))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_simple,
            initial_paginator_state=(resume.paginator_state if resume is not None else None),
        )
    else:
        parent_config = STATUSPAGE_ENDPOINTS[_PARENT_ENDPOINT]
        fanout_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [
                {
                    "name": _PARENT_ENDPOINT,
                    "endpoint": {
                        "path": parent_config.path,
                        "params": {parent_config.page_size_param: parent_config.page_size},
                        "response_actions": _RETRY_ACTIONS,
                    },
                },
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": {
                            # Binds the {page_id} path placeholder from each parent page's id.
                            "page_id": {"type": "resolve", "resource": _PARENT_ENDPOINT, "field": "id"},
                            config.page_size_param: config.page_size,
                        },
                        "response_actions": _RETRY_ACTIONS,
                    },
                    "include_from_parent": ["id"],
                    "data_map": _promote_page_id,
                },
            ],
        }

        def save_fanout(state: Optional[dict[str, Any]]) -> None:
            if state is not None:
                resumable_source_manager.save_state(StatuspageResumeConfig(fanout_state=state))

        resources = rest_api_resources(
            fanout_config,
            team_id,
            job_id,
            None,
            resume_hook=save_fanout,
            initial_paginator_state=(resume.fanout_state if resume is not None else None),
        )
        resource = next(r for r in resources if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_key,
        # Full refresh only — Statuspage exposes no server-side timestamp filter — but rows still arrive
        # in a stable page order, so asc is correct.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
        # A chained fan-out saves no cursor, so a shutdown hand-off would restart it from the top.
        supports_resume=config.parent is None,
    )


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{STATUSPAGE_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Confirm the API key is genuine with one cheap probe against the pages listing."""
    session = make_tracked_session(
        headers={"Authorization": f"OAuth {api_key}", "Content-Type": "application/json"},
        redact_values=(api_key,),
        allow_redirects=False,
    )
    url = _build_url("/pages", {"per_page": 1, "page": 1})
    try:
        response = session.get(url, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Statuspage API key. Please check your API key and try again."
    if response.status_code == 403:
        return False, "Your Statuspage API key does not have permission to list pages."

    try:
        message = response.json().get("error", response.text)
    except Exception:
        message = response.text
    return False, message
