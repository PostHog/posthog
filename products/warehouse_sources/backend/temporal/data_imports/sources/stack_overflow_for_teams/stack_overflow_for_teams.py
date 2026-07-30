import re
import dataclasses
from collections.abc import Iterable
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.settings import (
    STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS,
)

BASE_API_PATH = "/v3/teams"

# Stack Overflow for Teams requires a descriptive User-Agent to avoid being throttled; the
# Bearer token is supplied through the framework auth config so it's redacted from logs.
USER_AGENT = "PostHog Data Warehouse (hey@posthog.com)"

# A single path segment: letters, digits, hyphens, underscores. Team names are only ever used
# as a URL path component (the host is always api.stackoverflowteams.com), so this rejects
# anything that would smuggle extra path segments or query parameters into the request.
_TEAM_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def normalize_team(team: str) -> str:
    """Validate and return a bare team name for use in the API path.

    Raises ``ValueError`` on anything that isn't a single path segment.
    """
    cleaned = team.strip()
    if not _TEAM_RE.match(cleaned):
        raise ValueError(
            f"Invalid Stack Overflow for Teams team name: {team!r}. Enter just your team's slug, e.g. 'engineering'."
        )
    return cleaned


def _base_url(team: str) -> str:
    return f"https://api.stackoverflowteams.com{BASE_API_PATH}/{normalize_team(team)}"


@dataclasses.dataclass
class StackOverflowForTeamsResumeConfig:
    # Next 1-indexed page to fetch. Only populated for top-level (non fan-out) endpoints -
    # dependent-resource fan-out (Answers) doesn't expose a resume hook in the rest_source
    # framework, so it always restarts from page 1 of its parent (Questions).
    next_page: int | None = None


def _client_config(team: str, api_token: str) -> ClientConfig:
    return {
        "base_url": _base_url(team),
        "headers": {"Accept": "application/json", "User-Agent": USER_AGENT},
        "auth": {"type": "bearer", "token": api_token},
        # `totalPages` is returned on every paginated list response and lets us stop cleanly on
        # the last page instead of paying for one extra empty-page request.
        "paginator": PageNumberPaginator(base_page=1, page_param="page", total_path="totalPages"),
    }


def _non_fanout_source(
    team: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[StackOverflowForTeamsResumeConfig],
) -> SourceResponse:
    config = STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"pageSize": config.page_size}
    if config.sort:
        params["sort"] = config.sort
    if config.order:
        params["order"] = config.order

    rest_config: RESTAPIConfig = {
        "client": _client_config(team, api_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A 200 body without an "items" key yields an empty page and ends pagination.
                    "data_selector": "items",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge/replace re-writes it) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(StackOverflowForTeamsResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def _fanout_source(
    team: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS[endpoint]
    assert config.fanout is not None

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(team, api_token),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            # Answers has no server-side timestamp filter, so this fan-out is always full
            # refresh - the watermark is never consulted.
            db_incremental_field_last_value=None,
            should_use_incremental_field=False,
            page_size_param="pageSize",
            parent_endpoint_extra={"data_selector": "items"},
            child_endpoint_extra={"data_selector": "items"},
        ),
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: dependent_resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def stack_overflow_for_teams_source(
    team: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[StackOverflowForTeamsResumeConfig],
) -> SourceResponse:
    config = STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS[endpoint]
    if config.fanout is not None:
        return _fanout_source(team, api_token, endpoint, team_id, job_id)

    return _non_fanout_source(team, api_token, endpoint, team_id, job_id, resumable_source_manager)


def validate_credentials(team: str, api_token: str) -> tuple[bool, int | None]:
    """Probe the `/users/me` endpoint to confirm the token is genuine for this team.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if the team name is malformed so the caller can surface a precise message.
    """
    url = f"{_base_url(team)}/users/me"
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json", "User-Agent": USER_AGENT},
    )
