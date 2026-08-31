import dataclasses
from collections.abc import Iterable
from typing import Any, Optional, cast

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
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.settings import (
    PAGE_SIZE,
    SMARTSHEET_ENDPOINTS,
    SmartsheetEndpointConfig,
)

SMARTSHEET_BASE_URL = "https://api.smartsheet.com/2.0"


@dataclasses.dataclass
class SmartsheetResumeConfig:
    # 1-based number of the next unfetched page — Smartsheet list endpoints page with `page`.
    next_page: int


def _non_secret_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from raised
    # errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _client_config(access_token: str) -> ClientConfig:
    return {
        "base_url": SMARTSHEET_BASE_URL,
        "headers": _non_secret_headers(),
        "auth": {"type": "bearer", "token": access_token},
    }


def _primary_keys(config: SmartsheetEndpointConfig) -> list[str]:
    return config.primary_key if isinstance(config.primary_key, list) else [config.primary_key]


def _report_fanout_source(
    access_token: str,
    endpoint: str,
    config: SmartsheetEndpointConfig,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    """Fan out from each report to its per-report structure (columns or scope).

    The `reports` parent walks the account's reports page-by-page; each child request resolves a
    report id into its path and pages by token (`lastKey`) until Smartsheet omits the key. These
    endpoints carry no timestamp, so the child full-refreshes and resume is not wired.
    """
    assert config.fanout is not None
    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=SMARTSHEET_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(access_token),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Parent uses `pageSize`, child uses `maxItems`; both are supplied through the fan-out
            # config's parent_params / child_params rather than a shared page-size param.
            page_size_param=None,
            parent_endpoint_extra={
                "paginator": PageNumberPaginator(base_page=1, page_param="page", total_path="totalPages"),
                "data_selector": "data",
            },
            child_endpoint_extra={
                "paginator": JSONResponseCursorPaginator(cursor_path="lastKey", cursor_param="lastKey"),
                "data_selector": "data",
            },
        ),
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: dependent_resource,
        primary_keys=_primary_keys(config),
        partition_count=1,
        partition_size=1,
    )


def smartsheet_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartsheetResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SMARTSHEET_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _report_fanout_source(access_token, endpoint, config, team_id, job_id)

    client_config = _client_config(access_token)
    # Smartsheet returns the grand total of PAGES in `totalPages`; stop after the last one.
    client_config["paginator"] = PageNumberPaginator(base_page=1, page_param="page", total_path="totalPages")

    rest_config: RESTAPIConfig = {
        "client": client_config,
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"pageSize": PAGE_SIZE},
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(SmartsheetResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=_primary_keys(config),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(access_token: str) -> bool:
    """Confirm the access token is valid. ``/users/me`` is a cheap authenticated probe
    that works for any valid token regardless of granted scopes."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{SMARTSHEET_BASE_URL}/users/me",
        headers={"Authorization": f"Bearer {access_token}", **_non_secret_headers()},
    )
    return ok
