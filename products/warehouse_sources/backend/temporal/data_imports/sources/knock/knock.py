import dataclasses
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any, Optional, cast
from urllib.parse import quote, unquote

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.settings import (
    ENDPOINTS_CONFIG,
    KNOCK_BASE_URL,
    KNOCK_PAGE_SIZE,
    KnockEndpointConfig,
)

DEFAULT_INCREMENTAL_START = "1970-01-01T00:00:00Z"

NO_OBJECT_COLLECTIONS_ERROR = (
    "The Knock objects table needs at least one object collection. "
    "Add your collection keys in the source settings, then sync again."
)

NO_AUDIENCE_KEYS_ERROR = (
    "The Knock audience members table needs at least one audience key. "
    "Add your audience keys in the source settings, then sync again."
)


@dataclasses.dataclass(frozen=True)
class KnockResumeConfig:
    after: str | None = None
    # Set only by the objects and audience members tables, which walk one configured
    # collection or audience key after another.
    collection: str | None = None


def _to_iso8601(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def parse_key_list(keys: Optional[str]) -> list[str]:
    if not keys:
        return []
    return list(dict.fromkeys(part.strip() for part in keys.split(",") if part.strip()))


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": KNOCK_BASE_URL,
        "auth": {
            "type": "bearer",
            "token": api_key,
        },
        "headers": {"Accept": "application/json"},
        "paginator": JSONResponseCursorPaginator(cursor_path="page_info.after", cursor_param="after"),
    }


def _percent_encode_id(row: dict[str, Any]) -> dict[str, Any]:
    # User ids are free-form strings and the fan-out binds them into the path unescaped.
    row["id"] = quote(str(row["id"]), safe="")
    return row


def _decode_user_id(row: dict[str, Any]) -> dict[str, Any]:
    # The fan-out tags child rows with the parent id after `_percent_encode_id` ran on it.
    row["user_id"] = unquote(row["user_id"])
    return row


def _shape_user_subscription(row: dict[str, Any]) -> dict[str, Any]:
    row = _decode_user_id(row)
    subscribed_object = row.get("object") or {}
    row["object_collection"] = subscribed_object.get("collection")
    row["object_id"] = subscribed_object.get("id")
    return row


_FANOUT_CHILD_ROW_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "user_subscriptions": _shape_user_subscription,
    "user_preferences": _decode_user_id,
}


def _paginator_override(config: KnockEndpointConfig) -> PaginatorConfig | None:
    if config.data_selector is None:
        return "single_page"
    if not config.documents_pagination:
        # The spec documents no cursor param here; fail loud if Knock returns a cursor it
        # then ignores, rather than re-reading the first page forever.
        return JSONResponseCursorPaginator(
            cursor_path="page_info.after", cursor_param="after", raise_on_repeated_cursor=True
        )
    return None


def _no_child_window(_incremental_field: str) -> Optional[IncrementalConfig]:
    # The child endpoints take no timestamp filter, so the window goes on the parent walk.
    return None


def get_resource(endpoint: str, should_use_incremental_field: bool, path: str | None = None) -> EndpointResource:
    config = ENDPOINTS_CONFIG[endpoint]

    params: dict[str, Any] = {"page_size": KNOCK_PAGE_SIZE} if config.documents_pagination else {}
    if should_use_incremental_field and config.incremental_param and config.incremental_fields:
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": config.incremental_fields[0]["field"],
            "initial_value": DEFAULT_INCREMENTAL_START,
            "convert": _to_iso8601,
        }

    endpoint_config: Endpoint = {
        "path": path or config.path,
        "params": params,
        "data_selector": config.data_selector,
        # Fail loud if Knock ever changes the response envelope key instead of
        # silently syncing 0 rows.
        "data_selector_required": True,
    }
    paginator = _paginator_override(config)
    if paginator is not None:
        endpoint_config["paginator"] = paginator

    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _fanout_items(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
) -> Any:
    endpoint_config = ENDPOINTS_CONFIG[endpoint]
    fanout = endpoint_config.fanout
    assert fanout is not None
    parent_config = ENDPOINTS_CONFIG[fanout.parent_name]

    if should_use_incremental_field and endpoint_config.incremental_param and db_incremental_field_last_value:
        fanout = dataclasses.replace(
            fanout, parent_params={endpoint_config.incremental_param: _to_iso8601(db_incremental_field_last_value)}
        )

    child_endpoint_extra: Endpoint = {"data_selector": endpoint_config.data_selector, "data_selector_required": True}
    paginator = _paginator_override(endpoint_config)
    if paginator is not None:
        child_endpoint_extra["paginator"] = paginator

    # No resume hook: the framework's per-parent checkpoint lists every parent completed so far,
    # which grows without bound on message- and user-sized parents.
    resource = build_dependent_resource(
        endpoint_configs=ENDPOINTS_CONFIG,
        child_endpoint=endpoint,
        fanout=fanout,
        client_config=_client_config(api_key),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        should_use_incremental_field=should_use_incremental_field,
        incremental_field=endpoint_config.default_incremental_field,
        incremental_config_factory=_no_child_window,
        parent_endpoint_extra={"data_selector": parent_config.data_selector, "data_selector_required": True},
        child_endpoint_extra=child_endpoint_extra,
        parent_data_map=_percent_encode_id if fanout.parent_name == "users" else None,
        # The size param is shared by the parent and the child. Knock's default page size is
        # the same as KNOCK_PAGE_SIZE, so leaving it off keeps the parent walk unchanged.
        page_size_param="page_size" if endpoint_config.documents_pagination else None,
    )
    child_row_map = _FANOUT_CHILD_ROW_MAPS.get(endpoint)
    return cast(Resource, resource).add_map(child_row_map) if child_row_map is not None else resource


def _tag_audience_key(audience_key: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _tag(row: dict[str, Any]) -> dict[str, Any]:
        row["audience_key"] = audience_key
        return row

    return _tag


def _keyed_items(
    api_key: str,
    endpoint: str,
    keys: list[str],
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KnockResumeConfig],
) -> Iterator[Any]:
    start_index = 0
    start_after: str | None = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.collection in keys:
            start_index = keys.index(resume_config.collection)
            start_after = resume_config.after

    for index in range(start_index, len(keys)):
        key = keys[index]
        after = start_after if index == start_index else None
        if after is None:
            # Every row of the earlier keys is already yielded, so a resume can start here.
            resumable_source_manager.save_state(KnockResumeConfig(collection=key))

        def save_checkpoint(state: Optional[dict[str, Any]], _key: str = key) -> None:
            if state and state.get("cursor"):
                resumable_source_manager.save_state(KnockResumeConfig(after=str(state["cursor"]), collection=_key))

        resource = get_resource(
            endpoint,
            should_use_incremental_field=False,
            path=ENDPOINTS_CONFIG[endpoint].path.replace("{key}", quote(key, safe="")),
        )
        if endpoint == "audience_members":
            # Member rows don't say which audience they belong to.
            resource["data_map"] = _tag_audience_key(key)

        config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resource_defaults": {},
            "resources": [resource],
        }
        for page in rest_api_resource(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"cursor": after} if after else None,
        ):
            yield page
            # The page is handed on in full and nothing is buffered, so a hand-off loses no rows.
            resumable_source_manager.safe_point()


def knock_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KnockResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    object_collections: Optional[str] = None,
    audience_keys: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = ENDPOINTS_CONFIG[endpoint]

    items: Any
    if endpoint_config.fanout is not None:
        resource = _fanout_items(
            api_key, endpoint, team_id, job_id, db_incremental_field_last_value, should_use_incremental_field
        )
        items = lambda: resource
    elif endpoint in ("objects", "audience_members"):
        keys = parse_key_list(object_collections if endpoint == "objects" else audience_keys)
        if not keys:
            raise ValueError(NO_OBJECT_COLLECTIONS_ERROR if endpoint == "objects" else NO_AUDIENCE_KEYS_ERROR)
        items = lambda: _keyed_items(api_key, endpoint, keys, team_id, job_id, resumable_source_manager)
    else:
        config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resource_defaults": {},
            "resources": [get_resource(endpoint, should_use_incremental_field)],
        }

        initial_paginator_state: Optional[dict[str, Any]] = None
        if resumable_source_manager.can_resume():
            resume_config = resumable_source_manager.load_state()
            if resume_config is not None and resume_config.after:
                initial_paginator_state = {"cursor": resume_config.after}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Only persist when there's a next page to resume to; the Redis TTL
            # handles cleanup on completion.
            if state and state.get("cursor"):
                resumable_source_manager.save_state(KnockResumeConfig(after=str(state["cursor"])))

        resource = rest_api_resource(
            config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        items = lambda: resource

    has_partition_key = endpoint_config.partition_key is not None

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=list(endpoint_config.primary_keys),
        partition_count=1 if has_partition_key else None,
        partition_size=1 if has_partition_key else None,
        partition_mode="datetime" if has_partition_key else None,
        partition_format="month" if has_partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode=endpoint_config.sort_mode,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_key,))
    res = session.get(
        f"{KNOCK_BASE_URL}/v1/users",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        params={"page_size": 1},
        timeout=30,
    )

    if res.status_code == 200:
        return True, None

    if res.status_code in (401, 403):
        # Knock returns {"code": "api_key_invalid", "message": "..."} on auth failures.
        try:
            message = res.json().get("message")
        except Exception:
            message = None
        return False, message or "Invalid Knock API key"

    return False, f"Knock API returned an unexpected response (HTTP {res.status_code})"
