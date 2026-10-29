import dataclasses
from collections.abc import Iterable, Iterator
from typing import Any, Optional, cast

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.settings import (
    HUMANITIX_ENDPOINTS,
    PAGE_SIZE,
    HumanitixEndpointConfig,
)

HUMANITIX_BASE_URL = "https://api.humanitix.com/v1"
# Cheap endpoint used to confirm the API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/events"


@dataclasses.dataclass(frozen=True)
class HumanitixResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `_id`.
    next_page: int = 1
    # Fan-out endpoints (orders, tickets) resume by parent event: the child paths already fully
    # synced, the one in progress, and its paginator state — see
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    # Check-in counts reuse `next_page` for the events page and `completed` for the
    # `<eventId>:<eventDateId>` keys already fetched on it.
    completed: Optional[list[str]] = None
    current: Optional[str] = None
    child_state: Optional[dict[str, Any]] = None


class HumanitixPaginator(BasePaginator):
    """Page-number pagination over the Humanitix `{total, page, pageSize, <list_key>[]}` envelope.

    Terminates on a short/empty page, or once the pages fetched cover the reported item ``total`` —
    the latter saving the extra empty-page request the built-in `PageNumberPaginator` would pay when
    the total is an exact multiple of the page size. Resumable: the saved page seeds the first request.
    """

    def __init__(self, page_size: int, page: int = 1) -> None:
        super().__init__()
        self.page_size = page_size
        self.page = page

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        # A short/empty page is the last page — no further rows to fetch.
        if len(items) < self.page_size:
            self._has_next_page = False
            return

        # A full page whose running count already covers the reported total ends the sync without
        # paying for an extra empty page. `self.page` is still the page just fetched here.
        try:
            total = response.json().get("total")
        except Exception:
            total = None
        if isinstance(total, int) and self.page * self.page_size >= total:
            self._has_next_page = False
            return

        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"next_page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_page = state.get("next_page")
        if next_page is not None:
            self.page = int(next_page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"HumanitixPaginator(page={self.page})"


def _headers() -> dict[str, str]:
    # Auth (the `x-api-key` header) is supplied via the framework auth config so its value is redacted
    # from logs and raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": HUMANITIX_BASE_URL,
        "headers": _headers(),
        "auth": {"type": "api_key", "api_key": api_key, "name": "x-api-key", "location": "header"},
        "paginator": HumanitixPaginator(page_size=PAGE_SIZE),
        # Orders and tickets carry attendee details and free-form checkout answers (`additionalFields`)
        # that the name-based sample scrubbers can't recognise, so keep bodies out of sample capture.
        "capture": False,
    }


# An event or event date can be deleted between the events listing and the check-in request.
_IGNORE_NOT_FOUND = create_response_hooks([{"status_code": 404, "action": "ignore"}], resource_name="humanitix")


def _rest_client(api_key: str) -> RESTClient:
    return RESTClient(
        base_url=HUMANITIX_BASE_URL,
        headers=_headers(),
        auth=APIKeyAuth(api_key=api_key, name="x-api-key", location="header"),
        allowed_hosts=[],
        allow_redirects=False,
        capture=False,
    )


@frozen
class _EventDateKey:
    event_id: str
    date_id: str

    @property
    def marker(self) -> str:
        return f"{self.event_id}:{self.date_id}"


def _event_date_keys(events: list[Any]) -> list[_EventDateKey]:
    keys: list[_EventDateKey] = []
    for event in events:
        for date in event.get("dates") or []:
            if date.get("_id") and not date.get("deleted"):
                keys.append(_EventDateKey(event_id=event["_id"], date_id=date["_id"]))
    return keys


def _check_in_count_rows(
    config: HumanitixEndpointConfig,
    api_key: str,
    resumable_source_manager: ResumableSourceManager[HumanitixResumeConfig],
) -> Iterator[dict[str, Any]]:
    client = _rest_client(api_key)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    # Full refresh appends without dedupe, so skip exactly the dates already fetched, even if the page changed.
    done = list(resume.completed or []) if resume else []

    for events in client.paginate(
        path="/events",
        params={"pageSize": PAGE_SIZE},
        paginator=HumanitixPaginator(page_size=PAGE_SIZE, page=page),
        data_selector="events",
        data_selector_required=True,
    ):
        completed = done
        skip = set(done)
        for key in _event_date_keys(events):
            event_id, date_id, marker = key.event_id, key.date_id, key.marker
            if marker in skip:
                continue
            body: Optional[dict[str, Any]] = None
            responded = False
            for result in client.paginate(
                path=config.path.format(eventId=event_id),
                params={"eventDateId": date_id},
                paginator=SinglePagePaginator(),
                hooks=_IGNORE_NOT_FOUND,
            ):
                responded = True
                if result and isinstance(result[0], dict):
                    body = result[0]
            # Only a 404 (no response) means the date is gone; any other non-object body is a shape change.
            if responded and body is None:
                raise ValueError(f"Humanitix check-in count for {marker} returned a non-object body")
            completed.append(marker)
            resumable_source_manager.save_state(HumanitixResumeConfig(next_page=page, completed=list(completed)))
            if body is None:
                resumable_source_manager.safe_point()
                continue
            yield {**body, "eventId": event_id, "eventDateId": date_id}

        done = []
        page += 1
        resumable_source_manager.safe_point()


def _make_source_response(
    config: HumanitixEndpointConfig, items: Any, column_hints: Optional[dict[str, Any]] = None
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def _fanout_source(
    config: HumanitixEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HumanitixResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = HUMANITIX_ENDPOINTS[config.fanout.parent_name]

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
                HumanitixResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=HUMANITIX_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra={"data_selector": parent_config.list_key, "data_selector_required": True},
            child_endpoint_extra={"data_selector": config.list_key, "data_selector_required": True},
            page_size_param="pageSize",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    return _make_source_response(config, lambda: dependent_resource)


def humanitix_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HumanitixResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HUMANITIX_ENDPOINTS[endpoint]

    if config.per_event_date:
        return _make_source_response(config, lambda: _check_in_count_rows(config, api_key, resumable_source_manager))

    if config.fanout is not None:
        return _fanout_source(config, api_key, team_id, job_id, resumable_source_manager)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"pageSize": PAGE_SIZE},
                    "data_selector": config.list_key,
                    # The row array is always present in the envelope; missing it means a malformed
                    # response, so fail loud rather than silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page > 1:
            initial_paginator_state = {"next_page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `_id`) rather than skipping it.
        if state and state.get("next_page") is not None:
            resumable_source_manager.save_state(HumanitixResumeConfig(next_page=int(state["next_page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _make_source_response(config, lambda: resource, column_hints=resource.column_hints)


def validate_credentials(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[bool, str | None]:
    """Probe a single list endpoint to validate the account-wide API key.

    The key is account-wide, so one probe validates access to every list endpoint. Maps 401/403 to a
    bad-key message, any other non-200 to its status, and an unreachable probe to a generic message.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{HUMANITIX_BASE_URL}{path}?page=1&pageSize=1",
        headers={"x-api-key": api_key, **_headers()},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Humanitix API key"
    if status is None:
        return False, "Could not validate Humanitix API key"
    return False, f"Humanitix returned HTTP {status}"
