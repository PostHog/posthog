import re
import dataclasses
from collections.abc import Callable, Iterable
from typing import Any, Optional, cast

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.settings import (
    CLOUDSMITH_BASE_URL,
    CLOUDSMITH_ENDPOINTS,
    PAGE_TOTAL_HEADER,
    CloudsmithEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Cloudsmith workspace (namespace) slugs, per the API schema's slug pattern. Enforced before the
# slug is interpolated into a request path.
WORKSPACE_SLUG_RE = re.compile(r"^[-a-zA-Z0-9_]+$")

INVALID_WORKSPACE_ERROR = "Enter a valid Cloudsmith workspace slug (letters, numbers, dashes and underscores only)."

# The lower bound sent on a first incremental sync: old enough to select every package, and a
# value the `uploaded` filter parses (a bare `None` would be rejected as an unknown expression).
INCREMENTAL_INITIAL_VALUE = "1970-01-01T00:00:00Z"


@dataclasses.dataclass
class CloudsmithResumeConfig:
    # Opaque framework checkpoint (the page number for top-level endpoints, per-parent fan-out
    # state for repository-scoped ones), round-tripped into `initial_paginator_state` on resume.
    paginator_state: dict[str, Any]


class CloudsmithPaginator(PageNumberPaginator):
    """Page-number paginator that stops on Cloudsmith's page-count response header.

    Cloudsmith reports the number of pages in `X-Pagination-PageTotal` rather than the response
    body, and answers a page past the last one with a 404 rather than an empty page - so the
    inherited empty-page check would only fire after a request that has already failed.
    """

    def __init__(self, page_size: int, page: int = 1) -> None:
        super().__init__(base_page=1, page=page, page_param="page")
        self.page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        self.page += 1

        raw_page_total = response.headers.get(PAGE_TOTAL_HEADER)
        if raw_page_total is not None:
            try:
                self._has_next_page = self.page <= int(raw_page_total)
                return
            except ValueError:
                pass

        # Header absent or unparseable: fall back to stopping on a short page, since asking for
        # the page after the last one is an error rather than an empty page.
        self._has_next_page = len(data) >= self.page_size

    def __str__(self) -> str:
        return f"CloudsmithPaginator(page={self.page}, page_size={self.page_size})"


def _format_uploaded_filter(value: Any) -> str:
    """Build the `query` search expression that bounds a package list by upload time.

    Truncates to whole seconds, which rounds the lower bound *down* - so a sync re-reads at most
    a few boundary packages (the merge dedupes them) rather than skipping any package uploaded in
    the same second as the watermark.
    """
    normalized_value = coerce_datetime_to_utc(value)
    formatted = normalized_value.strftime("%Y-%m-%dT%H:%M:%SZ") if normalized_value is not None else str(value)
    return f"uploaded:>={formatted}"


def _cloudsmith_incremental_window(cursor_path: str) -> IncrementalConfig:
    # `query` is a server-side search filter that applies to every page, so pagination stays
    # bounded by the filtered set and terminates at the watermark.
    return {
        "cursor_path": cursor_path,
        "start_param": "query",
        "initial_value": INCREMENTAL_INITIAL_VALUE,
        "convert": _format_uploaded_filter,
    }


def _drop_fields(fields: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        for name in fields:
            row.pop(name, None)
        return row

    return _mapper


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": CLOUDSMITH_BASE_URL,
        "headers": {"Accept": "application/json"},
        # Cloudsmith API keys authenticate via the `X-Api-Key` header (HTTP basic also works, but
        # the header is the documented default and keeps the key out of the URL userinfo).
        "auth": {"type": "api_key", "name": "X-Api-Key", "api_key": api_key, "location": "header"},
        # `capture=False` keeps raw responses out of HTTP sample storage: member emails, audit-log
        # IP addresses and webhook targets ride in these bodies, and the name-based scrubber can't
        # recognise them. Traffic is still metered and logged, with the API key redacted.
        "session": make_tracked_session(redact_values=(api_key,), capture=False),
    }


def validate_credentials(api_key: str, workspace: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Confirm the API key is genuine and the workspace is reachable with one cheap probe.

    `GET /namespaces/{slug}/` validates both halves of the config at once: a bad key is a 401 and
    a workspace the key cannot see is a 404.
    """
    if not WORKSPACE_SLUG_RE.match(workspace):
        return False, INVALID_WORKSPACE_ERROR

    response = make_tracked_session(redact_values=(api_key,), capture=False).get(
        f"{CLOUDSMITH_BASE_URL}/namespaces/{workspace}/",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        timeout=10,
    )
    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Cloudsmith rejected the API key. Check the key in your Cloudsmith user settings and try again."
    if response.status_code == 403:
        # A Cloudsmith API key inherits its owner's permissions, which vary per repository. Let
        # source creation through so the user can still sync the tables they do have access to,
        # and only fail when a specific table is being checked.
        if schema_name is None:
            return True, None
        return False, "Your Cloudsmith API key does not have permission to read this data."
    if response.status_code == 404:
        return False, f"Cloudsmith workspace '{workspace}' was not found, or this API key cannot see it."
    return False, f"Cloudsmith returned an unexpected response (HTTP {response.status_code})."


def get_resource(config: CloudsmithEndpointConfig, workspace: str) -> EndpointResource:
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{config.name}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path.replace("{owner}", workspace),
        "params": {"page_size": config.page_size, **config.params},
        "paginator": CloudsmithPaginator(page_size=config.page_size),
        # Every Cloudsmith list endpoint returns a bare JSON array; anything else is a shape
        # change we would rather fail on than silently sync as a single row.
        "data_selector_required": True,
    }

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }
    if config.strip_fields:
        resource["data_map"] = _drop_fields(config.strip_fields)
    return resource


def _make_source_response(config: CloudsmithEndpointConfig, items_fn: Callable[[], Any]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_key if isinstance(config.primary_key, list) else [config.primary_key],
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def cloudsmith_source(
    api_key: str,
    workspace: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloudsmithResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    if not WORKSPACE_SLUG_RE.match(workspace):
        raise ValueError(INVALID_WORKSPACE_ERROR)

    endpoint_config = CLOUDSMITH_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's somewhere to resume to; the Redis TTL handles cleanup.
        if state:
            resumable_source_manager.save_state(CloudsmithResumeConfig(paginator_state=dict(state)))

    if endpoint_config.fanout is not None:
        parent_config = CLOUDSMITH_ENDPOINTS[endpoint_config.fanout.parent_name]
        dependent_resource: Any = build_dependent_resource(
            endpoint_configs=CLOUDSMITH_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=_client_config(api_key),
            path_format_values={"owner": workspace},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            incremental_config_factory=_cloudsmith_incremental_window,
            page_size_param="page_size",
            parent_endpoint_extra={
                "paginator": CloudsmithPaginator(page_size=parent_config.page_size),
                "data_selector_required": True,
            },
            child_endpoint_extra={
                "paginator": CloudsmithPaginator(page_size=endpoint_config.page_size),
                "data_selector_required": True,
            },
            child_params_extra=dict(endpoint_config.params) if endpoint_config.params else None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        if endpoint_config.strip_fields:
            dependent_resource = dependent_resource.add_map(_drop_fields(endpoint_config.strip_fields))
        items = cast(Iterable[Any], dependent_resource)
        return _make_source_response(endpoint_config, lambda: items)

    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint_config, workspace)],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)
