import dataclasses
from typing import Any, Optional
from urllib.parse import quote

from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.settings import (
    ENDPOINTS,
    MAX_PAGE,
    PAGE_SIZE,
    PUBLICATION_PATH_PLACEHOLDER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BASE_HOST = "https://api.beehiiv.com"
REQUEST_TIMEOUT_SECONDS = 30.0


@dataclasses.dataclass
class BeehiivResumeConfig:
    # Opaque paginator snapshot: `{"cursor": ...}` for cursor endpoints, `{"page": ...}` for
    # paged ones. The manager is namespaced per endpoint so the two shapes can't cross over.
    paginator_state: dict[str, Any]


def base_url(api_version: str) -> str:
    return f"{BASE_HOST}/{api_version}"


def resolve_path(path: str, publication_id: str) -> str:
    return path.replace(PUBLICATION_PATH_PLACEHOLDER, quote(publication_id, safe=""))


def build_paginator(endpoint: str) -> BasePaginator:
    config = ENDPOINTS[endpoint]
    if config.pagination == "cursor":
        return JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")
    return PageNumberPaginator(
        base_page=1,
        page_param="page",
        total_path="total_pages",
        maximum_page=MAX_PAGE,
    )


def get_resource(endpoint: str, publication_id: str) -> EndpointResource:
    config = ENDPOINTS[endpoint]

    params: dict[str, Any] = {"limit": PAGE_SIZE, **config.params}

    endpoint_config: Endpoint = {
        "path": resolve_path(config.path, publication_id),
        "params": params,
        "data_selector": "data",
        # Every beehiiv list response wraps rows in `data`; a body without it means the shape
        # changed, and syncing 0 rows silently would look like an empty publication.
        "data_selector_required": True,
        "paginator": build_paginator(endpoint),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def beehiiv_source(
    api_key: str,
    publication_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[BeehiivResumeConfig],
) -> SourceResponse:
    endpoint_config = ENDPOINTS[endpoint]

    client_config: ClientConfig = {
        "base_url": base_url(api_version),
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint, publication_id)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.paginator_state:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(BeehiivResumeConfig(paginator_state=state))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partitioned = endpoint_config.partition_key is not None

    return SourceResponse(
        name=endpoint_config.name,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1 if partitioned else None,
        partition_size=1 if partitioned else None,
        partition_mode="datetime" if partitioned else None,
        partition_format="week" if partitioned else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(
    api_key: str,
    publication_id: str,
    api_version: str,
    *,
    allow_missing_scope: bool,
) -> tuple[bool, str | None]:
    """Probe the configured publication with the API key.

    ``allow_missing_scope`` accepts a 403 as a valid key: beehiiv API keys are scoped per
    resource, so a key that can read subscriptions but not publications is still usable and
    must not block source creation.
    """
    url = f"{base_url(api_version)}/publications/{quote(publication_id, safe='')}"
    session = make_tracked_session(redact_values=(api_key,))
    try:
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "beehiiv rejected the API key. Create a new key in Settings > Integrations > API."
    if response.status_code == 403:
        if allow_missing_scope:
            return True, None
        return False, "The API key does not have permission to read this publication."
    if response.status_code == 404:
        return False, "No publication found with that ID. Check the publication ID in your beehiiv settings."
    return False, f"beehiiv returned HTTP {response.status_code}"
