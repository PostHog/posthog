import dataclasses
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    ClientConfig,
    Endpoint,
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.settings import (
    TRELLO_ENDPOINTS,
    TrelloEndpointConfig,
)

TRELLO_BASE_URL = "https://api.trello.com/1"


@dataclasses.dataclass
class TrelloResumeConfig:
    # Legacy resume fields kept (with defaults) so state saved by the old transport still parses via
    # ``dataclass(**saved)``. A resumed run that only carries these starts the fan-out fresh.
    board_index: int = 0
    before_cursor: str | None = None
    # Fan-out resume state as produced by the rest_source dependent-resource resume hook:
    # ``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}``.
    fanout_state: dict | None = None


def _get_headers(api_key: str, api_token: str) -> dict[str, str]:
    # Header auth keeps the secret token out of request URLs (and therefore out of
    # our tracked-session request logs), unlike Trello's ?key=&token= query params.
    return {"Authorization": f'OAuth oauth_consumer_key="{api_key}", oauth_token="{api_token}"'}


def _id_to_created_at(obj_id: Any) -> str | None:
    """Derive a creation timestamp from a Trello ObjectID.

    Trello IDs are MongoDB ObjectIDs whose first 8 hex chars encode the Unix
    creation time. Most Trello objects expose no creation timestamp of their own,
    so we surface this as a stable ``created_at`` for partitioning.
    """
    if not isinstance(obj_id, str) or len(obj_id) < 8:
        return None
    try:
        timestamp = int(obj_id[:8], 16)
    except ValueError:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _add_created_at(item: dict[str, Any]) -> dict[str, Any]:
    if "created_at" not in item:
        created_at = _id_to_created_at(item.get("id"))
        if created_at is not None:
            item["created_at"] = created_at
    return item


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 string for Trello's ``since`` filter."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


class TrelloActionsPaginator(BasePaginator):
    """Pages a board's actions newest-first via the ``before`` cursor.

    Trello returns actions newest-first and offers no forward cursor, so each page's
    oldest action id (the last row) becomes the ``before`` bound for the next, older
    page. Pagination stops on an empty page, a short page (fewer than ``limit`` rows),
    or a page whose last row carries no id.
    """

    def __init__(self, limit: int, before: str | None = None) -> None:
        super().__init__()
        self.limit = limit
        self._before = before

    def _apply(self, request: Request) -> None:
        if self._before is not None:
            if request.params is None:
                request.params = {}
            request.params["before"] = self._before

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        last = data[-1]
        oldest_id = last.get("id") if isinstance(last, dict) else None
        if oldest_id is None or len(data) < self.limit:
            self._has_next_page = False
            return
        self._before = oldest_id
        self._has_next_page = True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"before": self._before} if self._has_next_page and self._before is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        before = state.get("before")
        if before is not None:
            self._before = before
            self._has_next_page = True


def validate_credentials(api_key: str, api_token: str) -> tuple[bool, str | None]:
    url = f"{TRELLO_BASE_URL}/members/me"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key, api_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None

    # Trello answers a missing/invalid token with 400 ("invalid token") and an
    # invalid key with 401 ("invalid key"); both mean the credentials are bad.
    if response.status_code in (400, 401):
        return False, "Invalid Trello API key or token"
    if response.status_code == 403:
        return False, "Your Trello token does not have the required permissions"

    return False, response.text or f"Trello API returned status {response.status_code}"


def _client_config(api_key: str, api_token: str) -> ClientConfig:
    # Framework auth carries the composite OAuth header so its value is redacted from logs and
    # raised errors; only non-secret headers would go in ``headers`` (Trello needs none).
    return {
        "base_url": TRELLO_BASE_URL,
        "auth": {
            "type": "api_key",
            "api_key": _get_headers(api_key, api_token)["Authorization"],
            "name": "Authorization",
            "location": "header",
        },
    }


def _member_resource(config: TrelloEndpointConfig, client_config: ClientConfig, team_id: int, job_id: str) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": config.page_size},
                    "paginator": SinglePagePaginator(),
                    # A 200 whose body isn't a list means the response shape changed — fail loud
                    # instead of wrapping the stray object as a single row.
                    "data_selector_required": True,
                },
                "data_map": _add_created_at,
            }
        ],
    }
    # Member endpoints are a single request; no resume checkpoints.
    return rest_api_resource(rest_config, team_id, job_id, None)


def _board_resource(
    config: TrelloEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[TrelloResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    child_paginator: BasePaginator = (
        TrelloActionsPaginator(limit=config.page_size) if config.paginated else SinglePagePaginator()
    )

    child_endpoint: Endpoint = {
        "path": f"/boards/{{board_id}}/{config.path}",
        "params": {
            "board_id": {"type": "resolve", "resource": "boards", "field": "id"},
            "limit": config.page_size,
        },
        "paginator": child_paginator,
        "data_selector_required": True,
    }
    # Only ``actions`` has a server-side ``since`` filter, and only on an incremental run with a
    # watermark; a full refresh (last_value is None) omits it.
    if config.paginated and db_incremental_field_last_value is not None:
        child_endpoint["incremental"] = {
            "start_param": "since",
            "cursor_path": config.default_incremental_field or "date",
            "convert": _format_incremental_value,
        }

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": "boards",
                "endpoint": {
                    # Only ids are needed to fan out; the full board objects sync via the `boards` schema.
                    "path": "/members/me/boards",
                    "params": {"fields": "id"},
                    "paginator": SinglePagePaginator(),
                },
            },
            {
                "name": config.name,
                "endpoint": child_endpoint,
                "include_from_parent": [],
                "data_map": _add_created_at,
            },
        ],
    }

    initial_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework emits fan-out progress after each parent page and parent completion; persist
        # it into our dataclass. ``None`` only when the whole fan-out is done — nothing left to save.
        if state is not None:
            manager.save_state(TrelloResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return next(r for r in resources if r.name == config.name)


def trello_source(
    api_key: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TrelloResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TRELLO_ENDPOINTS[endpoint]
    client_config = _client_config(api_key, api_token)

    if config.scope == "member":
        resource = _member_resource(config, client_config, team_id, job_id)
    else:
        resource = _board_resource(
            config, client_config, team_id, job_id, resumable_source_manager, db_incremental_field_last_value
        )

    items: Iterable[Any] = resource
    return SourceResponse(
        name=endpoint,
        items=lambda: items,
        primary_keys=[config.primary_key],
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
