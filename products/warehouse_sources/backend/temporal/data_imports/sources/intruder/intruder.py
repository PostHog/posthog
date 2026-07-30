import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.settings import (
    INTRUDER_ENDPOINTS,
    IntruderEndpointConfig,
)

INTRUDER_BASE_URL = "https://api.intruder.io/v1"
# Intruder caps authenticated requests at 5000/hour, so we page as large as the API allows to keep
# the request count down. Its list endpoints default to 25 per page and accept a `limit` param.
PAGE_SIZE = 100


@dataclasses.dataclass
class IntruderResumeConfig:
    # Full URL of the next page to fetch for a standard (non-fan-out) endpoint. Intruder returns a
    # ready-to-follow `next` URL on every paginated response. None means "start at the first page".
    next_url: str | None = None
    # Legacy field from the hand-rolled fan-out bookmark, kept so state saved by an older build still
    # parses (ResumableSourceManager does dataclass(**saved)). No longer written.
    issue_id: int | None = None
    # Framework fan-out resume state for the occurrences endpoint:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {"next_url": ...} | None}.
    fanout_state: dict | None = None


def _non_secret_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so the token is redacted out of logs
    # and raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _client_config(access_token: str) -> ClientConfig:
    # allowed_hosts=[] pins every request — including API-returned `next` links and seeded resume
    # URLs — to the base_url host (api.intruder.io), so a poisoned resume cursor or a spoofed `next`
    # can't exfiltrate the bearer token off-origin. allow_redirects=False refuses any 3xx (a redirect
    # could retarget the authenticated request at another host). Together these reproduce the
    # hand-rolled SSRF guard.
    return {
        "base_url": INTRUDER_BASE_URL,
        "headers": _non_secret_headers(),
        "auth": {"type": "bearer", "token": access_token},
        "paginator": JSONResponsePaginator(next_url_path="next"),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _rename_issue_id(row: dict[str, Any]) -> dict[str, Any]:
    # `include_from_parent=["id"]` injects the owning issue's id as `_issues_id`; expose it as
    # `issue_id` so the composite primary key [issue_id, id] matches the pre-migration row shape.
    if "_issues_id" in row:
        row["issue_id"] = row.pop("_issues_id")
    return row


def _source_response(endpoint: str, config: IntruderEndpointConfig, items: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _list_source(
    access_token: str,
    endpoint: str,
    config: IntruderEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[IntruderResumeConfig],
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": _client_config(access_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "results",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(IntruderResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # full refresh only — no Intruder list endpoint exposes a verifiable server-side cursor
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _source_response(endpoint, config, resource)


def _occurrences_source(
    access_token: str,
    endpoint: str,
    config: IntruderEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[IntruderResumeConfig],
) -> SourceResponse:
    """Fan out over every issue, materializing its occurrences as rows tagged with `issue_id`.

    Each occurrence row gets the owning `issue_id` injected so the composite primary key
    [issue_id, id] stays unique table-wide. Full refresh only — re-pulled rows on resume are deduped
    by the primary key on merge.
    """
    rest_config: RESTAPIConfig = {
        "client": _client_config(access_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": "issues",
                "endpoint": {
                    "path": INTRUDER_ENDPOINTS["issues"].path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "results",
                },
            },
            {
                "name": endpoint,
                "include_from_parent": ["id"],
                "endpoint": {
                    "path": config.path,
                    "params": {
                        "issue_id": {"type": "resolve", "resource": "issues", "field": "id"},
                        "limit": PAGE_SIZE,
                    },
                    "data_selector": "results",
                },
                "data_map": _rename_issue_id,
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(IntruderResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    child = next(resource for resource in resources if resource.name == endpoint)
    return _source_response(endpoint, config, child)


def intruder_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[IntruderResumeConfig],
) -> SourceResponse:
    config = INTRUDER_ENDPOINTS[endpoint]
    if config.fan_out_over_issues:
        return _occurrences_source(access_token, endpoint, config, team_id, job_id, resumable_source_manager)
    return _list_source(access_token, endpoint, config, team_id, job_id, resumable_source_manager)


def validate_credentials(access_token: str) -> bool:
    # `/targets/` requires a valid token (401 otherwise) and returns 200 even for accounts with no
    # targets, making it a cheap, side-effect-free probe. `/health/` can't be used — it returns 200
    # regardless of whether the token is valid. validate_via_probe swallows transport errors and maps
    # them to "not validated".
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{INTRUDER_BASE_URL}/targets/?limit=1",
        headers={"Authorization": f"Bearer {access_token}", **_non_secret_headers()},
    )
    return ok


__all__ = ["IntruderResumeConfig", "intruder_source", "validate_credentials"]
