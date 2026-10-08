import dataclasses
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import urlencode

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.settings import (
    GRANOLA_ENDPOINTS,
    PAGE_SIZE,
    GranolaEndpointConfig,
)

GRANOLA_BASE_URL = "https://public-api.granola.ai"


@dataclasses.dataclass(frozen=True)
class GranolaResumeConfig:
    # Full, self-contained next-page URL (base + filters + cursor) so a resume can GET it directly.
    next_url: str | None = None
    # Fan-out endpoints resume by parent: the parent paths already fully synced, the parent in
    # progress, and that parent's paginator state.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


class GranolaCursorPaginator(BaseNextUrlPaginator):
    """Cursor pagination gated on BOTH ``hasMore`` and ``cursor`` in the response body.

    Granola returns an opaque ``cursor`` plus a ``hasMore`` flag; a page only has a successor when
    both are truthy. The built-in cursor paginator keys off the cursor alone, so this small subclass
    reproduces the exact stop condition. It builds a self-contained next-page URL (base + page_size +
    incremental filter + cursor) via the injected builder, which keeps the resume state a single
    ``next_url`` string — the same shape the hand-rolled source persisted.
    """

    def __init__(self, next_url_builder: Callable[[str], str]) -> None:
        super().__init__()
        self._next_url_builder = next_url_builder

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = {}
        if isinstance(body, dict) and body.get("hasMore") and body.get("cursor"):
            self._next_url = self._next_url_builder(body["cursor"])
            self._has_next_page = True
        else:
            self._has_next_page = False


class GranolaTranscriptPaginator(JSONResponseCursorPaginator):
    """Body-cursor pagination for a single note's transcript, with the same ``hasMore`` gate."""

    def __init__(self) -> None:
        # A cursor that does not advance would re-request the same page until the activity times out.
        super().__init__(cursor_path="cursor", cursor_param="cursor", raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        try:
            body = response.json()
        except Exception:
            body = {}
        if not (isinstance(body, dict) and body.get("hasMore")):
            self._has_next_page = False


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 UTC timestamp with a Z suffix."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_initial_params(
    config: GranolaEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"page_size": PAGE_SIZE}

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # Honour the user's chosen cursor field, falling back to the first advertised field.
        field_name = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
        query_param = config.incremental_query_params.get(field_name) if field_name else None
        if query_param:
            params[query_param] = _format_timestamp(db_incremental_field_last_value)

    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{GRANOLA_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the endpoint matching the schema being validated to confirm the API key is genuine.

    A 401 means the key is missing or invalid. A 403 means a valid key without the scope
    for this endpoint - accepted at source-create (schema_name is None) since users may only
    grant the scopes for the streams they want to sync. Probing the schema's own path means a
    scope-limited key (e.g. folders-only) isn't rejected by an unrelated stream's probe.
    """
    endpoint = GRANOLA_ENDPOINTS.get(schema_name) if schema_name else None
    if endpoint is not None and endpoint.fanout is not None:
        # A fan-out child's path needs a parent id, and its rows come from the parent's notes.
        endpoint = GRANOLA_ENDPOINTS[endpoint.fanout.parent_name]
    path = endpoint.path if endpoint else GRANOLA_ENDPOINTS["notes"].path
    url = _build_url(path, {"page_size": 1})

    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers=_get_headers(api_key),
    )

    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Granola API key"
    if status == 403 and schema_name is None:
        return True, None
    if status == 403:
        return False, "Your Granola API key does not have access to this data"
    if status is None:
        return False, "Could not reach the Granola API. Please try again."

    return False, f"Granola API returned an unexpected status code: {status}"


def _source_response(config: GranolaEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        # Granola's list endpoints have no sort parameter, so within-page ordering is
        # undefined. "desc" here is the pipeline's "commit the incremental watermark only
        # after every page has been processed" mode - with undefined ordering we must not
        # advance the watermark per-batch (that could persist a high value early and skip
        # older, not-yet-fetched rows on the next run's server-side `*_after` filter).
        # Pagination is driven entirely by the opaque cursor, so we don't rely on ordering
        # or on `db_incremental_field_earliest_value` to scroll; merge dedupes on `id`.
        sort_mode="desc",
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _fanout_source(
    config: GranolaEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GranolaResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = GRANOLA_ENDPOINTS[config.fanout.parent_name]
    parent_params: dict[str, Any] = {"page_size": parent_config.page_size}

    client_config: ClientConfig = {
        "base_url": GRANOLA_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "paginator": GranolaCursorPaginator(
            lambda cursor: _build_url(parent_config.path, {**parent_params, "cursor": cursor})
        ),
    }

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                GranolaResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=GRANOLA_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra={"data_selector": parent_config.data_key},
            child_endpoint_extra={"data_selector": config.data_key, "paginator": GranolaTranscriptPaginator()},
            page_size_param="page_size",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    return _source_response(config, lambda: resource)


def granola_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GranolaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = GRANOLA_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(config, api_key, team_id, job_id, resumable_source_manager)

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    def build_next_url(cursor: str) -> str:
        # Self-contained next-page URL carrying page_size + any incremental filter + cursor.
        return _build_url(config.path, {**params, "cursor": cursor})

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": GRANOLA_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and raised errors; only the non-secret accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": GranolaCursorPaginator(build_next_url),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # The list lives under a wrapper key (e.g. {"notes": [...]}). A missing key is
                    # treated as an empty page (not a hard error), matching the hand-rolled source.
                    "data_selector": config.data_key,
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on id) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(GranolaResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Incremental filtering is applied as a computed static query param above, so the framework
        # has no server-side cursor param to inject.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, lambda: resource)
