from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.settings import EVENTEE_ENDPOINTS

# The base URL is fixed: the Bearer token scopes to a single event, so there's no per-tenant host.
EVENTEE_BASE_URL = "https://api.eventee.com/public/v1"


def _client_config(api_key: str) -> ClientConfig:
    # The token travels via framework bearer auth (not a hand-built header) so its value is registered
    # for redaction wherever it surfaces in logs or raised error messages; only the non-secret Accept
    # header goes here. Every endpoint returns its whole collection in one response — no pagination.
    return {
        "base_url": EVENTEE_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "paginator": SinglePagePaginator(),
    }


def eventee_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = EVENTEE_ENDPOINTS[endpoint]

    # `/content` bundles several lists, so a table sourced from it reads its rows from `data_key`; the
    # standalone endpoints return their list directly (data_key None -> the whole body is the rows).
    # The selector is deliberately NOT required: a missing/empty data key yields 0 rows (matching the
    # old `_extract_rows`), and `/registrations` returning a bare object is wrapped into one row.
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": config.data_key,
                    "paginator": SinglePagePaginator(),
                },
            }
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the token is genuine with a cheap probe. A valid token returns 200; an invalid or
    expired one returns 401 (`token_invalid`)."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{EVENTEE_BASE_URL}/groups",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    return ok
