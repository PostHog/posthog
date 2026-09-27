import dataclasses
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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.settings import (
    FIREHYDRANT_ENDPOINTS,
    PAGE_SIZE,
)

# FireHydrant accounts are region-pinned: US accounts live on api.firehydrant.io, EU accounts on the
# data-residency host. The stored API key only authenticates against its own region's host.
BASE_URLS: dict[str, str] = {
    "us": "https://api.firehydrant.io",
    "eu": "https://api.eu.firehydrant.io",
}
DEFAULT_REGION = "us"


@dataclasses.dataclass
class FireHydrantResumeConfig:
    # Opaque framework checkpoint: `{"cursor": <next page>}` for a top-level endpoint (FireHydrant
    # paginates with `page` / `per_page` and returns `pagination.next`, or null on the last page), or
    # the fan-out manager's `{"completed": [...], "current": ..., "child_state": {...}}` for an
    # endpoint walked per parent — round-tripped into `initial_paginator_state` on resume.
    # Defaulted so state written in an older shape resumes from the start instead of failing.
    paginator_state: dict[str, Any] = dataclasses.field(default_factory=dict)


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def base_url_for_region(region: str | None) -> str:
    return BASE_URLS.get((region or DEFAULT_REGION).lower(), BASE_URLS[DEFAULT_REGION])


def validate_credentials(api_key: str, region: str | None = None) -> tuple[bool, str | None]:
    """Probe the authenticated ping endpoint to confirm the token is genuine.

    Only a 200 proves the key is real and usable. A 403 means the request reached FireHydrant but the
    token lacks the required permissions — we surface that as a permissions failure rather than
    silently accepting an unverified key (which would let a broken source register as authenticated).
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url_for_region(region)}/v1/ping",
        headers=_get_headers(api_key),
    )
    if ok:
        return True, None
    if status is None:
        return False, "Could not reach the FireHydrant API. Please try again."
    if status == 401:
        return False, "Invalid FireHydrant API key"
    if status == 403:
        return (
            False,
            "Your FireHydrant API key is missing the permissions needed to access this data. "
            "Grant the required permissions in your FireHydrant settings, then reconnect.",
        )
    return False, f"FireHydrant API returned an unexpected status: {status}"


def _client_config(api_key: str, region: str | None) -> ClientConfig:
    return {
        "base_url": base_url_for_region(region),
        # Auth (Bearer) is supplied via the framework auth config so the token is redacted from
        # logs; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        # FireHydrant returns the next page number in `pagination.next` (null on the last page);
        # inject it as the `page` query param. Termination is `pagination.next` being falsy —
        # endpoints returning a single unpaginated response carry no `pagination`, so they stop
        # after one page.
        "paginator": JSONResponseCursorPaginator(cursor_path="pagination.next", cursor_param="page"),
    }


def firehydrant_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FireHydrantResumeConfig],
    region: str | None = None,
) -> SourceResponse:
    config = FIREHYDRANT_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.paginator_state:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there is somewhere left to resume to; save AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if state:
            resumable_source_manager.save_state(FireHydrantResumeConfig(paginator_state=dict(state)))

    resource: Resource
    if config.fanout is not None:
        # Neither parent nor child offers a server-side time filter, so every sync walks the parent
        # list and re-fetches the child per parent; that is inherent to the API.
        resource = cast(
            Resource,
            build_dependent_resource(
                endpoint_configs=cast(Any, FIREHYDRANT_ENDPOINTS),
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=_client_config(api_key, region),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                page_size_param="per_page",
                parent_endpoint_extra={"data_selector": "data"},
                child_endpoint_extra={"data_selector": "data"},
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_paginator_state,
            ),
        )
    else:
        rest_config: RESTAPIConfig = {
            "client": _client_config(api_key, region),
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": {"per_page": PAGE_SIZE},
                        # Paginated endpoints wrap rows in a top-level `data` array. A missing/empty
                        # `data` key degrades to zero rows (not required) so an endpoint with nothing
                        # to return ends cleanly rather than raising.
                        "data_selector": "data",
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
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
