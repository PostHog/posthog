import dataclasses
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.settings import (
    ENDPOINTS_CONFIG,
    SEQUENZY_BASE_URL,
    SequenzyEndpointConfig,
)


@frozen
class SequenzyResumeConfig:
    """Snapshot of the framework paginator's resume state.

    Exactly one field is set, matching the endpoint's pagination style: `cursor` for
    subscribers, `offset` for campaigns/sequences, `page` for email metrics. The field
    names mirror the keys of the framework paginators' `get_resume_state` dicts so the
    two shapes convert without a mapping table.
    """

    cursor: str | None = None
    offset: int | None = None
    page: int | None = None


def _paginator_state(resume: SequenzyResumeConfig) -> Optional[dict[str, Any]]:
    state = {key: value for key, value in dataclasses.asdict(resume).items() if value is not None}
    return state or None


def _make_paginator(config: SequenzyEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        return JSONResponseCursorPaginator(cursor_path="pagination.nextCursor", cursor_param="cursor")
    if config.pagination == "offset":
        assert config.page_size is not None
        return OffsetPaginator(
            limit=config.page_size,
            offset_param="offset",
            limit_param="limit",
            total_path="pagination.total",
        )
    if config.pagination == "page":
        return PageNumberPaginator(base_page=1, page_param="page", total_path="pagination.totalPages")
    return SinglePagePaginator()


def get_resource(name: str) -> EndpointResource:
    config = ENDPOINTS_CONFIG[name]

    params: dict[str, Any] = dict(config.params)
    # The cursor and page-number paginators only inject their own pagination param, so
    # the page size rides along as a plain query param. The offset paginator sends
    # `limit` itself.
    if config.pagination in ("cursor", "page") and config.page_size is not None:
        params["limit"] = config.page_size

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": {
            "path": config.path,
            "data_selector": config.data_selector,
            "params": params,
            "paginator": _make_paginator(config),
        },
        "table_format": "delta",
    }


def sequenzy_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SequenzyResumeConfig],
    company_id: str | None = None,
) -> SourceResponse:
    endpoint_config = ENDPOINTS_CONFIG[endpoint]

    headers = {"Accept": "application/json"}
    if company_id:
        # Account API keys (seq_user_) span workspaces and need the target workspace
        # named per request; workspace keys (seq_live_) are already bound to one.
        headers["x-company-id"] = company_id

    config: RESTAPIConfig = {
        "client": {
            "base_url": SEQUENZY_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": headers,
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = _paginator_state(resume_config)

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if not state:
            return
        resumable_source_manager.save_state(
            SequenzyResumeConfig(
                cursor=state.get("cursor"),
                offset=state.get("offset"),
                page=state.get("page"),
            )
        )

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(endpoint_config.primary_keys),
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # The paginated collections come back newest-first with no ascending option, and
        # the single-page collections document no order, so never claim "asc".
        sort_mode="desc",
    )


def validate_credentials(api_key: str, company_id: str | None = None) -> tuple[bool, str | None]:
    # A non-ASCII key cannot be encoded into the Authorization header (requests uses
    # latin-1), which would otherwise surface a raw UnicodeEncodeError to the user.
    if not api_key.isascii():
        return (
            False,
            "Your Sequenzy API key contains an unsupported character (for example an invisible one "
            "pasted from another app). Retype it by hand and try again.",
        )

    headers = {"Authorization": f"Bearer {api_key}"}
    if company_id:
        headers["x-company-id"] = company_id

    # Documented by Sequenzy as the credential-validation endpoint for integrations.
    res = make_tracked_session(redact_values=(api_key,)).get(
        f"{SEQUENZY_BASE_URL}/subscribers/me",
        headers=headers,
        timeout=10,
    )
    if res.status_code == 200:
        return True, None
    if res.status_code == 401:
        return False, "Invalid API key. Check the key in Sequenzy under Settings > API Keys and try again."
    if res.status_code == 403:
        return (
            False,
            "Sequenzy could not find that workspace. If you use an account API key (seq_user_), "
            "enter the company ID of the workspace to sync.",
        )
    return False, f"Sequenzy returned an unexpected response (HTTP {res.status_code}). Try again later."
