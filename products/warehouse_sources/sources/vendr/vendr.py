import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.settings import (
    PAGE_SIZE,
    VENDR_ENDPOINTS,
    VendrEndpointConfig,
)

BASE_URL = "https://api.vendr.com"

# Vendr's `pagination` response object isn't documented field-by-field (only that a list
# response carries one), so we don't parse a `total`/`hasMore` field to decide when to stop.
# Stopping once a page comes back shorter than `limit` (or empty) is sufficient and doesn't
# depend on an unconfirmed field name.
_PAGINATOR: PaginatorConfig = {"type": "offset", "limit": PAGE_SIZE, "total_path": None}


@dataclasses.dataclass(frozen=True)
class VendrResumeConfig:
    # Opaque framework checkpoint: an offset position for a top-level endpoint, or per-company
    # fan-out state (current company, completed companies, child offset) for a company-scoped
    # one. Round-tripped into `initial_paginator_state` on resume.
    paginator_state: dict[str, Any]


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "headers": {"Accept": "application/json"},
        # The API key rides in the framework auth config so its value is redacted from logs;
        # only the non-secret Accept header is set above.
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Key", "location": "header"},
        # Vendr's base URL is fixed (not user-configurable), so pin every request - including
        # paginator next-page state - to it and never follow redirects off it.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Confirm the API key is genuine with one cheap, low-privilege list call."""
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        f"{BASE_URL}/v1/catalog/companies?limit=1",
        headers={"X-API-Key": api_key, "Accept": "application/json"},
        allow_redirects=False,
    )


def _get_resource(config: VendrEndpointConfig) -> EndpointResource:
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{config.name}' must use the fan-out path")
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": {
            "path": config.path,
            "params": {"sortBy": config.sort_by, "sortOrder": "asc"},
            "paginator": _PAGINATOR,
            "data_selector": "data",
        },
        "table_format": "delta",
    }


def vendr_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VendrResumeConfig],
) -> SourceResponse:
    config = VENDR_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion. Saved AFTER a page is yielded, so a crash re-fetches from the next position
        # and never skips a page (a re-fetched page is deduped by the write disposition below).
        if state:
            resumable_source_manager.save_state(VendrResumeConfig(paginator_state=dict(state)))

    if config.fanout is not None:
        items = build_dependent_resource(
            endpoint_configs=VENDR_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            child_params_extra={"sortBy": config.sort_by, "sortOrder": "asc"},
            parent_endpoint_extra={"paginator": _PAGINATOR, "data_selector": "data"},
            child_endpoint_extra={"paginator": _PAGINATOR, "data_selector": "data"},
            page_size_param="limit",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        return SourceResponse(
            name=endpoint,
            items=lambda: items,
            primary_keys=config.primary_keys,
        )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [_get_resource(config)],
    }

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        column_hints=resource.column_hints,
    )
