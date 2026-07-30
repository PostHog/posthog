from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.height.settings import HEIGHT_ENDPOINTS

HEIGHT_BASE_URL = "https://api.height.app"
# Cheap endpoint used to confirm an API key is genuine. The key is workspace-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/users"


class HeightAPIKeyAuth(APIKeyAuth):
    """Height's Authorization scheme is the literal word ``api-key`` followed by the secret, not a
    Bearer token. Passing the composite value through the framework auth keeps the credential out of
    logged errors; the raw key is redacted too so it never leaks on its own."""

    def __init__(self, api_key: str) -> None:
        super().__init__(api_key=f"api-key {api_key}", name="Authorization", location="header")
        self._raw_api_key = api_key

    def secret_values(self) -> tuple[str, ...]:
        # Redact both the composite header value and the raw key on its own.
        return tuple(value for value in (self.api_key, self._raw_api_key) if value)


def height_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = HEIGHT_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HEIGHT_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": HeightAPIKeyAuth(api_key),
            # Height list endpoints are unpaginated single-shot lists, so one request returns the
            # full collection.
            "paginator": SinglePagePaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # Height list endpoints wrap records in a top-level `list` key; require it so a
                    # 200 with an unexpected shape (bare array / missing key) fails loud instead of
                    # silently syncing 0 rows.
                    "data_selector": "list",
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
        f"{HEIGHT_BASE_URL}{DEFAULT_PROBE_PATH}",
        auth=HeightAPIKeyAuth(api_key),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Height API key"
    if status is None:
        return False, "Could not validate Height API key"
    return False, f"Height returned HTTP {status}"
