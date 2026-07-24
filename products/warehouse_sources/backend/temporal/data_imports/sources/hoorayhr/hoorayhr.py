from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.settings import (
    HOORAYHR_BASE_URL,
    HOORAYHR_ENDPOINTS,
)


def hoorayhr_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = HOORAYHR_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HOORAYHR_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Both personal API keys (pk_ prefixed) and partner OAuth access tokens are sent as
            # `Authorization: Bearer <token>`.
            "auth": {"type": "bearer", "token": api_key},
            # No pagination is documented on any list endpoint — each table is a single bare-array
            # page, full refresh only.
            "paginator": "single_page",
        },
        "resource_defaults": None,
        "resources": [{"name": endpoint, "endpoint": {"path": config.path}}],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    has_partition_key = config.partition_key is not None
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Month is the coarsest datetime tier; the auto-repartitioner only steps finer, so this
        # gives it the most headroom. Endpoints without a stable creation field stay unpartitioned.
        partition_mode="datetime" if has_partition_key else None,
        partition_format="month" if has_partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    # /leave-types is the cheapest authenticated read: a handful of rows per company. The probe runs
    # before the source is saved, so `redact_values` masks the API key in tracked telemetry here too.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{HOORAYHR_BASE_URL}{HOORAYHR_ENDPOINTS['leave_types'].path}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=15,
    )
    return ok
