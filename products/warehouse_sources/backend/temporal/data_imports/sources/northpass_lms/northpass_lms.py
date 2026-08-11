import dataclasses
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    make_parent_key_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.settings import (
    NORTHPASS_ENDPOINTS,
    QUIZ_COMPLETED_EVENT_TYPE,
    NorthpassEndpointConfig,
)

NORTHPASS_BASE_URL = "https://api.northpass.com/v2"
# Northpass serves every account from this single shared host (no per-account subdomains). Pinning
# every request — including the JSON:API `links.next` pagination URL (attacker-controlled if the
# upstream is spoofed) — to this host keeps the credentialed request from leaking the key off-host.
NORTHPASS_HOST = "api.northpass.com"
# Northpass doesn't publish its max page size; 100 is a conventional cap that keeps payloads small.
PAGE_SIZE = 100


@dataclasses.dataclass
class NorthpassResumeConfig:
    # Top-level endpoints: full URL of the next JSON:API page (`links.next`). None means "start from
    # the first page".
    next_url: str | None = None
    # Deprecated fan-out bookmark from the pre-framework transport. Retained (with a default) so
    # state saved by the old implementation still rehydrates via ``dataclass(**saved)``; new fan-out
    # runs store their cursor in ``fanout_state`` instead.
    parent_id: str | None = None
    # Fan-out endpoints: the framework's dependent-resource resume cursor —
    # ``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}``.
    # Parents already fully synced are skipped by path; the in-progress parent resumes its page cursor.
    fanout_state: dict[str, Any] | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def _build_url(path: str, params: dict[str, Any]) -> str:
    base = f"{NORTHPASS_BASE_URL}{path}"
    return f"{base}?{urlencode(params)}" if params else base


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Promote a JSON:API resource's ``attributes`` to the root, keeping ``id``/``type``/``relationships``.

    The per-item ``links`` block is dropped (it's only self/action hyperlinks).
    """
    row = dict(item)
    attributes = row.pop("attributes", None)
    row.pop("links", None)
    if isinstance(attributes, dict):
        row.update(attributes)
    return row


def _make_relationship_flattener(relationship_id_fields: dict[str, str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Flatten a row and promote related-resource ids from ``relationships`` to root columns.

    ``/events`` rows carry no ``id`` and reference the person/activity they belong to only inside
    JSON:API ``relationships``; promoting those ids gives the row queryable foreign-key columns
    (which also form its primary key). A missing relationship still emits its column (``None``) so
    the table schema stays stable across heterogeneous event types.
    """

    def _flatten(item: dict[str, Any]) -> dict[str, Any]:
        row = _flatten_item(item)
        relationships = row.get("relationships")
        for relationship, column in relationship_id_fields.items():
            related = relationships.get(relationship) if isinstance(relationships, dict) else None
            data = related.get("data") if isinstance(related, dict) else None
            row[column] = data.get("id") if isinstance(data, dict) else None
        return row

    return _flatten


def _make_child_flattener(parent_name: str, parent_id_field: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Flatten a fan-out child row and rename its injected parent id.

    ``include_from_parent=["id"]`` injects the parent id under ``_{parent_name}_id``; rename it to the
    endpoint's ``parent_id_field`` (part of the child primary key) so the parent id always wins over
    any same-named attribute — matching the old transport's ``row.update(extra)`` ordering.
    """
    prefixed_key = make_parent_key_name(parent_name, "id")

    def _flatten(item: dict[str, Any]) -> dict[str, Any]:
        row = _flatten_item(item)
        if prefixed_key in row:
            row[parent_id_field] = row.pop(prefixed_key)
        return row

    return _flatten


def _promote_relationship_ids(row: dict[str, Any], relationship_id_fields: dict[str, str]) -> dict[str, Any]:
    """Promote related-resource ids out of a row's JSON:API ``relationships`` into root columns.

    Gives rows queryable foreign-key columns. A missing relationship still emits its column
    (``None``) so the table schema stays stable across rows.
    """
    relationships = row.get("relationships")
    for relationship, column in relationship_id_fields.items():
        related = relationships.get(relationship) if isinstance(relationships, dict) else None
        data = related.get("data") if isinstance(related, dict) else None
        row[column] = data.get("id") if isinstance(data, dict) else None
    return row


def _make_quiz_attempt_flattener() -> Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]:
    """Reshape sent-webhooks log messages into completed-quiz-attempt rows.

    The v2 API lists no quiz attempts directly; the quiz-completed event a ``/webhooks`` message
    delivered (in ``attributes.payload``) is the only documented place attempt UUIDs and results
    appear. The attempt UUID becomes the row ``id`` — the primary key, and what the answers fan-out
    resolves — with the event's own id kept as ``event_id`` and the quiz/course/person/activity
    references promoted to id columns. A message maps to ``[]`` (dropping it) when it carries
    another event type (in case the server ever ignores the type filter), when its payload has no
    attempt UUID, or when the attempt was already seen this run — the log stores one message per
    subscribed webhook endpoint, so the same attempt can appear more than once.
    """
    seen: set[str] = set()

    def _flatten(item: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        message = item.get("attributes")
        if not isinstance(message, dict) or message.get("type") != QUIZ_COMPLETED_EVENT_TYPE:
            return []
        payload = message.get("payload")
        event = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(event, dict):
            return []
        attributes = event.get("attributes")
        if not isinstance(attributes, dict):
            return []
        attempt_id = attributes.get("quiz_attempt_uuid")
        if not attempt_id or attempt_id in seen:
            return []
        seen.add(attempt_id)

        row: dict[str, Any] = {key: value for key, value in attributes.items() if key != "quiz_attempt_uuid"}
        # Set after the attribute spread so the attempt id always wins as ``id``.
        row.update(
            {
                "id": attempt_id,
                "type": event.get("type"),
                "event_id": event.get("id"),
                "relationships": event.get("relationships"),
            }
        )
        return _promote_relationship_ids(
            row, {"quiz": "quiz_id", "course": "course_id", "person": "person_id", "activity": "activity_id"}
        )

    return _flatten


def _make_quiz_answer_flattener(parent_name: str, parent_id_field: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Child flattener for quiz answers: standard child flattening plus a promoted ``question_id``.

    An answer references its question only inside JSON:API ``relationships``; promoting the id to a
    root column keeps answers joinable to their question.
    """
    flatten_child = _make_child_flattener(parent_name, parent_id_field)

    def _flatten(item: dict[str, Any]) -> dict[str, Any]:
        return _promote_relationship_ids(flatten_child(item), {"question": "question_id"})

    return _flatten


def _collection_params(config: NorthpassEndpointConfig) -> dict[str, Any]:
    return dict(config.params) if config.params is not None else {"limit": PAGE_SIZE}


def _collection_data_map(
    endpoint: str,
) -> Optional[Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]]:
    """Bespoke row transform for a collection endpoint, or None when raw JSON:API items are fine."""
    if endpoint == "quiz_attempts":
        return _make_quiz_attempt_flattener()
    return None


def _child_data_map(
    endpoint: str, parent_name: str, parent_id_field: str
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    if endpoint == "quiz_attempt_answers":
        return _make_quiz_answer_flattener(parent_name, parent_id_field)
    return _make_child_flattener(parent_name, parent_id_field)


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": NORTHPASS_BASE_URL,
        # Auth (the API key) rides in the framework auth config so its value is redacted from logs and
        # raised errors; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-Api-Key", "location": "header"},
        # JSON:API paginates via a `links.next` URL embedded in the response body.
        "paginator": JSONResponsePaginator(next_url_path="links.next"),
        # Pin every request to Northpass's host and refuse redirects, so a spoofed `next` link or a
        # 30x can't forward the credentialed X-Api-Key header off-host.
        "allowed_hosts": [NORTHPASS_HOST],
        "allow_redirects": False,
    }


def _top_level_source(
    api_key: str,
    endpoint: str,
    config: NorthpassEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    data_map = _collection_data_map(endpoint) or (
        _make_relationship_flattener(config.relationship_id_fields) if config.relationship_id_fields else _flatten_item
    )
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        # A collection with no rows 404s instead of returning `data: []` (seen on
        # /learning-paths); retrying can't produce rows, so treat it like the empty-body
        # case above and let the resource yield nothing rather than failing the sync.
        "resource_defaults": {"endpoint": {"response_actions": [{"status_code": 404, "action": "ignore"}]}},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _collection_params(config),
                    # A 200 without `data` is treated as an empty page (old transport used
                    # `.get("data", [])`), so no data_selector_required here.
                    "data_selector": "data",
                },
                "data_map": data_map,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the hook fires AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(NorthpassResumeConfig(next_url=state["next_url"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fan_out_source(
    api_key: str,
    endpoint: str,
    config: NorthpassEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    if config.fan_out_parent is None or config.parent_id_field is None:
        raise ValueError(f"_fan_out_source called with non-fan-out config: {config.name}")
    parent_name = config.fan_out_parent
    parent_config = NORTHPASS_ENDPOINTS[parent_name]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        # Same "empty collection 404s instead of `data: []`" case as the top-level source: the
        # parent enumeration below inherits this so an account with no parent rows fans out over
        # zero parents instead of failing the sync outright.
        "resource_defaults": {"endpoint": {"response_actions": [{"status_code": 404, "action": "ignore"}]}},
        "resources": [
            {
                "name": parent_name,
                "endpoint": {
                    "path": parent_config.path,
                    "params": _collection_params(parent_config),
                    "data_selector": "data",
                },
                # Parents that aren't plain JSON:API collections (the sent-webhooks log backing
                # quiz_attempts) are reshaped before the child resolves ids from their rows.
                "data_map": _collection_data_map(parent_name),
            },
            {
                "name": endpoint,
                "include_from_parent": ["id"],
                "endpoint": {
                    "path": config.path,
                    "params": {
                        "parent_id": {"type": "resolve", "resource": parent_name, "field": "id"},
                        "limit": PAGE_SIZE,
                    },
                    "data_selector": "data",
                    # A parent deleted between enumeration and this fetch 404s; treat that child page
                    # as a valid empty page and move on to the next parent rather than failing the sync.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
                "data_map": _child_data_map(endpoint, parent_name, config.parent_id_field),
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(NorthpassResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    # Only the child rows are emitted; the parent list is iterated internally to drive the fan-out.
    return next(resource for resource in resources if resource.name == endpoint)


def northpass_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NORTHPASS_ENDPOINTS[endpoint]

    if config.fan_out_parent is not None:
        resource = _fan_out_source(
            api_key, endpoint, config, team_id, job_id, resumable_source_manager, db_incremental_field_last_value
        )
    else:
        resource = _top_level_source(
            api_key, endpoint, config, team_id, job_id, resumable_source_manager, db_incremental_field_last_value
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe a cheap list endpoint to confirm the API key is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        _build_url("/courses", {"limit": 1}),
        headers=_headers(api_key),
    )
    return ok, status
