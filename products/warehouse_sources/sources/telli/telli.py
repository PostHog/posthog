from collections.abc import Iterator
from typing import Any, cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.telli.settings import BASE_URL, ENDPOINTS


@frozen
class TelliResumeConfig:
    cursor: str | None = None
    completed: bool = False


def validate_credentials(api_key: str, schema_name: str | None = None) -> None:
    endpoint = schema_for_resource(ENDPOINTS, schema_name).endpoint if schema_name is not None else None
    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(token=api_key),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=60,
        capture=False,
    )
    try:
        next(
            client.paginate(
                path=cast(str, endpoint["path"]) if endpoint else "/v1/verify-api-key",
                params={"limit": 1} if endpoint and endpoint.get("params") else None,
                paginator=SinglePagePaginator(),
                data_selector=endpoint["data_selector"] if endpoint else "$",
            )
        )
    finally:
        client.session.close()


def telli_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TelliResumeConfig],
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        if resume and resume.completed:
            return

        def save_state(state: dict[str, Any] | None) -> None:
            resumable_source_manager.save_state(
                TelliResumeConfig(cursor=state["cursor"] if state else None, completed=state is None)
            )

        client: ClientConfig = {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 60,
            # Calls contain transcripts and contacts contain arbitrary properties that generic
            # sample scrubbers cannot reliably redact.
            "capture": False,
        }
        config: RESTAPIConfig = {
            "client": client,
            "resources": [{"name": endpoint, "endpoint": {**settings.endpoint, "data_selector_required": True}}],
        }
        yield from rest_api_resource(
            config,
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            resume_hook=save_state,
            initial_paginator_state={"cursor": resume.cursor} if resume and resume.cursor is not None else None,
        )

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=[settings.primary_key],
        partition_keys=[settings.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=settings.sort_mode,
    )
