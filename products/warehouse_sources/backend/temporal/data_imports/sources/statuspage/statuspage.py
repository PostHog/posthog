import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from requests import PreparedRequest

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    ClientConfig,
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.settings import STATUSPAGE_ENDPOINTS

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


@dataclasses.dataclass
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
    if not config.page_scoped:
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
