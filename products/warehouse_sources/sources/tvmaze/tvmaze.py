import dataclasses
from collections.abc import Iterator
from typing import Any, Optional, cast

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    PageNumberPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
)
from products.warehouse_sources.sources.tvmaze.settings import BASE_URL, ENDPOINT_CONFIGS, TVMazeEndpointConfig

# Rows per yielded batch when flattening the /updates id->timestamp maps (the
# people map holds hundreds of thousands of entries in a single response).
UPDATES_CHUNK_SIZE = 5000


@dataclasses.dataclass(frozen=False)
class TVMazeResumeConfig:
    page: int | None = None
    # Fan-out progress (the show index page plus finished shows) for the per-show tables.
    fanout_state: Optional[dict[str, Any]] = None


def _make_index_paginator() -> PageNumberPaginator:
    # TVmaze signals the end of an index with a 404 (handled via a response
    # action), not an empty page — deleted records leave gaps, so an empty 200
    # page mid-index must not stop pagination early.
    return PageNumberPaginator(base_page=0, page_param="page", stop_after_empty_page=False)


def _index_endpoint_extra() -> Endpoint:
    # The documented index terminator: a page past the last one returns 404 with
    # a JSON body, which ends pagination cleanly.
    return {"response_actions": [{"status_code": 404, "action": "ignore"}]}


def _client_config() -> ClientConfig:
    # Open public API — no auth. Traffic still rides the tracked session
    # RESTClient builds by default.
    return {"base_url": BASE_URL, "paginator": _make_index_paginator()}


def get_resource(endpoint: str) -> EndpointResource:
    config = ENDPOINT_CONFIGS[endpoint]
    index_endpoint: Endpoint = {"path": config.path, "params": {}}
    index_endpoint.update(_index_endpoint_extra())
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": index_endpoint,
        "table_format": "delta",
    }


def _flatten_cast_row(row: dict[str, Any]) -> dict[str, Any]:
    person = row.get("person") or {}
    character = row.get("character") or {}
    row["person_id"] = person.get("id")
    row["character_id"] = character.get("id")
    return row


def _updates_items(path: str) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session()
    response = session.get(f"{BASE_URL}{path}")
    response.raise_for_status()
    payload = response.json()

    batch: list[dict[str, Any]] = []
    for record_id, updated in payload.items():
        batch.append({"id": int(record_id), "updated": updated})
        if len(batch) >= UPDATES_CHUNK_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


def _index_source(
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TVMazeResumeConfig],
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": _client_config(),
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.page is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Called after each page is yielded, so a crash re-fetches the last page
        # rather than skipping it; the Redis TTL handles cleanup on completion.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(TVMazeResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        # Index pages are ordered by ascending id; no stable non-null datetime
        # field exists (premiered can be null), so partitioning is skipped.
        sort_mode="asc",
    )


def _fanout_source(
    endpoint: str,
    config: TVMazeEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TVMazeResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.fanout_state:
            initial_paginator_state = resume_config.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(TVMazeResumeConfig(fanout_state=state))

    resource = cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=ENDPOINT_CONFIGS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param=None,
            parent_endpoint_extra=_index_endpoint_extra(),
            # Per-show lists come back whole in one response; without this the child
            # would inherit the index page-number paginator.
            child_endpoint_extra={"paginator": "single_page"},
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
            resume_parent_pagination=True,
        ),
    )
    if endpoint == "cast":
        resource = resource.add_map(_flatten_cast_row)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # One request series per show, so the table as a whole has no order.
        sort_mode=None,
    )


def tvmaze_source(
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TVMazeResumeConfig],
) -> SourceResponse:
    endpoint_config = ENDPOINT_CONFIGS[endpoint]

    if endpoint_config.kind == "updates":
        return SourceResponse(
            name=endpoint,
            items=lambda: _updates_items(endpoint_config.path),
            primary_keys=["id"],
            sort_mode="asc",
        )

    if endpoint_config.kind == "fanout":
        return _fanout_source(endpoint, endpoint_config, team_id, job_id, resumable_source_manager)

    return _index_source(endpoint, team_id, job_id, resumable_source_manager)


def check_connection() -> tuple[bool, str | None]:
    try:
        # The first index page is part of the API contract (and cached at
        # TVmaze's load balancer), unlike any individual show id.
        response = make_tracked_session().get(f"{BASE_URL}/shows", params={"page": 0})
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None

    return False, f"TVmaze API is unreachable (status {response.status_code}). Try again later."
