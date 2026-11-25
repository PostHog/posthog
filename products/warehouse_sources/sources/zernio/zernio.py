from typing import Any, Optional

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    EndpointResource,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    format_datetime,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.zernio.settings import FEED_START, ZERNIO_ENDPOINTS, ZernioEndpointConfig

ZERNIO_HOST = "https://zernio.com/api"
REQUEST_TIMEOUT_SECONDS = 60.0


@frozen
class ZernioResumeConfig:
    # The paginator snapshot: `{"cursor": ...}`, `{"offset": ...}` or `{"page": ...}`. The manager
    # keeps one slot per table, so the shapes never mix.
    paginator_state: dict[str, Any]


def base_url(api_version: str) -> str:
    return f"{ZERNIO_HOST}/{api_version}"


def build_paginator(config: ZernioEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        return JSONResponseCursorPaginator(cursor_path="pagination.nextCursor", cursor_param="cursor")
    if config.pagination == "skip":
        return OffsetPaginator(
            limit=config.page_size,
            offset_param="skip",
            limit_param="limit",
            total_path=config.total_path,
        )
    if config.pagination == "page":
        return PageNumberPaginator(base_page=1, page_param="page", total_path="pagination.pages")
    return SinglePagePaginator()


def build_params(
    config: ZernioEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.params)
    if config.pagination in ("cursor", "page"):
        params["limit"] = config.page_size

    if config.updated_since_param is not None:
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            params[config.updated_since_param] = format_datetime(db_incremental_field_last_value, "iso_z_millis")
        elif config.always_send_updated_since:
            params[config.updated_since_param] = FEED_START

    return params


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    config = ZERNIO_ENDPOINTS[endpoint]
    use_incremental = should_use_incremental_field and bool(config.incremental_fields)

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": {
            "path": config.path,
            "params": build_params(config, use_incremental, db_incremental_field_last_value),
            "data_selector": config.data_selector,
            # Every Zernio list wraps its rows in a named key. A body without it means the shape
            # changed, and an empty table would hide that.
            "data_selector_required": True,
            "paginator": build_paginator(config),
        },
        "table_format": "delta",
    }


def zernio_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[ZernioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ZERNIO_ENDPOINTS[endpoint]

    client_config: ClientConfig = {
        "base_url": base_url(api_version),
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [get_resource(endpoint, should_use_incremental_field, db_incremental_field_last_value)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.paginator_state:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(ZernioResumeConfig(paginator_state=state))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partitioned = config.partition_key is not None
    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1 if partitioned else None,
        partition_size=1 if partitioned else None,
        partition_mode="datetime" if partitioned else None,
        partition_format="month" if partitioned else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, str | None]:
    # `/auth/verify` checks the key without reading any data, so a key scoped to some profiles
    # still passes.
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url(api_version)}/auth/verify",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )

    if status == 200:
        return True, None
    if status == 401:
        return (
            False,
            "Zernio didn't accept this API key. Create a new key on the API keys page of the Zernio dashboard.",
        )
    if status is None:
        return False, "Couldn't reach the Zernio API. Try again in a few minutes."
    return False, f"The Zernio API returned an unexpected status code ({status}). Try again in a few minutes."
