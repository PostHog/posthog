import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    make_parent_key_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.settings import (
    DEEPGRAM_ENDPOINTS,
    DeepgramEndpointConfig,
)

DEEPGRAM_BASE_URL = "https://api.deepgram.com/v1"

# The requests log caps `limit` at 1000; use the max to minimise round trips.
REQUESTS_PAGE_SIZE = 1000

# Parent (projects) list is the fan-out seed for every project-scoped endpoint.
_PARENT_RESOURCE = "projects"
_PARENT_ID_FIELD = "project_id"
# The framework injects the parent id under this `_<parent>_<field>` name; the child map lifts it back
# to the flat `project_id` column the tables have always exposed.
_PARENT_ID_KEY = make_parent_key_name(_PARENT_RESOURCE, _PARENT_ID_FIELD)


class DeepgramTokenAuth(AuthConfigBase):
    """Deepgram's Management API expects `Authorization: Token <key>` (not Bearer).

    Supplying it through a framework auth object (rather than a hand-built header) registers the key
    for value-based log redaction, so a failed or sampled request never persists the customer's secret.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"Token {self.api_key}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.api_key,) if self.api_key else ()


class DeepgramRequestsPaginator(PageNumberPaginator):
    """Page/`limit` pagination over Deepgram's requests log (0-indexed `page`).

    The requests log reports no total count, so — like the hand-rolled loop this replaces — a page
    shorter than the requested `limit` (or an empty page) is the last page. Stopping on a short page
    avoids the extra empty-page request the plain ``PageNumberPaginator`` would pay.
    """

    def __init__(self) -> None:
        super().__init__(base_page=0, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < REQUESTS_PAGE_SIZE:
            self._has_next_page = False


@dataclasses.dataclass
class DeepgramResumeConfig:
    # Opaque paginator/fan-out state handed back by the rest_source framework (per-parent completed-path
    # progress plus the in-progress project's requests-log page). Retained as a single blob so the shape
    # can evolve without a state-format migration.
    fanout_state: dict[str, Any] | None = None
    # Legacy fields from the hand-rolled resume format. Kept (with defaults) so an old saved state still
    # parses via ``dataclass(**saved)``; a run resumed from one starts fan-out fresh (a re-read the merge
    # dedupes) rather than mis-mapping the old positional scope onto the new state.
    project_id: str | None = None
    page: int | None = None


def _format_start_value(value: Any) -> str:
    """Format an incremental cursor value for Deepgram's `start` filter.

    Deepgram accepts YYYY-MM-DD or ISO 8601; we send full ISO 8601 with a Z suffix. Future-dated
    cursors are capped at now so we never build a start-in-the-future filter (harmless but pointless).
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        aware = now if aware > now else aware
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        capped = now.date() if value > now.date() else value
        return capped.isoformat()
    return str(value)


def _redact_url_userinfo(url: str) -> str:
    """Strip embedded userinfo (`user:pass@`) from a URL.

    Deepgram callback URLs can carry Basic Auth credentials in the userinfo component; those must not
    land in the warehouse where anyone with query access could read them. The host/path is preserved
    so the row still records which callback was used.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if "@" not in parts.netloc:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit(parts._replace(netloc=host))


def _make_child_map(config: DeepgramEndpointConfig) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Per-row transform for a fanned-out (project-scoped) endpoint.

    Reproduces the old ``_transform_row``: flatten a nested sub-object into the row root, lift the
    framework's parent-id key back to the flat ``project_id`` column, redact any callback credentials,
    and fail loud on a row missing a required primary key.
    """

    def _map(row: dict[str, Any]) -> dict[str, Any]:
        if config.flatten_key and isinstance(row.get(config.flatten_key), dict):
            nested = row.pop(config.flatten_key)
            row = {**row, **nested}
        # Fan-out rows carry the parent project's id so the composite primary key stays unique table-wide.
        if _PARENT_ID_KEY in row:
            row[_PARENT_ID_FIELD] = row.pop(_PARENT_ID_KEY)
        # Request-log rows can echo the callback URL, which may embed Basic Auth credentials.
        if isinstance(row.get("callback"), str):
            row["callback"] = _redact_url_userinfo(row["callback"])
        # A row missing a required primary-key field would let the delta merge build a partial predicate
        # and overwrite unrelated rows in the same project, so fail loudly instead of emitting it.
        for primary_key in config.primary_keys:
            if row.get(primary_key) is None:
                raise ValueError(f"Deepgram {config.name} row missing required primary key '{primary_key}'")
        return row

    return _map


def _incremental_config(
    should_use_incremental_field: bool, db_incremental_field_last_value: Any
) -> IncrementalConfig | None:
    """Server-side `start` filter for the requests log, only when we have a cursor to filter on.

    Mirrors the old behaviour: no filter on a first (full) sync, and the persisted watermark is
    formatted (and future-clamped) the way Deepgram's `start` expects.
    """
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return None
    return {
        "start_param": "start",
        "cursor_path": "created",
        "convert": _format_start_value,
    }


def _projects_resource() -> EndpointResource:
    # The top-level /projects list synced as its own table — yielded raw (no fan-out, no per-row
    # transform), exactly as the old is_project_list path did.
    return {
        "name": "projects",
        "endpoint": {
            "path": "/projects",
            "data_selector": "projects",
            "paginator": SinglePagePaginator(),
        },
    }


def _projects_parent_resource() -> EndpointResource:
    # The same /projects list used as the fan-out seed. The old code skipped projects with no
    # project_id; drop them here so the child resolve (which would otherwise raise) never sees an
    # id-less parent row.
    return {
        "name": "projects",
        "endpoint": {
            "path": "/projects",
            "data_selector": "projects",
            "paginator": SinglePagePaginator(),
        },
        "data_map": lambda row: [row] if row.get(_PARENT_ID_FIELD) else [],
    }


def _child_resource(
    endpoint: str, config: DeepgramEndpointConfig, incremental: IncrementalConfig | None
) -> EndpointResource:
    params: dict[str, Any] = {
        _PARENT_ID_FIELD: {"type": "resolve", "resource": _PARENT_RESOURCE, "field": _PARENT_ID_FIELD},
    }
    endpoint_config: dict[str, Any] = {
        "path": f"/projects/{{{_PARENT_ID_FIELD}}}{config.path}",
        "params": params,
        "data_selector": config.data_key,
    }
    if config.paginated:
        params["limit"] = REQUESTS_PAGE_SIZE
        endpoint_config["paginator"] = DeepgramRequestsPaginator()
    else:
        endpoint_config["paginator"] = SinglePagePaginator()
    if incremental is not None:
        endpoint_config["incremental"] = incremental
    return {
        "name": endpoint,
        "include_from_parent": [_PARENT_ID_FIELD],
        "endpoint": endpoint_config,
        "data_map": _make_child_map(config),
    }


def _resources_for(endpoint: str, incremental: IncrementalConfig | None) -> list[EndpointResource]:
    config = DEEPGRAM_ENDPOINTS[endpoint]
    if config.is_project_list:
        return [_projects_resource()]
    return [_projects_parent_resource(), _child_resource(endpoint, config, incremental)]


def deepgram_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DeepgramResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DEEPGRAM_ENDPOINTS[endpoint]
    incremental = (
        _incremental_config(should_use_incremental_field, db_incremental_field_last_value)
        if config.supports_incremental
        else None
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": DEEPGRAM_BASE_URL,
            # Auth (the Token header) is supplied via the framework auth object so its value is redacted
            # from logs; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": DeepgramTokenAuth(api_key),
        },
        "resource_defaults": {},
        "resources": _resources_for(endpoint, incremental),
    }

    initial_paginator_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge dedupes) rather than
        # skipping it. A ``None`` state means no page remains — nothing to persist.
        if state is not None:
            resumable_source_manager.save_state(DeepgramResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    resource: Resource = next(r for r in resources if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # The requests log's default order isn't documented and can't be curl-verified without a live
        # token, so we use "desc": the pipeline finalises the incremental watermark (max `created`) only
        # at job end rather than checkpointing per batch, which stays correct regardless of the actual
        # arrival order. The `start` filter still bounds each incremental sync server-side, so this is
        # not a re-fetch-all-history situation. Full-refresh endpoints keep the default "asc".
        sort_mode="desc" if config.supports_incremental else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    # Listing projects is the cheapest probe that proves the token is genuine; it is also the seed for
    # every other (project-scoped) endpoint, so a token that can't list projects can't sync anything.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{DEEPGRAM_BASE_URL}/projects",
        headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
    )
    return ok
