import dataclasses
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.settings import (
    ENDPOINTS_CONFIG,
    KNOCK_BASE_URL,
    KNOCK_PAGE_SIZE,
)

DEFAULT_INCREMENTAL_START = "1970-01-01T00:00:00Z"

NO_OBJECT_COLLECTIONS_ERROR = (
    "The Knock objects table needs at least one object collection. "
    "Add your collection keys in the source settings, then sync again."
)


@dataclasses.dataclass
class KnockResumeConfig:
    after: str | None = None
    # Set only by the objects table, which walks one collection after another.
    collection: str | None = None


def _to_iso8601(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def parse_object_collections(object_collections: Optional[str]) -> list[str]:
    if not object_collections:
        return []
    return list(dict.fromkeys(part.strip() for part in object_collections.split(",") if part.strip()))


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


def _no_child_window(_incremental_field: str) -> Optional[IncrementalConfig]:
    # The child endpoints take no timestamp filter, so the window goes on the parent walk.
    return None


def get_resource(endpoint: str, should_use_incremental_field: bool, path: str | None = None) -> EndpointResource:
    config = ENDPOINTS_CONFIG[endpoint]

    params: dict[str, Any] = {"page_size": KNOCK_PAGE_SIZE}
    if should_use_incremental_field and config.incremental_param and config.incremental_fields:
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": config.incremental_fields[0]["field"],
            "initial_value": DEFAULT_INCREMENTAL_START,
            "convert": _to_iso8601,
        }

    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": path or config.path,
            "params": params,
            "data_selector": config.data_selector,
            # Fail loud if Knock ever changes the response envelope key instead of
            # silently syncing 0 rows.
            "data_selector_required": True,
        },
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

    # No resume hook: the framework's per-parent checkpoint lists every parent completed so far,
    # which grows without bound on message- and user-sized parents.
    return build_dependent_resource(
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
        child_endpoint_extra={"data_selector": endpoint_config.data_selector, "data_selector_required": True},
        parent_data_map=_percent_encode_id if fanout.parent_name == "users" else None,
        page_size_param="page_size",
    )


def _objects_items(
    api_key: str,
    collections: list[str],
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KnockResumeConfig],
) -> Iterator[Any]:
    start_index = 0
    start_after: str | None = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.collection in collections:
            start_index = collections.index(resume_config.collection)
            start_after = resume_config.after

    for index in range(start_index, len(collections)):
        collection = collections[index]
        after = start_after if index == start_index else None
        if after is None:
            # Every row of the earlier collections is already yielded, so a resume can start here.
            resumable_source_manager.save_state(KnockResumeConfig(collection=collection))

        def save_checkpoint(state: Optional[dict[str, Any]], _collection: str = collection) -> None:
            if state and state.get("cursor"):
                resumable_source_manager.save_state(
                    KnockResumeConfig(after=str(state["cursor"]), collection=_collection)
                )

        config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resource_defaults": {},
            "resources": [
                get_resource(
                    "objects",
                    should_use_incremental_field=False,
                    path=f"/v1/objects/{quote(collection, safe='')}",
                )
            ],
        }
        yield from rest_api_resource(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"cursor": after} if after else None,
        )


def knock_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KnockResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    object_collections: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = ENDPOINTS_CONFIG[endpoint]

    items: Any
    if endpoint_config.fanout is not None:
        resource = _fanout_items(
            api_key, endpoint, team_id, job_id, db_incremental_field_last_value, should_use_incremental_field
        )
        items = lambda: resource
    elif endpoint == "objects":
        collections = parse_object_collections(object_collections)
        if not collections:
            raise ValueError(NO_OBJECT_COLLECTIONS_ERROR)
        items = lambda: _objects_items(api_key, collections, team_id, job_id, resumable_source_manager)
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
