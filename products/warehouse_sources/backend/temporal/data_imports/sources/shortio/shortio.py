from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.settings import SHORTIO_ENDPOINTS

SHORTIO_BASE_URL = "https://api.short.io"
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to the domain list.
DEFAULT_PROBE_PATH = "/api/domains"


def _auth_headers(api_key: str) -> dict[str, str]:
    # Short.io expects the raw secret API key in the Authorization header — no `Bearer` prefix.
    return {"Authorization": api_key, "Accept": "application/json"}


def shortio_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = SHORTIO_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SHORTIO_BASE_URL,
            # Only the non-secret Accept header is set here; the raw key rides in Authorization via
            # the framework auth config so its value is redacted from logs and error messages.
            "headers": {"Accept": "application/json"},
            # Short.io expects the raw secret key in Authorization — no `Bearer` prefix.
            "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
            # The domain list has no pagination, so a single request returns the whole collection.
            "paginator": SinglePagePaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # The body is a bare JSON array; require a list so a non-list 200 (schema drift or
                    # an error object) fails loud instead of syncing the object as a single row.
                    "data_selector_required": True,
                },
            }
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SHORTIO_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers=_auth_headers(api_key),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Short.io API key"
    if status is None:
        return False, "Could not connect to Short.io. Please try again."
    return False, f"Short.io returned HTTP {status}"
