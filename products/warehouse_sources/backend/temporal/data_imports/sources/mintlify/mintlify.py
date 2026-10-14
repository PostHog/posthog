from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mintlify import (
    MintlifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.settings import (
    API_VERSION,
    BASE_URL,
    ENDPOINTS,
    HTTP_ERRORS,
    INCREMENTAL_FIELDS,
)


@frozen
class MintlifyResumeConfig:
    paginator_state: dict[str, Any]
    date_to: str
    date_from: str | None = None


class MintlifyOffsetPaginator(OffsetPaginator):
    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        super().update_state(response, data)
        self._has_next_page = response.json()["hasMore"]


def validate_credentials(config: MintlifySourceConfig, schema_name: str | None = None) -> tuple[bool, str | None]:
    endpoint = schema_for_resource(ENDPOINTS, schema_name or "feedback")
    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(config.api_key),
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=30,
    )
    try:
        next(
            client.paginate(
                path=f"/{API_VERSION}/analytics/{quote(config.project_id, safe='')}/{endpoint.path}",
                params={"limit": 1},
                data_selector=endpoint.data_selector,
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status is not None and status in HTTP_ERRORS:
            return False, HTTP_ERRORS[status]
        raise
    return True, None


def mintlify_source(
    config: MintlifySourceConfig,
    endpoint_name: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MintlifyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: datetime | str | None = None,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, endpoint_name)
    incremental = should_use_incremental_field and endpoint_name in INCREMENTAL_FIELDS
    date_from = None
    if incremental and db_incremental_field_last_value is not None:
        date_from = (
            db_incremental_field_last_value.isoformat()
            if isinstance(db_incremental_field_last_value, datetime)
            else db_incremental_field_last_value
        )
    date_to = datetime.now(UTC).isoformat()
    initial_state = None
    if resumable_source_manager.can_resume():
        saved = resumable_source_manager.load_state()
        if saved is not None:
            initial_state = saved.paginator_state
            date_from = saved.date_from
            date_to = saved.date_to

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                MintlifyResumeConfig(paginator_state=state, date_to=date_to, date_from=date_from)
            )

    paginator: BasePaginator
    if endpoint.offset_pagination:
        paginator = MintlifyOffsetPaginator(limit=endpoint.limit, total_path=None, stop_after_empty_page=False)
    else:
        paginator = JSONResponseCursorPaginator(cursor_path="nextCursor", raise_on_repeated_cursor=True)

    # Preserve the time window across pages and retries so aggregate pages use the same bounds.
    params: dict[str, Any] = {"limit": endpoint.limit, "dateTo": date_to}
    if date_from is not None:
        params["dateFrom"] = date_from
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": config.api_key},
            "paginator": paginator,
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 30,
        },
        "resources": [
            {
                "name": endpoint_name,
                "endpoint": {
                    "path": f"/{API_VERSION}/analytics/{quote(config.project_id, safe='')}/{endpoint.path}",
                    "params": params,
                    "data_selector": endpoint.data_selector,
                    "data_selector_required": True,
                },
            }
        ],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=endpoint_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        # Mintlify does not guarantee ascending order, so defer the watermark until extraction completes.
        sort_mode="desc" if incremental else None,
        partition_keys=["timestamp"] if endpoint_name == "assistant_conversations" else None,
        partition_mode="datetime" if endpoint_name == "assistant_conversations" else None,
        partition_format="month" if endpoint_name == "assistant_conversations" else None,
    )
