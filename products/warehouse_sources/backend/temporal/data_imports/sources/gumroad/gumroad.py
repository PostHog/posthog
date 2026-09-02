import dataclasses
from collections.abc import Callable, Iterable
from typing import Any, Optional, cast

import requests

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
    BasePaginator,
    JSONResponseCursorPaginator,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.settings import (
    GUMROAD_BASE_URL,
    GUMROAD_ENDPOINTS,
    INCREMENTAL_START_PARAM,
    PAGE_KEY_CURSOR_PATH,
    PAGE_KEY_PARAM,
    GumroadEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30.0


@dataclasses.dataclass
class GumroadResumeConfig:
    """Paginator checkpoint — the `page_key` cursor of the page we have not yet fetched."""

    page_key: str


def _format_gumroad_date(value: Any) -> str:
    """Format the incremental watermark for Gumroad's `after` filter (YYYY-MM-DD).

    Gumroad only accepts whole dates and filters on `created_at >= <date>`, so truncating to
    the day rounds the lower bound down: a sync re-reads the watermark day rather than
    skipping rows created later on it. The merge dedupes the overlap on the primary key.
    """
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime("%Y-%m-%d")


def _gumroad_incremental_window(cursor_path: str) -> IncrementalConfig:
    return {
        "cursor_path": cursor_path,
        "start_param": INCREMENTAL_START_PARAM,
        "initial_value": "1970-01-01",
        "convert": _format_gumroad_date,
    }


def _page_key_paginator() -> JSONResponseCursorPaginator:
    return JSONResponseCursorPaginator(cursor_path=PAGE_KEY_CURSOR_PATH, cursor_param=PAGE_KEY_PARAM)


def _paginator_for(config: GumroadEndpointConfig) -> BasePaginator:
    return _page_key_paginator() if config.paginated else SinglePagePaginator()


def _rest_api_client_config(access_token: str) -> ClientConfig:
    return {
        "base_url": GUMROAD_BASE_URL,
        "auth": {"type": "bearer", "token": access_token},
        "headers": {"Accept": "application/json"},
        # `capture=False`: sales and subscriber rows carry redeemable `license_key` values, and
        # reviews and custom fields carry arbitrary customer text the name-based sample scrubbers
        # can't redact, so keep every response body out of HTTP sample storage. Requests stay
        # metered and logged.
        "session": make_tracked_session(redact_values=(access_token,), capture=False, allow_redirects=False),
        # Pin every request (and the bearer header) to the Gumroad host and refuse to follow a
        # 3xx, so a server-side redirect can never replay the credential off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field_name: str | None = None,
) -> EndpointResource:
    config = GUMROAD_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": dict(config.extra_params),
        "data_selector": config.data_selector,
        # Every documented Gumroad response wraps its rows in a named key, so a body without it
        # means the shape changed — fail loud rather than silently syncing 0 rows.
        "data_selector_required": True,
        "paginator": _paginator_for(config),
    }

    use_incremental = should_use_incremental_field and bool(config.incremental_fields)
    if use_incremental:
        endpoint_config["incremental"] = _gumroad_incremental_window(
            incremental_field_name or config.default_incremental_field or "created_at"
        )

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(
    endpoint_config: GumroadEndpointConfig,
    items_fn: Callable[[], Iterable[Any]],
) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key,
        # Every Gumroad list endpoint orders `created_at DESC, id DESC`, and there is no
        # parameter to reverse it, so rows always arrive newest-first.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def gumroad_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: Optional[ResumableSourceManager[GumroadResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = GUMROAD_ENDPOINTS[endpoint]

    if endpoint_config.fanout:
        parent_config = GUMROAD_ENDPOINTS[endpoint_config.fanout.parent_name]
        # Dependent resources don't currently support resume in the rest_source framework;
        # the manager is intentionally not threaded into this path.
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=GUMROAD_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=dataclasses.replace(endpoint_config.fanout, child_params=dict(endpoint_config.extra_params)),
                client_config=_rest_api_client_config(access_token),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                incremental_config_factory=_gumroad_incremental_window,
                # Gumroad list endpoints take no page-size parameter; the server fixes it.
                page_size_param=None,
                parent_endpoint_extra={
                    "paginator": _paginator_for(parent_config),
                    "data_selector": parent_config.data_selector,
                    "data_selector_required": True,
                },
                child_endpoint_extra={
                    "paginator": _paginator_for(endpoint_config),
                    "data_selector": endpoint_config.data_selector,
                    "data_selector_required": True,
                },
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _rest_api_client_config(access_token),
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None
    if resumable_source_manager is not None:
        if resumable_source_manager.can_resume():
            resume_config = resumable_source_manager.load_state()
            if resume_config is not None:
                initial_paginator_state = {"cursor": resume_config.page_key}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only while there is another page to resume to; the Redis TTL cleans up
            # on completion.
            if resumable_source_manager is None or not state:
                return
            cursor = state.get("cursor")
            if cursor:
                resumable_source_manager.save_state(GumroadResumeConfig(page_key=str(cursor)))

        resume_hook = save_checkpoint

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)


def _get(access_token: str, path: str, params: dict[str, str] | None = None) -> int | None:
    """Probe `path` and return the HTTP status code, or None if the request never completed.

    Transport failures (DNS error, connection reset, timeout before any response) are not
    permission problems, so they surface as None and let each caller decide how to treat an
    unreachable host. `capture=False` keeps the real `/v2/user` and `/v2/sales` probe responses
    out of HTTP sample storage.
    """
    try:
        response = make_tracked_session(redact_values=(access_token,), capture=False, allow_redirects=False).get(
            f"{GUMROAD_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return None
    return response.status_code


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    # `/v2/user` is readable by every scope Gumroad can issue, so a non-200 here means the token
    # itself is bad rather than under-scoped.
    status_code = _get(access_token, "/v2/user")
    if status_code is None:
        return False, "Couldn't reach Gumroad to validate the access token. Check your connection and try again."
    if status_code == 200:
        return True, None
    if status_code in (401, 403):
        return (
            False,
            "Gumroad rejected the access token. Generate a new one under Settings > Advanced > "
            "Applications and reconnect.",
        )
    return False, f"Gumroad API returned an unexpected status code: {status_code}"


def check_endpoint_permission(access_token: str, path: str) -> bool:
    """Whether the token can read `path`. Only a 403 counts as a missing scope; a transport failure
    leaves the probe unable to tell, so we treat the endpoint as reachable rather than denied."""
    return _get(access_token, path) != 403
