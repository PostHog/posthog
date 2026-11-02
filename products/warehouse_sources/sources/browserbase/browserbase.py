from collections.abc import Callable, Iterable
from typing import Any, cast

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.settings import (
    BROWSERBASE_ENDPOINTS,
    CURSOR_PARAM,
    CURSOR_PATH,
    MAX_PAGE_SIZE,
    BrowserbaseEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    BasePaginator,
    ClientConfig,
    Endpoint,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BROWSERBASE_BASE_URL = "https://api.browserbase.com/v1"


def _make_session(api_key: str) -> requests.Session:
    # `redact_values` masks the key in tracked logs/samples. `capture=False` keeps response bodies
    # out of HTTP sample storage — session objects carry arbitrary `userMetadata` (and session logs
    # carry the raw CDP request/response bodies of whatever the browser did) that the name-based
    # sample scrubbers can't recognise. Requests are still metered and logged (status + url).
    return make_tracked_session(redact_values=(api_key,), capture=False)


def validate_credentials(api_key: str) -> bool:
    # `/projects` is the cheapest authenticated probe: a project-scoped key can always list at least
    # its own project, so a 200 confirms the key is genuine without needing any session data.
    ok, _status = validate_via_probe(
        lambda: _make_session(api_key),
        f"{BROWSERBASE_BASE_URL}/projects",
        headers={"X-BB-API-Key": api_key, "Accept": "application/json"},
    )
    return ok


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BROWSERBASE_BASE_URL,
        "headers": {"Accept": "application/json"},
        # Framework auth (not a hand-built header) so the key is redacted wherever it surfaces.
        "auth": {"type": "api_key", "name": "X-BB-API-Key", "api_key": api_key, "location": "header"},
        "session": _make_session(api_key),
    }


def _paginator_for(config: BrowserbaseEndpointConfig) -> BasePaginator:
    if config.paginated:
        return JSONResponseCursorPaginator(cursor_path=CURSOR_PATH, cursor_param=CURSOR_PARAM)
    # The rest of Browserbase's list endpoints take no pagination, page, or cursor params, so a
    # single request yields the whole collection.
    return SinglePagePaginator()


def _endpoint_extra(config: BrowserbaseEndpointConfig) -> Endpoint:
    extra: Endpoint = {
        "paginator": _paginator_for(config),
        # The row list is the whole body (or the envelope's `data` key); anything else is an
        # unexpected/error shape. Fail loud instead of finishing "successfully" with zero rows.
        # An endpoint that answers with a single object has no list to check.
        "data_selector_required": not config.returns_object,
    }
    if config.data_selector:
        extra["data_selector"] = config.data_selector
    return extra


def _make_source_response(config: BrowserbaseEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def browserbase_source(api_key: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    endpoint_config = BROWSERBASE_ENDPOINTS[endpoint]

    if endpoint_config.fanout:
        parent_config = BROWSERBASE_ENDPOINTS[endpoint_config.fanout.parent_name]
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=BROWSERBASE_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_client_config(api_key),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                # Neither the fan-out parents nor their children accept a page-size param.
                page_size_param=None,
                parent_endpoint_extra=_endpoint_extra(parent_config),
                child_endpoint_extra=_endpoint_extra(endpoint_config),
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    resource_endpoint: Endpoint = {
        "path": endpoint_config.path,
        **_endpoint_extra(endpoint_config),
    }
    if endpoint_config.paginated:
        resource_endpoint["params"] = {"limit": MAX_PAGE_SIZE}

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": endpoint,
                "endpoint": resource_endpoint,
            }
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return _make_source_response(endpoint_config, lambda: resource)
