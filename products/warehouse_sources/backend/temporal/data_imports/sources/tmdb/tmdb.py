import dataclasses
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.settings import TMDB_ENDPOINTS

TMDB_BASE_URL = "https://api.themoviedb.org/3"

# TMDB list endpoints (popular/top_rated/...) and /discover are hard-capped at 500 pages server-side,
# so there's no point requesting beyond that — it 422s.
MAX_PAGES = 500


@dataclasses.dataclass(frozen=False)
class TMDbResumeConfig:
    # Next page number to fetch. Page-number pagination means a single integer is enough to resume.
    next_page: int | None = None
    # Per-title endpoints resume by parent: the child paths already synced, the one in progress, and
    # its paginator state. See `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


RowMapper = Callable[[dict[str, Any]], list[dict[str, Any]]]


def _movie_credit_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {**credit, "movie_id": body.get("id"), "credit_type": credit_type}
        for credit_type in ("cast", "crew")
        for credit in body.get(credit_type) or []
    ]


def _tv_aggregate_credit_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    # Aggregate credits nest one entry per role (cast) or job (crew) under each person. One row per
    # role or job gives every row its own credit_id, like the movie credits table.
    rows = []
    for credit_type, nested_key in (("cast", "roles"), ("crew", "jobs")):
        for person in body.get(credit_type) or []:
            person_fields = {key: value for key, value in person.items() if key != nested_key}
            for credit in person.get(nested_key) or []:
                rows.append({**person_fields, **credit, "series_id": body.get("id"), "credit_type": credit_type})
    return rows


def _tv_season_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**season, "series_id": body.get("id")} for season in body.get("seasons") or []]


def _tv_episode_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    return list(body.get("episodes") or [])


ROW_MAPPERS: dict[str, RowMapper] = {
    "movie_credits": _movie_credit_rows,
    "tv_aggregate_credits": _tv_aggregate_credit_rows,
    "tv_seasons": _tv_season_rows,
    "tv_episodes": _tv_episode_rows,
}


def _resource(name: str) -> EndpointResource:
    config = TMDB_ENDPOINTS[name]

    if config.paginated:
        # TMDB list/trending endpoints paginate with `page` / `total_pages`; stop after the last page
        # and never request past the server-side 500-page ceiling.
        paginator: PageNumberPaginator | SinglePagePaginator = PageNumberPaginator(
            base_page=1,
            page_param="page",
            total_path="total_pages",
            maximum_page=MAX_PAGES,
        )
        # Only paginated requests carry `language`; the reference endpoints omit it, matching the
        # previous hand-rolled URL builder exactly.
        params: dict[str, Any] = {"language": "en-US", **config.params}
    else:
        paginator = SinglePagePaginator()
        params = dict(config.params)

    for path_param, parent_field in config.resolve_fields.items():
        params[path_param] = {"type": "resolve", "resource": config.parent, "field": parent_field}

    endpoint: Endpoint = {
        "path": config.path,
        "params": params,
        # None for the bare-list configuration endpoints (languages/countries) and the per-title
        # objects; "results" or "genres" otherwise. Not marked required: a malformed body degrades
        # to empty rows rather than failing loud, matching the previous behavior.
        "data_selector": config.data_key,
        "paginator": paginator,
    }
    if config.parent is not None:
        # A title can leave the catalog between the discover listing and its own request.
        endpoint["response_actions"] = [{"status_code": 404, "action": "ignore"}]

    resource: EndpointResource = {"name": name, "endpoint": endpoint}
    row_mapper = ROW_MAPPERS.get(name)
    if row_mapper is not None:
        resource["data_map"] = row_mapper
    return resource


def _resource_chain(endpoint: str) -> list[EndpointResource]:
    """The endpoint and every parent it fans out over, root first."""
    chain: list[EndpointResource] = []
    name: Optional[str] = endpoint
    while name is not None:
        chain.insert(0, _resource(name))
        name = TMDB_ENDPOINTS[name].parent
    return chain


def _fanout_depth(endpoint: str) -> int:
    depth = 0
    parent = TMDB_ENDPOINTS[endpoint].parent
    while parent is not None:
        depth += 1
        parent = TMDB_ENDPOINTS[parent].parent
    return depth


def endpoint_supports_resume(endpoint: str) -> bool:
    # The framework cannot checkpoint a fan-out of two or more levels (tv_episodes), so a retry of
    # that table starts again from the first title.
    return _fanout_depth(endpoint) <= 1


def tmdb_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TMDbResumeConfig],
) -> SourceResponse:
    config = TMDB_ENDPOINTS[endpoint]
    resources = _resource_chain(endpoint)
    fanout_depth = len(resources) - 1
    supports_resume = endpoint_supports_resume(endpoint)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TMDB_BASE_URL,
            "headers": {"Accept": "application/json"},
            # The api_key rides in the query string; framework auth redacts it from every raised error
            # message (raise_for_status, HTTP {status} for {url}) so it can't leak into job errors.
            "auth": {"type": "api_key", "api_key": api_key, "name": "api_key", "location": "query"},
        },
        "resource_defaults": {},
        "resources": [*resources],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if supports_resume and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if fanout_depth == 0 and config.paginated and resume.next_page is not None:
                initial_paginator_state = {"page": resume.next_page}
            elif fanout_depth == 1 and (resume.completed or resume.current):
                initial_paginator_state = {
                    "completed": resume.completed or [],
                    "current": resume.current,
                    "child_state": resume.child_state,
                }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if not state:
            return
        if fanout_depth == 1:
            resumable_source_manager.save_state(
                TMDbResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        elif state.get("page") is not None:
            resumable_source_manager.save_state(TMDbResumeConfig(next_page=int(state["page"])))

    built = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,  # every TMDB endpoint is full refresh — no server-side updated-after filter
        resume_hook=save_checkpoint if supports_resume else None,
        initial_paginator_state=initial_paginator_state,
    )
    resource = next(r for r in built if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        supports_resume=supports_resume,
        # Full refresh (replace) on small, bounded ranking/reference datasets whose date fields can be
        # empty, so datetime partitioning isn't worthwhile here.
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # /configuration is a cheap call that 200s for any valid key and 401s for an invalid one. Only a
    # 401 means the key is wrong — a transient failure (5xx, network error, timeout) must not be
    # reported as an invalid key, or a user with a perfectly valid key during a brief TMDB outage
    # would be told to regenerate it.
    url = f"{TMDB_BASE_URL}/configuration?{urlencode({'api_key': api_key})}"
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Accept": "application/json"},
    )
    if ok:
        return True, None
    if status is None:
        return False, "Could not reach TMDB to validate your API key. Check your connection and try again."
    if status == 401:
        return False, "Invalid TMDB API key"
    return (
        False,
        f"TMDB returned an unexpected response (status {status}) while validating your API key. Please try again.",
    )
