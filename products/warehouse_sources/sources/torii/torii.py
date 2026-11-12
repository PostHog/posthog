import dataclasses
from collections.abc import Iterable, Iterator
from typing import Any, Optional, cast

from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    ClientConfig,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.torii.settings import (
    FANOUT_ENDPOINTS,
    METADATA_ENTITIES,
    PARTITION_KEYS,
    PRIMARY_KEYS,
    TORII_BASE_URL,
    get_resource,
)


@dataclasses.dataclass(frozen=False)
class ToriiResumeConfig:
    # The next page cursor of a list endpoint.
    cursor: str | None = None
    # The framework's fan-out position for AppUsers: finished apps, the app in progress and its cursor.
    fanout_state: dict[str, Any] | None = None


def _client_config(api_key: str, api_version: str) -> ClientConfig:
    return {
        "base_url": TORII_BASE_URL,
        "headers": {"X-API-Version": api_version},
        "auth": {"type": "bearer", "token": api_key},
        "paginator": {"type": "cursor", "cursor_path": "nextCursor", "cursor_param": "cursor"},
    }


def _source_response(endpoint: str, items: Any, column_hints: Any = None) -> SourceResponse:
    partition_key = PARTITION_KEYS.get(endpoint)
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=PRIMARY_KEYS[endpoint],
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
        column_hints=column_hints,
    )


def _app_users_source(
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ToriiResumeConfig],
    api_version: str,
) -> SourceResponse:
    config = FANOUT_ENDPOINTS["AppUsers"]
    assert config.fanout is not None
    parent_config = FANOUT_ENDPOINTS[config.fanout.parent_name]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state = resume.fanout_state if resume is not None else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(ToriiResumeConfig(fanout_state=state))

    resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=FANOUT_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key, api_version),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param="size",
            parent_endpoint_extra={"data_selector": parent_config.data_selector},
            child_endpoint_extra={
                "data_selector": config.data_selector,
                "paginator": {"type": "cursor", "cursor_path": "nextCursor", "cursor_param": "cursor"},
            },
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
            resume_parent_pagination=True,
        ),
    )
    return _source_response(config.name, lambda: resource)


def _field_rows(entity: str, body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError(f"Torii returned an unexpected {entity} metadata response. Expected a JSON object.")
    rows: list[dict[str, Any]] = []
    for key, is_custom in (("predefinedFields", False), ("customFields", True)):
        for field in body.get(key) or []:
            rows.append({**field, "entity": entity, "isCustom": is_custom})
    return rows


def _iter_fields_metadata(
    api_key: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[ToriiResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    client = RESTClient(
        base_url=TORII_BASE_URL,
        headers={"X-API-Version": api_version},
        auth=BearerTokenAuth(token=api_key),
        paginator=SinglePagePaginator(),
    )
    try:
        for entity in METADATA_ENTITIES:
            rows: list[dict[str, Any]] = []
            for page in client.paginate(path=f"/{entity}/metadata"):
                for body in page:
                    rows.extend(_field_rows(entity, body))
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()
    finally:
        client.session.close()


def torii_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ToriiResumeConfig],
    api_version: str,
) -> SourceResponse:
    if endpoint == "AppUsers":
        return _app_users_source(api_key, team_id, job_id, resumable_source_manager, api_version)
    if endpoint == "FieldsMetadata":
        return _source_response(endpoint, lambda: _iter_fields_metadata(api_key, api_version, resumable_source_manager))

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, api_version),
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.cursor:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist while there's a next page to resume to; the Redis TTL handles cleanup on
        # completion. Saved after a page is yielded (see rest_api_resource) so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(ToriiResumeConfig(cursor=str(state["cursor"])))

    result = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(result.name, lambda: result, result.column_hints)


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is genuine. GET /orgs/my is the cheapest authenticated call and needs
    no resource-specific scope."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{TORII_BASE_URL}/orgs/my",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return ok
