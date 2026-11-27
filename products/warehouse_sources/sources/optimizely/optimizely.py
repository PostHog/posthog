from collections.abc import Callable
from typing import Any

from products.warehouse_sources.sources.optimizely.settings import OPTIMIZELY_ENDPOINTS, OptimizelyEndpointConfig
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    EndpointResource,
    HeaderLinkPaginator,
    Resource,
    ResponseAction,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    frozen,
    make_tracked_session,
    rest_api_resource,
    rest_api_resources,
    validate_via_probe,
)

OPTIMIZELY_API_HOST = "api.optimizely.com"
OPTIMIZELY_BASE_URL = f"https://{OPTIMIZELY_API_HOST}/v2"
# Optimizely list pages cap at 100 items.
PAGE_SIZE = 100


@frozen
class OptimizelyResumeConfig:
    # What the framework handed the resume hook: the next `Link` URL of a list endpoint, or the
    # finished and in-progress projects of a project fan-out. Stored unchanged.
    paginator_state: dict[str, Any] | None = None
    # The last page of a list endpoint is handed on, so a resume reads nothing again.
    completed: bool = False


_SKIP_INACCESSIBLE: list[ResponseAction] = [
    {"status_code": 400, "action": "ignore"},
    {"status_code": 403, "action": "ignore"},
    {"status_code": 404, "action": "ignore"},
]


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": OPTIMIZELY_BASE_URL,
        # The Bearer token rides in the framework auth config so its value is redacted from logs and
        # raised errors; the client sets the Authorization header itself.
        "auth": {"type": "bearer", "token": api_token},
        # Optimizely paginates via RFC 5988 `Link: rel="next"` headers.
        "paginator": HeaderLinkPaginator(),
        # Pin every request — including the `Link` next-page URL, which a spoofed upstream response
        # could point elsewhere — to Optimizely's API host, so the credentialed Bearer request can't
        # be redirected to an internal address (SSRF) or attacker host (token theft).
        "allowed_hosts": [OPTIMIZELY_API_HOST],
    }


def _simple_source(
    api_token: str,
    endpoint: str,
    config: OptimizelyEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[OptimizelyResumeConfig],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": PAGE_SIZE},
                    # Bare-array body — no data_selector. The old transport tolerated a non-list body
                    # as an empty page, so no data_selector_required here.
                },
            }
        ],
    }
    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=_resume_hook(manager),
        initial_paginator_state=_initial_state(manager),
    )


def _project_scoped_resource(name: str, path: str) -> EndpointResource:
    return {
        "name": name,
        "endpoint": {
            # project_id rides in a query param; embed the resolve placeholder in the path so
            # the binding lands in the query string (resolve only substitutes into paths).
            "path": f"{path}?project_id={{project_id}}",
            "params": {
                "project_id": {"type": "resolve", "resource": "projects", "field": "id"},
                "per_page": PAGE_SIZE,
            },
            # A project without access to this feature (e.g. campaigns on a non-Web project)
            # returns 400/403/404 — treat that as a valid empty page and move to the next
            # project rather than failing the whole stream, matching the old per-project skip.
            "response_actions": _SKIP_INACCESSIBLE,
        },
    }


def _per_parent_resource(endpoint: str, path: str, parent: str, parent_id_param: str) -> EndpointResource:
    return {
        "name": endpoint,
        "endpoint": {
            "path": path,
            "params": {
                parent_id_param: {"type": "resolve", "resource": parent, "field": "id"},
            },
            # Results come back as one object per parent, not a list.
            "data_selector": "$",
            "paginator": SinglePagePaginator(),
            # 202 means the results are still being computed. These tables are full refresh, so
            # skipping the parent would drop its previous snapshot: retry with the client's backoff,
            # and fail the sync (keeping the old table) if the results never finish. 204 means the
            # parent has no results yet (e.g. a draft experiment). 4xx covers parents whose results
            # the token can't read.
            "response_actions": [
                {"status_code": 202, "action": "retry", "message": "Optimizely results are still being computed"},
                {"status_code": 204, "action": "ignore"},
                *_SKIP_INACCESSIBLE,
            ],
        },
    }


def _fan_out_source(
    api_token: str,
    endpoint: str,
    config: OptimizelyEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[OptimizelyResumeConfig],
) -> Resource:
    resources: list[str | EndpointResource] = [
        {
            "name": "projects",
            "endpoint": {
                "path": "/projects",
                "params": {"per_page": PAGE_SIZE},
            },
        },
    ]
    if config.parent is None or config.parent_id_param is None:
        resources.append(_project_scoped_resource(endpoint, config.path))
    else:
        resources.append(_project_scoped_resource(config.parent, OPTIMIZELY_ENDPOINTS[config.parent].path))
        resources.append(_per_parent_resource(endpoint, config.path, config.parent, config.parent_id_param))

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": resources,
    }
    # The framework resumes a fan-out with one dependent level only. The per-parent results tables
    # chain two levels, so they read every project again after a resume (the merge dedupes).
    built = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=_resume_hook(manager),
        initial_paginator_state=_initial_state(manager),
    )
    # Only the requested endpoint's rows are emitted; its ancestors are iterated internally to drive the fan-out.
    return next(resource for resource in built if resource.name == endpoint)


def _initial_state(manager: ResumableSourceManager[OptimizelyResumeConfig]) -> dict[str, Any] | None:
    resume = manager.load_state() if manager.can_resume() else None
    return resume.paginator_state if resume is not None else None


def _resume_hook(manager: ResumableSourceManager[OptimizelyResumeConfig]) -> Callable[[dict[str, Any] | None], None]:
    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state:
            manager.save_state(OptimizelyResumeConfig(paginator_state=state))
        elif state is None:
            manager.save_state(OptimizelyResumeConfig(completed=True))

    return save_checkpoint


def optimizely_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OptimizelyResumeConfig],
) -> SourceResponse:
    config = OPTIMIZELY_ENDPOINTS[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed = resume is not None and resume.completed

    if config.project_scoped:
        resource = _fan_out_source(api_token, endpoint, config, team_id, job_id, resumable_source_manager)
    else:
        resource = _simple_source(api_token, endpoint, config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        on_complete=resumable_source_manager.clear_state,
        items=lambda: [] if completed else resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


def validate_credentials(api_token: str) -> bool:
    """Confirm the personal access token is valid with a cheap projects probe.

    Any reachable response other than 401 means the token is usable (a 403 is a valid token missing
    a scope); a transport error (status None) means "not validated" — matching the old probe.
    """
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{OPTIMIZELY_BASE_URL}/projects?per_page=1",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    return status is not None and status != 401
