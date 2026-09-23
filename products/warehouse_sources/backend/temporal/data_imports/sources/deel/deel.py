from collections.abc import Iterable, Iterator
from functools import partial
from typing import Any, Optional, cast

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.settings import (
    DEEL_ENDPOINTS,
    TIME_OFF_EVENTS_ENDPOINT,
    TIME_OFF_EVENTS_PARENT,
    DeelEndpointConfig,
)

DEEL_BASE_URL = "https://api.letsdeel.com/rest/v2"
REQUEST_TIMEOUT_SECONDS = 30

# Time-off rows carry absence reasons and family/medical event details, and timesheets carry a
# free-text work description plus a reviewer's remarks — none of it name-tagged in a way the
# name-based sample scrubbers can spot.
_UNCAPTURED_ENDPOINTS = frozenset({"time_offs", TIME_OFF_EVENTS_ENDPOINT, "timesheets"})


@frozen
class DeelResumeConfig:
    # Offset-paginated endpoints persist the offset; the keyset endpoints persist Deel's opaque
    # next-page cursor instead.
    offset: Optional[int] = None
    cursor: Optional[str] = None
    # Fan-out endpoints resume per parent — see
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: Optional[list[str]] = None
    current: Optional[str] = None
    child_state: Optional[dict[str, Any]] = None


def _find(body: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(body, dict):
            return None
        body = body.get(key)
    return body


class DeelCursorPaginator(BasePaginator):
    """Keyset paginator for Deel's cursor endpoints.

    The next cursor's body path and the query param that sends it back vary per endpoint.
    Terminate when the response carries no next cursor, publishes a false "has more" flag,
    returns no rows, OR echoes back the same cursor it was just sent — Deel can return a stale
    or unchanged cursor on an exhausted keyset while still claiming more pages exist, so both
    an empty page and a repeated cursor must stop the walk rather than loop forever.
    """

    def __init__(
        self,
        cursor_param: str = "after_cursor",
        cursor_path: tuple[str, ...] = ("page", "cursor"),
        has_more_path: Optional[tuple[str, ...]] = None,
    ) -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self.cursor_path = cursor_path
        self.has_more_path = has_more_path
        self._cursor: Optional[str] = None

    def _inject(self, request: Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor

    def init_request(self, request: Request) -> None:
        # Applies a seeded resume cursor to the first request.
        self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        try:
            body = response.json()
        except Exception:
            self._has_next_page = False
            return
        if self.has_more_path is not None and not _find(body, self.has_more_path):
            self._has_next_page = False
            return
        next_cursor = _find(body, self.cursor_path)
        if next_cursor and str(next_cursor) != self._cursor:
            self._cursor = str(next_cursor)
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


def _make_paginator(config: DeelEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        return DeelCursorPaginator(
            cursor_param=config.cursor_param,
            cursor_path=config.cursor_path,
            has_more_path=config.has_more_path,
        )
    if config.pagination == "offset":
        # OffsetPaginator injects both limit and offset; termination is a short/empty page
        # (Deel exposes no dependable top-level total).
        return OffsetPaginator(limit=config.page_size, total_path=None)
    return SinglePagePaginator()


def _client_config(api_token: str, config: DeelEndpointConfig) -> ClientConfig:
    client_config: ClientConfig = {
        "base_url": DEEL_BASE_URL,
        # Bearer auth via the framework so the token is redacted from logs.
        "auth": {"type": "bearer", "token": api_token},
    }
    if config.name in _UNCAPTURED_ENDPOINTS:
        client_config["capture"] = False
    return client_config


def _base_params(config: DeelEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.params)
    # The offset paginator injects its own limit; the cursor endpoints need it sent up front.
    if config.pagination == "cursor" and config.page_size_param is not None:
        params[config.page_size_param] = config.page_size
    return params


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the API token is valid with a cheap one-person listing probe.

    Scoped tokens may lack individual resource scopes (403); only 401 means the
    token itself is bad. A transient network failure surfaces as a distinct
    "could not reach Deel" error so it isn't mistaken for a bad token."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{DEEL_BASE_URL}/people?limit=1",
        headers={"Authorization": f"Bearer {api_token}"},
    )

    if status is None:
        return False, "Could not reach Deel"
    if status == 401:
        return False, "Invalid Deel API token"
    return True, None


def _top_level_items(
    config: DeelEndpointConfig,
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DeelResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterable[Any]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None:
        if config.pagination == "cursor" and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}
        elif config.pagination == "offset" and resume.offset is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes) rather than skipping it.
        if not state:
            return
        if config.pagination == "cursor" and state.get("cursor") is not None:
            resumable_source_manager.save_state(DeelResumeConfig(cursor=str(state["cursor"])))
        elif config.pagination == "offset" and state.get("offset") is not None:
            resumable_source_manager.save_state(DeelResumeConfig(offset=int(state["offset"])))

    client_config = _client_config(api_token, config)
    client_config["paginator"] = _make_paginator(config)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": _base_params(config),
                    # A missing `data` key is treated as an empty page (lenient), matching the
                    # hand-rolled `body.get("data", [])` — not a fail-loud like other sources.
                    "data_selector": config.data_selector,
                },
            }
        ],
    }

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_items(
    config: DeelEndpointConfig,
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DeelResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterable[Any]:
    fanout = config.fanout
    assert fanout is not None
    parent_config = DEEL_ENDPOINTS[fanout.parent_name]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_state: Optional[dict[str, Any]] = None
    if resume is not None and (resume.completed or resume.current):
        initial_state = {
            "completed": resume.completed or [],
            "current": resume.current,
            "child_state": resume.child_state,
        }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                DeelResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    parent_endpoint: Endpoint = {
        "paginator": _make_paginator(parent_config),
        "data_selector": parent_config.data_selector,
    }
    child_endpoint: Endpoint = {
        "paginator": _make_paginator(config),
        "data_selector": config.data_selector,
    }

    return cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=DEEL_ENDPOINTS,
            child_endpoint=config.name,
            fanout=fanout,
            client_config=_client_config(api_token, config),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            # Both hops take their page size from fanout.parent_params, or none at all.
            page_size_param=None,
            parent_endpoint_extra=parent_endpoint,
            child_endpoint_extra=child_endpoint,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )


def _time_off_event_items(
    config: DeelEndpointConfig,
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DeelResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Yield one batch of time-off event rows per page of people.

    Hand-rolled rather than a dependent resource because Deel takes the worker profile as a query
    param, and the shared fan-out helper binds path params only.
    """
    parent_config = DEEL_ENDPOINTS[TIME_OFF_EVENTS_PARENT]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state = {"offset": resume.offset} if resume is not None and resume.offset is not None else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The hook runs when this generator asks for the next page, so after its rows are out.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(DeelResumeConfig(offset=int(state["offset"])))

    parent_client_config = _client_config(api_token, parent_config)
    parent_client_config["paginator"] = _make_paginator(parent_config)

    parent_rest_config: RESTAPIConfig = {
        "client": parent_client_config,
        "resources": [
            {
                "name": TIME_OFF_EVENTS_PARENT,
                "endpoint": {
                    "path": parent_config.path,
                    "params": _base_params(parent_config),
                    "data_selector": parent_config.data_selector,
                },
            }
        ],
    }

    people = rest_api_resource(
        parent_rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    session = make_tracked_session(redact_values=(api_token,), capture=False)
    headers = {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}

    for page in people:
        rows: list[dict[str, Any]] = []
        for person in page:
            hris_profile_id = person.get("id")
            if hris_profile_id is None:
                continue
            response = session.get(
                f"{DEEL_BASE_URL}{config.path}",
                params={"hris_profile_id": str(hris_profile_id)},
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code == 404:
                # The person went away between the listing and this fetch.
                continue
            response.raise_for_status()
            body = response.json()
            events = body.get("data") if isinstance(body, dict) else None
            for event in events or []:
                # Deel omits hris_profile_id from some event rows, and it is half the primary key.
                rows.append({**event, "hris_profile_id": event.get("hris_profile_id") or str(hris_profile_id)})
        if rows:
            yield rows


def deel_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DeelResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DEEL_ENDPOINTS[endpoint]

    items: Any
    column_hints: Optional[dict[str, Any]] = None
    if endpoint == TIME_OFF_EVENTS_ENDPOINT:
        items = partial(
            _time_off_event_items,
            config,
            api_token,
            team_id,
            job_id,
            resumable_source_manager,
        )
    else:
        builder = _fanout_items if config.fanout is not None else _top_level_items
        resource = builder(
            config,
            api_token,
            team_id,
            job_id,
            resumable_source_manager,
            db_incremental_field_last_value,
        )
        items = lambda: resource  # noqa: E731
        column_hints = getattr(resource, "column_hints", None)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=column_hints,
    )
