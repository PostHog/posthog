from typing import Any

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
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.settings import (
    GOOGLE_WEBFONTS_ENDPOINTS,
)

GOOGLE_WEBFONTS_BASE_URL = "https://www.googleapis.com"

# The key rides the `X-goog-api-key` header (Google accepts either this or a `key` query param) so it
# never lands in a logged request URL; the framework auth config redacts its value from logs and
# raised error messages.
GOOGLE_WEBFONTS_API_KEY_HEADER = "X-goog-api-key"


def _endpoint_params(sort: str | None) -> dict[str, Any]:
    return {"sort": sort} if sort else {}


def google_webfonts_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = GOOGLE_WEBFONTS_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": GOOGLE_WEBFONTS_BASE_URL,
            # Only non-secret headers here; the API key rides in the framework auth config below so
            # its value is redacted from logs and raised error messages.
            "headers": {"Accept": "application/json"},
            "auth": {
                "type": "api_key",
                "api_key": api_key,
                "name": GOOGLE_WEBFONTS_API_KEY_HEADER,
                "location": "header",
            },
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _endpoint_params(config.sort),
                    # The catalog arrives in a single (unpaginated) `items` array. A missing/empty
                    # selector yields no rows (leniently, as before) rather than failing loud.
                    "data_selector": config.data_selector,
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
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Confirm the API key is valid with a single catalog probe.

    An invalid key returns 400 (`API_KEY_INVALID`) and a missing key 403; only a genuine key returns
    200. A connection-level failure (DNS, timeout, reset) surfaces as status ``None`` so the caller
    can tell "unreachable" apart from "invalid key" instead of blaming the credential.
    """
    config = GOOGLE_WEBFONTS_ENDPOINTS["webfonts"]
    params = _endpoint_params(config.sort)
    query = f"?sort={params['sort']}" if params else ""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{GOOGLE_WEBFONTS_BASE_URL}{config.path}{query}",
        headers={GOOGLE_WEBFONTS_API_KEY_HEADER: api_key, "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status is None:
        return False, "Could not reach the Google Fonts API. Check your network connection and try again."
    return False, "Invalid Google API key"
