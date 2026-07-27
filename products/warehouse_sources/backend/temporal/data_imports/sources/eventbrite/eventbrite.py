import dataclasses
from datetime import UTC, date, datetime
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
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.settings import (
    EVENTBRITE_ENDPOINTS,
    ORG_EVENTS_PATH,
    ORGANIZATIONS_PATH,
    EndpointScope,
    EventbriteEndpointConfig,
)

EVENTBRITE_BASE_URL = "https://www.eventbriteapi.com/v3"


@dataclasses.dataclass
class EventbriteResumeConfig:
    # Continuation token for the next page of a top-level list endpoint (organizations/categories/
    # formats). Fan-out endpoints (org/event scoped) instead persist the framework's dependent-resource
    # checkpoint under `fanout_state`; a two-level fan-out (attendees/ticket_classes) has no resume at
    # all and relies on merge dedupe. Both fields default so an old `{"continuation": ...}` state still
    # parses after this change.
    continuation: str = ""
    fanout_state: Optional[dict[str, Any]] = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_changed_since(value: Any) -> str:
    """Format an incremental value for Eventbrite's `changed_since` filter (ISO 8601 UTC, Z suffix)."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


class EventbriteContinuationPaginator(BasePaginator):
    """Eventbrite v3 continuation-token pagination.

    Stops on ``pagination.has_more_items == false`` rather than merely the absence of a continuation
    token: Eventbrite can still return a token on the final page, so gating strictly on
    ``has_more_items`` preserves the hand-rolled behavior exactly.
    """

    def __init__(self, cursor_param: str = "continuation") -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self._continuation: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if self._continuation is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._continuation

    def init_request(self, request: Request) -> None:
        # Seed a resumed run's first request with the saved continuation token.
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            pagination = response.json().get("pagination") or {}
        except Exception:
            pagination = {}
        continuation = pagination.get("continuation")
        if pagination.get("has_more_items") and continuation:
            self._continuation = continuation
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._has_next_page:
            self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._continuation is not None:
            return {"continuation": self._continuation}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        continuation = state.get("continuation")
        if continuation is not None:
            self._continuation = continuation
            self._has_next_page = True


def _client_config(api_token: str) -> ClientConfig:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs;
    # only the non-secret Accept header is set on the client.
    return {
        "base_url": EVENTBRITE_BASE_URL,
        "auth": {"type": "bearer", "token": api_token},
        "headers": {"Accept": "application/json"},
        "paginator": EventbriteContinuationPaginator(),
    }


def _changed_since_incremental(config: EventbriteEndpointConfig) -> IncrementalConfig:
    return {
        "cursor_path": config.changed_since_field or "changed",
        "start_param": "changed_since",
        "convert": _format_changed_since,
    }


def _leaf_endpoint(
    config: EventbriteEndpointConfig,
    *,
    resolve: Optional[tuple[str, str, str]] = None,
    incremental: Optional[IncrementalConfig] = None,
) -> Endpoint:
    endpoint: Endpoint = {"path": config.path, "data_selector": config.data_key}
    if resolve is not None:
        param_name, parent, field = resolve
        endpoint["params"] = {param_name: {"type": "resolve", "resource": parent, "field": field}}
    if incremental is not None:
        endpoint["incremental"] = incremental
    return endpoint


def _parent_resource(
    name: str, path: str, data_selector: str, resolve: Optional[tuple[str, str, str]]
) -> EndpointResource:
    endpoint: Endpoint = {"path": path, "data_selector": data_selector}
    if resolve is not None:
        param_name, parent, field = resolve
        endpoint["params"] = {param_name: {"type": "resolve", "resource": parent, "field": field}}
    return {"name": name, "endpoint": endpoint}


def _should_apply_incremental(
    config: EventbriteEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> bool:
    # Mirror the hand-rolled gate: only narrow with the server-side `changed_since` filter when the
    # endpoint supports it and the user's chosen cursor is the field that filter targets (`changed`).
    return (
        should_use_incremental_field
        and config.changed_since_field is not None
        and db_incremental_field_last_value is not None
        and incremental_field in (None, config.changed_since_field)
    )


def eventbrite_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[EventbriteResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = EVENTBRITE_ENDPOINTS[endpoint]

    incremental: Optional[IncrementalConfig] = None
    if _should_apply_incremental(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    ):
        incremental = _changed_since_incremental(config)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None:
        if resume.fanout_state:
            initial_paginator_state = resume.fanout_state
        elif resume.continuation:
            initial_paginator_state = {"continuation": resume.continuation}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge dedupes on PK).
        if not state:
            return
        if "continuation" in state:
            if state.get("continuation"):
                resumable_source_manager.save_state(EventbriteResumeConfig(continuation=state["continuation"]))
        else:
            resumable_source_manager.save_state(EventbriteResumeConfig(fanout_state=state))

    client = _client_config(api_token)

    resource: Resource
    if config.scope == EndpointScope.TOP_LEVEL:
        rest_config: RESTAPIConfig = {
            "client": client,
            "resources": [{"name": endpoint, "endpoint": _leaf_endpoint(config)}],
        }
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
    else:
        resources: list[str | EndpointResource] = [
            _parent_resource("organizations", ORGANIZATIONS_PATH, "organizations", None)
        ]
        if config.scope == EndpointScope.ORG:
            leaf = _leaf_endpoint(config, resolve=("organization_id", "organizations", "id"), incremental=incremental)
        else:  # EndpointScope.EVENT — two-level fan-out: organizations -> events -> leaf
            resources.append(
                _parent_resource("events", ORG_EVENTS_PATH, "events", ("organization_id", "organizations", "id"))
            )
            leaf = _leaf_endpoint(config, resolve=("event_id", "events", "id"), incremental=incremental)
        resources.append({"name": endpoint, "endpoint": leaf})

        rest_config = {"client": client, "resources": resources}
        built = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
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


def validate_credentials(api_token: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{EVENTBRITE_BASE_URL}/users/me/",
        headers=_get_headers(api_token),
    )
    return ok
