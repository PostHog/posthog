import dataclasses
from typing import Any, Optional

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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.settings import (
    LAUNCHDARKLY_ENDPOINTS,
    LaunchDarklyEndpointConfig,
)

API_HOST = "https://app.launchdarkly.com"
BASE_URL = f"{API_HOST}/api/v2"

# Parent resource name for fan-out endpoints. Named singular so include_from_parent injects the
# project key under `_project_key` (make_parent_key_name(name, "key") == f"_{name}_key"), matching
# the column the hand-rolled source emitted.
PROJECTS_PARENT_NAME = "project"


@dataclasses.dataclass
class LaunchDarklyResumeConfig:
    # Full URL of the next page to fetch for a top-level endpoint ("" once exhausted).
    next_url: str = ""
    # Retained for backwards compatibility with resume state saved by the previous
    # implementation; unused by the current code.
    project_key: str = ""
    # Framework fan-out resume state ({"completed": [...], "current": ..., "child_state": ...}).
    fanout_state: Optional[dict[str, Any]] = None


def _get_headers(access_token: str) -> dict[str, str]:
    # LaunchDarkly expects the raw access token in the Authorization header, with no
    # "Bearer" prefix (see https://apidocs.launchdarkly.com/#section/Overview/Authentication).
    return {
        "Authorization": access_token,
        "Accept": "application/json",
    }


def _resolve_url(href: str) -> str:
    # LaunchDarkly returns relative hrefs (e.g. "/api/v2/projects?limit=20&offset=20").
    if href.startswith("http"):
        return href
    return f"{API_HOST}{href}"


class LaunchDarklyLinkPaginator(BaseNextUrlPaginator):
    """Follows LaunchDarkly's ``_links.next.href`` pagination.

    The href is usually a relative path, so it's resolved against the API host before the next
    request is sent. Resume (``get_resume_state``/``set_resume_state`` on the next URL) is inherited
    from ``BaseNextUrlPaginator``.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = {}
        links = (body.get("_links") if isinstance(body, dict) else None) or {}
        next_link = links.get("next") or {}
        href = next_link.get("href")
        if href:
            self._next_url = _resolve_url(href)
            self._has_next_page = True
        else:
            self._has_next_page = False

    def __str__(self) -> str:
        return "LaunchDarklyLinkPaginator()"


def _client_config(access_token: str) -> dict[str, Any]:
    return {
        "base_url": BASE_URL,
        # Only the non-secret Accept header goes here; the access token rides on the framework auth
        # so it's scrubbed from any raised error message.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": access_token, "name": "Authorization", "location": "header"},
    }


def _build_toplevel_resource(
    config: LaunchDarklyEndpointConfig,
    access_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LaunchDarklyResumeConfig],
    resume: Optional[LaunchDarklyResumeConfig],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(access_token),
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": config.page_size},
                    "data_selector": "items",
                    "paginator": LaunchDarklyLinkPaginator(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_url:
        initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded (only while a next page remains) so a crash re-fetches the
        # next page rather than re-emitting the one just yielded (merge dedupes regardless).
        if state and state.get("next_url"):
            resumable_source_manager.save_state(LaunchDarklyResumeConfig(next_url=state["next_url"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _build_fanout_resource(
    config: LaunchDarklyEndpointConfig,
    access_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LaunchDarklyResumeConfig],
    resume: Optional[LaunchDarklyResumeConfig],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(access_token),
        "resources": [
            {
                "name": PROJECTS_PARENT_NAME,
                "endpoint": {
                    "path": "/projects",
                    "params": {"limit": LAUNCHDARKLY_ENDPOINTS["projects"].page_size},
                    "data_selector": "items",
                    "paginator": LaunchDarklyLinkPaginator(),
                },
            },
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {
                        "project_key": {"type": "resolve", "resource": PROJECTS_PARENT_NAME, "field": "key"},
                        "limit": config.page_size,
                    },
                    "data_selector": "items",
                    "paginator": LaunchDarklyLinkPaginator(),
                },
                # Injects the parent project's key into every child row as `_project_key`.
                "include_from_parent": ["key"],
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.fanout_state:
        initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(LaunchDarklyResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if resource.name == config.name)


def launchdarkly_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LaunchDarklyResumeConfig],
) -> SourceResponse:
    config = LAUNCHDARKLY_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.requires_project:
        resource = _build_fanout_resource(config, access_token, team_id, job_id, resumable_source_manager, resume)
    else:
        resource = _build_toplevel_resource(config, access_token, team_id, job_id, resumable_source_manager, resume)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_key,
        # LaunchDarkly timestamps are epoch-millisecond integers and the datetime
        # partitioner expects epoch-seconds, so partitioning is intentionally left off to
        # avoid mis-bucketing rows far into the future.
        partition_mode=None,
        partition_keys=None,
    )


def validate_credentials(access_token: str, path: str = "/caller-identity") -> int | None:
    """Probe an endpoint and return the HTTP status code (or None on transport failure)."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{BASE_URL}{path}",
        headers=_get_headers(access_token),
    )
    return status
