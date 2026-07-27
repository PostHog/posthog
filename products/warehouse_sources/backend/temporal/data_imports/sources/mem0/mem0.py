"""Mem0 platform data warehouse source, built on the shared ``rest_source`` framework.

Reference: https://docs.mem0.ai/api-reference

All outbound HTTP goes through the framework's tracked session so calls show up in our HTTP logs,
OTel metrics, and sample-capture pipeline. The API key travels via the framework ``auth`` config so
it is redacted from logs and raised error messages.
"""

import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.settings import (
    ENTITIES_ENDPOINT,
    EVENTS_ENDPOINT,
    MEM0_BASE_URL,
    MEM0_ENDPOINTS,
    MEMORIES_ENDPOINT,
)

# Every memory carries at least one owning entity id (user_id / agent_id / app_id / run_id are
# required at add time), so OR-ing the wildcard over all four matches the whole store. A bare
# {"user_id": "*"} would miss memories scoped only to an agent, app, or run.
_MATCH_ALL_FILTER: dict[str, Any] = {"OR": [{"user_id": "*"}, {"agent_id": "*"}, {"app_id": "*"}, {"run_id": "*"}]}


@dataclasses.dataclass
class Mem0ResumeConfig:
    """Resume state for a crashed/heartbeat-timed-out sync.

    ``endpoint`` scopes the state so a memories cursor is never replayed against events.
    ``next_url`` is the next-page envelope URL to resume from (memories and events both paginate
    via a ``next`` link). ``cutoff`` pins the incremental filter value the run started with so a
    resumed memories attempt paginates the same server-side result set. ``page`` is retained for
    backward compatibility with resume state written by the pre-framework implementation.
    """

    endpoint: str
    page: int | None = None
    next_url: str | None = None
    cutoff: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    # GET /v1/ping/ is the cheap key probe the official mem0ai SDK uses on client init.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{MEM0_BASE_URL}/v1/ping/",
        headers=_get_headers(api_key),
    )
    return ok


def _format_cutoff(value: Any) -> str | None:
    """Format an incremental cursor value for the Mem0 filter DSL.

    The documented filter examples only demonstrate date strings (e.g. ``"2024-07-01"``), so we
    send the cursor as a date. ``gte`` on the truncated date only over-fetches rows from the
    cursor's own day — the merge on the primary key dedupes them — and can never skip rows.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _build_memories_filters(incremental_field: str, cutoff: str | None) -> dict[str, Any]:
    if not cutoff:
        return _MATCH_ALL_FILTER
    return {"AND": [_MATCH_ALL_FILTER, {incremental_field: {"gte": cutoff}}]}


def _ensure_mem0_origin(url: str) -> str:
    """Resolve a pagination/resume URL against the Mem0 API origin, refusing any that leave it.

    Mem0's ``next`` links are sometimes relative (e.g. ``/v1/events/?page=2``); resolving them
    against the API base yields the absolute URL the request must target. The session carries the
    API key on every request, so following an off-origin link (from a tampered response, or a
    poisoned resume-state entry) would send the credential to an arbitrary host. Rejects any URL
    that resolves to a scheme or host other than the Mem0 API origin — including a scheme-relative
    ``//other-host`` link or an ``http://`` downgrade to the same host.
    """
    resolved = urljoin(MEM0_BASE_URL, url)
    parsed = urlparse(resolved)
    expected = urlparse(MEM0_BASE_URL)
    if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc:
        raise ValueError(
            f"Refusing to follow a pagination URL off the Mem0 API origin: {parsed.scheme}://{parsed.netloc}"
        )
    return resolved


class Mem0OriginPinnedPaginator(JSONResponsePaginator):
    """A ``JSONResponsePaginator`` (follows the ``next`` link in the body) that refuses any
    next-page or resume URL off the Mem0 API origin before a credentialed request is sent."""

    def update_state(self, response: Any, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._next_url is not None:
            self._next_url = _ensure_mem0_origin(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url is not None:
            state = {**state, "next_url": _ensure_mem0_origin(next_url)}
        super().set_resume_state(state)


def _base_client(api_key: str) -> ClientConfig:
    return {
        "base_url": MEM0_BASE_URL,
        # Only the non-secret Accept header lives here; the key rides the framework auth so it is
        # redacted from logs and error messages.
        "headers": {"Accept": "application/json"},
        "auth": {
            "type": "api_key",
            "api_key": f"Token {api_key}",
            "name": "Authorization",
            "location": "header",
        },
    }


def _entities_unwrap(item: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    # Documented as a bare JSON array; tolerate a {"results": [...]} envelope in case the API
    # grows one by exploding the wrapper into its rows.
    if isinstance(item, dict) and isinstance(item.get("results"), list):
        return item["results"]
    return item


def mem0_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[Mem0ResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
    org_id: str | None = None,
    project_id: str | None = None,
) -> SourceResponse:
    endpoint_config = MEM0_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.endpoint != endpoint:
        resume = None

    client = _base_client(api_key)

    if endpoint == MEMORIES_ENDPOINT:
        resource = _memories_resource(
            client,
            team_id,
            job_id,
            resumable_source_manager,
            resume,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )
    elif endpoint == ENTITIES_ENDPOINT:
        resource = _entities_resource(client, team_id, job_id, org_id, project_id)
    elif endpoint == EVENTS_ENDPOINT:
        resource = _events_resource(client, team_id, job_id, resumable_source_manager, resume)
    else:
        raise ValueError(f"Unknown Mem0 endpoint: {endpoint}")

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        # The memories list exposes no sort parameter, so row order within a run is undefined.
        # "desc" makes the pipeline commit the incremental watermark only at successful end of
        # run — with undefined ordering, per-batch ("asc") checkpointing could advance the
        # watermark past rows a crashed run never yielded.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def _memories_resource(
    client: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[Mem0ResumeConfig],
    resume: Mem0ResumeConfig | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Any:
    config = MEM0_ENDPOINTS[MEMORIES_ENDPOINT]

    # On resume the pinned cutoff (not a freshly computed one) drives the filter, otherwise the
    # resumed run paginates a different server-side result set than the pages already fetched.
    if resume is not None and resume.next_url:
        cutoff = resume.cutoff
        initial_paginator_state: dict[str, Any] | None = {"next_url": resume.next_url}
    else:
        cutoff = (
            _format_cutoff(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value
            else None
        )
        initial_paginator_state = None

    filters = _build_memories_filters(incremental_field or "updated_at", cutoff)

    rest_config: RESTAPIConfig = {
        "client": client,
        "resource_defaults": {},
        "resources": [
            {
                "name": MEMORIES_ENDPOINT,
                "endpoint": {
                    "path": config.path,
                    "method": "POST",
                    "params": {"page": 1, "page_size": config.page_size},
                    "json": {"filters": filters},
                    "data_selector": "results",
                    "paginator": Mem0OriginPinnedPaginator(),
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (the merge dedupes) rather than skipping it. The cutoff is pinned so a
        # resumed run filters on the same value the original run started with.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(
                Mem0ResumeConfig(endpoint=MEMORIES_ENDPOINT, next_url=state["next_url"], cutoff=cutoff)
            )

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _entities_resource(
    client: ClientConfig,
    team_id: int,
    job_id: str,
    org_id: str | None,
    project_id: str | None,
) -> Any:
    config = MEM0_ENDPOINTS[ENTITIES_ENDPOINT]

    rest_config: RESTAPIConfig = {
        "client": client,
        "resource_defaults": {},
        "resources": [
            {
                "name": ENTITIES_ENDPOINT,
                "endpoint": {
                    "path": config.path,
                    "method": "GET",
                    "params": {"org_id": org_id, "project_id": project_id},
                    "paginator": SinglePagePaginator(),
                },
                "data_map": _entities_unwrap,
            }
        ],
    }

    return rest_api_resource(rest_config, team_id, job_id, None)


def _events_resource(
    client: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[Mem0ResumeConfig],
    resume: Mem0ResumeConfig | None,
) -> Any:
    config = MEM0_ENDPOINTS[EVENTS_ENDPOINT]

    initial_paginator_state: dict[str, Any] | None = None
    if resume is not None and resume.next_url:
        # Validate the seeded resume URL before it is ever requested (poisoned resume state must
        # not receive the credentialed request); the paginator re-checks on seed too.
        initial_paginator_state = {"next_url": _ensure_mem0_origin(resume.next_url)}

    rest_config: RESTAPIConfig = {
        "client": client,
        "resource_defaults": {},
        "resources": [
            {
                "name": EVENTS_ENDPOINT,
                "endpoint": {
                    "path": config.path,
                    "method": "GET",
                    "data_selector": "results",
                    "paginator": Mem0OriginPinnedPaginator(),
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("next_url"):
            resumable_source_manager.save_state(Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=state["next_url"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
