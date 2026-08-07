import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.settings import (
    POSTSCRIPT_BASE_URL,
    POSTSCRIPT_ENDPOINTS,
    PostscriptEndpointConfig,
)


@dataclasses.dataclass
class PostscriptResumeConfig:
    page: int


def _format_postscript_datetime(value: Any) -> str:
    """Format the incremental watermark for Postscript's `<field>__gte` filters.

    Truncating to whole seconds rounds the lower bound down, and `__gte` is inclusive, so a
    resumed sync re-reads a few boundary rows (the merge dedupes them on `id`) instead of
    skipping any.
    """
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _postscript_incremental_window(cursor_path: str) -> IncrementalConfig:
    return {
        "cursor_path": cursor_path,
        "start_param": f"{cursor_path}__gte",
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _format_postscript_datetime,
    }


def _rest_api_client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": POSTSCRIPT_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        # Pin every request to the Postscript host and refuse to follow a 3xx, so a redirect
        # can never replay the bearer token off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _page_paginator() -> PageNumberPaginator:
    # Postscript pages are 1-based and the body reports `page_info.total_pages`, so pagination
    # stops after the last page instead of paying an extra empty-page request.
    return PageNumberPaginator(base_page=1, page_param="page", total_path="page_info.total_pages")


def _resolve_cursor_field(config: PostscriptEndpointConfig, requested: str | None) -> str:
    """Pick the incremental cursor, honoring the user's choice when we advertise it.

    A field we never advertised has no matching `__gte` filter or `sort` value, so the API
    would 400 on it; fall back to the endpoint's default rather than failing the sync.
    """
    advertised = {f["field"] for f in config.incremental_fields}
    if requested in advertised:
        return str(requested)
    return str(config.default_incremental_field)


def get_resource(
    endpoint: str,
    api_version: str,
    should_use_incremental_field: bool,
    incremental_field_name: str | None = None,
) -> EndpointResource:
    config = POSTSCRIPT_ENDPOINTS[endpoint]
    use_incremental = should_use_incremental_field and bool(config.incremental_fields)

    params: dict[str, Any] = {}
    if config.stable_sort_field is not None:
        # The sort field must match the filtered column so rows arrive in watermark order.
        sort_field = _resolve_cursor_field(config, incremental_field_name) if use_incremental else None
        params["sort"] = f"{sort_field or config.stable_sort_field}__asc"

    endpoint_config: Endpoint = {
        "path": config.path_template.format(api_version=api_version),
        "params": params,
        "data_selector": config.data_selector,
        # The wrapper key is documented on every list response, so a body without it means the
        # API shape changed — fail loud rather than silently syncing 0 rows. A wholly empty
        # body still counts as a valid 0-row page: it isn't documented whether a shop with no
        # keywords gets `{"keywords": []}` or `{}`, and failing that shop's sync would be worse
        # than accepting the empty page.
        "data_selector_required": True,
        "data_selector_empty_ok": True,
        "paginator": _page_paginator() if config.paginated else SinglePagePaginator(),
    }
    if use_incremental:
        endpoint_config["incremental"] = _postscript_incremental_window(
            _resolve_cursor_field(config, incremental_field_name)
        )

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, str | None]:
    response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
        f"{POSTSCRIPT_BASE_URL}/api/{api_version}/subscribers",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        params={"page": 1},
        timeout=10,
    )
    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Postscript API key"
    if response.status_code == 403:
        return (
            False,
            "Postscript rejected the API key. Use a shop Private API Key from Settings > "
            "Integrations > API in your Postscript account. Partner keys are not supported.",
        )
    return False, f"Postscript API returned an unexpected status code: {response.status_code}"


def postscript_source(
    api_key: str,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: Optional[ResumableSourceManager[PostscriptResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = POSTSCRIPT_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": _rest_api_client_config(api_key),
        "resource_defaults": {},
        "resources": [get_resource(endpoint, api_version, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager is not None and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while there is another page to resume to; the Redis TTL cleans up on
        # completion.
        if resumable_source_manager is None or not state or state.get("page") is None:
            return
        resumable_source_manager.save_state(PostscriptResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint if resumable_source_manager is not None else None,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint_config.name,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_key,
        # Every paginated request pins `sort=<field>__asc`, so rows arrive oldest-first.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
