"""Eventzilla transport layer.

Eventzilla is an event-ticketing platform. Auth is an account API key sent in an ``x-api-key``
header. Every resource lives under ``https://www.eventzillaapi.net/api/v2``.

List endpoints paginate with ``limit``/``offset`` and carry a ``pagination`` object
(``{offset, limit, total}``) that signals whether more pages remain: the offset-paged endpoints
(events, users, transactions) return it, while endpoints that return their whole result set in one
response (categories, tickets, and the per-event attendees/tickets samples) omit it. The events,
categories and users lists are top-level; attendees, transactions and tickets fan out over every
event (``/events/{event_id}/...``) and each child row is stamped with its parent ``event_id``.

Eventzilla exposes no server-side updated-since filter on any endpoint, so every table is full
refresh only.

Built on the shared ``rest_source`` framework: a small custom offset paginator reproduces the
``pagination``-envelope termination and advances by the real returned count (so a clamped page size
can't skip rows), framework ``api_key`` auth carries the key in ``x-api-key`` (and redacts it from
errors/logs), and event-scoped resources are single-hop dependent resources fanning out from the
events list. A child ``404`` (event deleted between enumeration and fetch) is ignored so the sync
skips it rather than failing.
"""

import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.settings import EVENTZILLA_ENDPOINTS

EVENTZILLA_BASE_URL = "https://www.eventzillaapi.net/api/v2"

# Documented default limit is 20; we request a larger page to cut request count. The offset advances
# by the number of rows actually returned (never a fixed step), so a server that silently clamps the
# page size can't cause us to skip rows.
PAGE_SIZE = 100

# Safety ceiling on pages per list to bound a runaway paginator (e.g. an endpoint that ignores
# offset). Real lists terminate far below this on an empty page or their reported total.
MAX_PAGES = 10_000

# ``include_from_parent=["id"]`` copies the parent event's id onto child rows under this
# framework-derived name; we rename it to the stable ``event_id`` column below.
_PARENT_EVENT_ID_KEY = "_events_id"


@dataclasses.dataclass
class EventzillaResumeConfig:
    # Offset of the next page to fetch within the current top-level list.
    offset: int = 0
    # Legacy field: the event-id bookmark the hand-rolled fan-out used. Kept (with a default) so an
    # old saved state still parses; the framework fan-out now checkpoints via ``fanout_state``.
    event_id: str | None = None
    # Framework dependent-resource checkpoint for event fan-out endpoints
    # (``{"completed": [...], "current": ..., "child_state": ...}``). Defaults to None so an old
    # ``{"offset": ..., "event_id": ...}`` state still parses after this change.
    fanout_state: Optional[dict[str, Any]] = None


class EventzillaOffsetPaginator(BasePaginator):
    """Limit/offset paginator matching Eventzilla's ``pagination`` envelope.

    Advances the offset by the number of rows actually returned (never a fixed step) so a server that
    clamps the requested page size can't cause us to skip rows. The response ``pagination`` object is
    the paginate signal: offset-paged endpoints return it and we advance until ``total`` is reached
    (or an empty page); endpoints that return their whole result set in one response omit it, so we
    stop after the first page rather than blindly re-requesting.
    """

    def __init__(self, limit: int = PAGE_SIZE, offset: int = 0) -> None:
        super().__init__()
        self.limit = limit
        self.offset = offset
        self._pages = 0

    def _apply(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["offset"] = self.offset
        request.params["limit"] = self.limit

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        self.offset += len(data)

        self._pages += 1
        if self._pages >= MAX_PAGES:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except Exception:
            body = None

        pagination = body.get("pagination") if isinstance(body, dict) else None
        if not isinstance(pagination, dict):
            # No pagination object: the endpoint returned its full result set in one response, so a
            # second request would re-read the same rows (or loop forever on an offset-ignoring list).
            self._has_next_page = False
            return

        total = pagination.get("total")
        if total is not None and self.offset >= total:
            self._has_next_page = False
            return

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset already points at the next page to fetch (update_state advanced it).
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"EventzillaOffsetPaginator(offset={self.offset}, limit={self.limit})"


def _get_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


def _client_config(api_key: str) -> ClientConfig:
    # Auth is supplied via the framework ``api_key`` config (header ``x-api-key``) so the value is
    # redacted from logs and raised error messages; only the non-secret Accept header is set here.
    return {
        "base_url": EVENTZILLA_BASE_URL,
        "auth": {
            "type": "api_key",
            "api_key": api_key,
            "name": "x-api-key",
            "location": "header",
        },
        "headers": {"Accept": "application/json"},
        "paginator": EventzillaOffsetPaginator(limit=PAGE_SIZE),
    }


def _stamp_event_id(row: dict[str, Any]) -> dict[str, Any]:
    # ``include_from_parent=["id"]`` copies the parent event id under ``_events_id``; rename it to the
    # stable ``event_id`` column (as a string, exactly as the hand-rolled fan-out stamped it) so the
    # composite primary keys stay table-wide unique.
    row["event_id"] = str(row.pop(_PARENT_EVENT_ID_KEY))
    return row


def eventzilla_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[EventzillaResumeConfig],
) -> SourceResponse:
    config = EVENTZILLA_ENDPOINTS[endpoint]
    client = _client_config(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-fetches the last page (merge dedupes on the PK)
        # rather than skipping it.
        if not state:
            return
        if "offset" in state:
            resumable_source_manager.save_state(EventzillaResumeConfig(offset=int(state["offset"])))
        else:
            resumable_source_manager.save_state(EventzillaResumeConfig(fanout_state=state))

    resource: Resource
    if not config.fan_out_over_events:
        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume is not None and resume.offset:
            initial_paginator_state = {"offset": resume.offset}

        rest_config: RESTAPIConfig = {
            "client": client,
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {"path": config.path, "data_selector": config.data_key},
                }
            ],
        }
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
    else:
        # Event fan-out: discover every event, then paginate the child endpoint per event, stamping
        # each row with its parent event id (single-hop dependent resource, resume enabled). A child
        # 404 (event deleted between enumeration and fetch) is ignored so the sync skips it.
        fanout_initial: Optional[dict[str, Any]] = resume.fanout_state if resume is not None else None

        events_resource: EndpointResource = {
            "name": "events",
            "endpoint": {"path": "/events", "data_selector": "events"},
        }
        child_endpoint: Endpoint = {
            "path": config.path,
            "data_selector": config.data_key,
            "params": {"event_id": {"type": "resolve", "resource": "events", "field": "id"}},
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        }
        child_resource: EndpointResource = {
            "name": endpoint,
            "endpoint": child_endpoint,
            "include_from_parent": ["id"],
            "data_map": _stamp_event_id,
        }

        rest_config = {"client": client, "resources": [events_resource, child_resource]}
        built = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=fanout_initial,
        )
        resource = next(r for r in built if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe against the events list confirms the key is genuine without touching any
    # per-event resource (the user may not have events yet).
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{EVENTZILLA_BASE_URL}/events?offset=0&limit={PAGE_SIZE}",
        headers=_get_headers(api_key),
    )
    return ok
