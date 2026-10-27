import dataclasses
from collections.abc import Callable, Iterator
from functools import partial
from typing import Any, Optional
from urllib.parse import quote, urlsplit

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.settings import (
    FOLK_BASE_URL,
    FOLK_BUILTIN_ENTITY_TYPES,
    FOLK_ENDPOINTS,
    FolkEndpointConfig,
)

# Documented maximum on every list endpoint (the default is 20).
FOLK_PAGE_SIZE = 100


class FolkUntrustedURLError(Exception):
    pass


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Folk API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `pagination.nextLink` URLs are
    followed verbatim with the customer's bearer token. Validating the scheme, host, and `/v1/`
    path prefix keeps a poisoned resume state or a hostile upstream response from retargeting the
    request at another host and leaking the token (SSRF). Returns the URL unchanged when trusted.
    """
    parts = urlsplit(url)
    is_trusted = parts.scheme == "https" and parts.netloc == "api.folk.app" and parts.path.startswith("/v1/")
    if not is_trusted:
        raise FolkUntrustedURLError("Refusing to follow a pagination URL outside the Folk API")
    return url


class FolkPaginator(JSONResponsePaginator):
    """Follows the envelope's `data.pagination.nextLink` URL, refusing any URL off the Folk API
    origin, whether it arrived in a response body or was seeded from saved resume state.

    The last page omits `nextLink` from the `pagination` object, which ends the walk."""

    def __init__(self) -> None:
        super().__init__(next_url_path="data.pagination.nextLink")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._next_url is not None:
            _validate_pagination_url(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        if self._next_url is not None:
            _validate_pagination_url(self._next_url)


@dataclasses.dataclass(frozen=True)
class FolkResumeConfig:
    # Full next-page URL from the response's `data.pagination.nextLink` field (omitted on the last
    # page). It carries the opaque cursor and the limit, so following it resumes the walk exactly.
    next_url: str | None = None
    # Group fan-out position: the groups still to sync and, within the head group, the children
    # (custom field entity types or object types) still to sync. The head of each list is in progress.
    remaining_group_ids: list[str] | None = None
    remaining_child_keys: list[str] | None = None


def probe_credentials(api_key: str, endpoint: str | None = None) -> int | None:
    """Cheap probe of the Folk API. Returns the HTTP status code, or None on a connection failure.

    Probes the given endpoint's own path when set (one row, to confirm access to that resource),
    else `/v1/users/me`, the cheapest call that confirms the key is genuine."""
    config = FOLK_ENDPOINTS.get(endpoint) if endpoint else None
    if config is None:
        url = f"{FOLK_BASE_URL}/v1/users/me"
    else:
        # Group-scoped endpoints have no listing without a group id, so probe the groups they fan out over.
        path = "/v1/groups" if config.group_fanout else config.path
        url = f"{FOLK_BASE_URL}{path}?limit=1"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return status


def folk_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FolkResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = schema_for_resource(FOLK_ENDPOINTS, endpoint)

    if config.group_fanout:
        client = RESTClient(
            base_url=FOLK_BASE_URL,
            auth=BearerTokenAuth(token=api_key),
            paginator=FolkPaginator(),
            capture=False,
        )
        return _source_response(config, lambda: _iter_group_fanout(client, config, resumable_source_manager))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": FOLK_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from logs.
            "auth": {"type": "bearer", "token": api_key},
            "paginator": FolkPaginator(),
            # Notes, tasks, and contact fields can carry confidential CRM content that the
            # name-based scrubber won't reliably catch (e.g. generic `content`/`description`
            # keys), so this PII-heavy source opts out of HTTP sample capture.
            "capture": False,
        },
        "resources": [
            {
                "name": config.name,
                "table_name": config.name,
                "write_disposition": "replace",
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": FOLK_PAGE_SIZE},
                    "data_selector": "data.items",
                    # A response missing `data.items` is a shape change, not a legitimately empty
                    # page; fail loud instead of silently replacing the table with zero rows.
                    "data_selector_required": True,
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the checkpoint lands AFTER a page is yielded so a
        # crash re-yields the last page (full refresh rewrites the table, so no duplicates land).
        if state and state.get("next_url"):
            resumable_source_manager.save_state(FolkResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, lambda: resource)


def _source_response(config: FolkEndpointConfig, items: Callable[[], Any]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


@dataclasses.dataclass(frozen=True)
class _GroupChild:
    # Resume key of the child within its group; "" when the group has a single child listing.
    key: str
    path: str
    # Columns added to every row, since the child rows do not name the group or type they belong to.
    row_fields: dict[str, str]


def _paginate(
    client: RESTClient,
    path: str,
    next_url: str | None = None,
    page_state_hook: Optional[Callable[[Optional[dict[str, Any]], bool], None]] = None,
) -> Iterator[list[dict[str, Any]]]:
    return client.paginate(
        path=path,
        params={"limit": FOLK_PAGE_SIZE},
        data_selector="data.items",
        data_selector_required=True,
        initial_paginator_state={"next_url": next_url} if next_url else None,
        page_state_hook=page_state_hook,
    )


def _object_type_names(
    client: RESTClient, manager: ResumableSourceManager[FolkResumeConfig], group_id: str
) -> list[str]:
    """Folk documents the group's person custom fields of type `objectField` as the way to list its
    object types (Deals and any other custom object type)."""
    names: list[str] = []
    for page in _paginate(client, f"/v1/groups/{group_id}/custom-fields/person"):
        names.extend(field["name"] for field in page if field.get("type") == "objectField")
        manager.safe_point()
    return names


def _group_children(
    client: RESTClient,
    manager: ResumableSourceManager[FolkResumeConfig],
    config: FolkEndpointConfig,
    group_id: str,
) -> list[_GroupChild]:
    path = config.path.replace("{groupId}", group_id)
    if config.group_fanout == "members":
        return [_GroupChild(key="", path=path, row_fields={"groupId": group_id})]
    if config.group_fanout == "custom_fields":
        entity_types = [*FOLK_BUILTIN_ENTITY_TYPES, *_object_type_names(client, manager, group_id)]
        return [
            _GroupChild(
                key=entity_type,
                path=path.replace("{entityType}", quote(entity_type, safe="")),
                row_fields={"groupId": group_id, "entityType": entity_type},
            )
            for entity_type in entity_types
        ]
    return [
        _GroupChild(
            key=object_type,
            path=path.replace("{objectType}", quote(object_type, safe="")),
            row_fields={"groupId": group_id, "objectType": object_type},
        )
        for object_type in _object_type_names(client, manager, group_id)
    ]


def _raise_unless_not_found(error: HTTPError) -> None:
    # A 404 means the group or object type was deleted after it was listed.
    if error.response is None or error.response.status_code != 404:
        raise error


def _stage_position(
    manager: ResumableSourceManager[FolkResumeConfig],
    group_ids: list[str],
    keys: list[str],
    index: int,
    state: Optional[dict[str, Any]],
    has_next: bool,
) -> None:
    """Stage the position of the page after the one about to be yielded."""
    if has_next and state:
        position = FolkResumeConfig(
            next_url=state["next_url"], remaining_group_ids=group_ids, remaining_child_keys=keys[index:]
        )
    elif index + 1 < len(keys):
        position = FolkResumeConfig(remaining_group_ids=group_ids, remaining_child_keys=keys[index + 1 :])
    else:
        position = FolkResumeConfig(remaining_group_ids=group_ids[1:])
    manager.save_state(position)


def _iter_group_fanout(
    client: RESTClient,
    config: FolkEndpointConfig,
    manager: ResumableSourceManager[FolkResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.remaining_group_ids is not None:
        group_ids = list(resume.remaining_group_ids)
        child_keys, next_url = resume.remaining_child_keys, resume.next_url
    else:
        group_ids = []
        for page in _paginate(client, "/v1/groups"):
            group_ids.extend(group["id"] for group in page)
            manager.safe_point()
        child_keys, next_url = None, None

    while group_ids:
        # Every row before this position is already yielded, so the run can hand off here.
        manager.save_state(
            FolkResumeConfig(next_url=next_url, remaining_group_ids=group_ids, remaining_child_keys=child_keys)
        )
        manager.safe_point()
        try:
            children = _group_children(client, manager, config, group_ids[0])
        except HTTPError as error:
            _raise_unless_not_found(error)
            children = []
        if child_keys is not None:
            # Keep only the children the saved position had left, and skip any deleted since.
            by_key = {child.key: child for child in children}
            if not child_keys or child_keys[0] not in by_key:
                next_url = None
            children = [by_key[key] for key in child_keys if key in by_key]
        keys = [child.key for child in children]

        for index, child in enumerate(children):
            try:
                for page in _paginate(
                    client,
                    child.path,
                    next_url=next_url,
                    page_state_hook=partial(_stage_position, manager, group_ids, keys, index),
                ):
                    if page:
                        yield [{**row, **child.row_fields} for row in page]
                    else:
                        manager.safe_point()
            except HTTPError as error:
                _raise_unless_not_found(error)
            next_url = None

        group_ids = group_ids[1:]
        child_keys = None
