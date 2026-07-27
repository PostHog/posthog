from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.settings import (
    OPTIMIZELY_ENDPOINTS,
    OptimizelyEndpointConfig,
)

OPTIMIZELY_API_HOST = "api.optimizely.com"
OPTIMIZELY_BASE_URL = f"https://{OPTIMIZELY_API_HOST}/v2"
# Optimizely list pages cap at 100 items.
PAGE_SIZE = 100


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": OPTIMIZELY_BASE_URL,
        # The Bearer token rides in the framework auth config so its value is redacted from logs and
        # raised errors; the client sets the Authorization header itself.
        "auth": {"type": "bearer", "token": api_token},
        # Optimizely paginates via RFC 5988 `Link: rel="next"` headers.
        "paginator": HeaderLinkPaginator(),
        # Pin every request — including the `Link` next-page URL, which a spoofed upstream response
        # could point elsewhere — to Optimizely's API host, so the credentialed Bearer request can't
        # be redirected to an internal address (SSRF) or attacker host (token theft).
        "allowed_hosts": [OPTIMIZELY_API_HOST],
    }


def _simple_source(
    api_token: str, endpoint: str, config: OptimizelyEndpointConfig, team_id: int, job_id: str
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": PAGE_SIZE},
                    # Bare-array body — no data_selector. The old transport tolerated a non-list body
                    # as an empty page, so no data_selector_required here.
                },
            }
        ],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def _fan_out_source(
    api_token: str, endpoint: str, config: OptimizelyEndpointConfig, team_id: int, job_id: str
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": "projects",
                "endpoint": {
                    "path": "/projects",
                    "params": {"per_page": PAGE_SIZE},
                },
            },
            {
                "name": endpoint,
                "endpoint": {
                    # project_id rides in a query param; embed the resolve placeholder in the path so
                    # the binding lands in the query string (resolve only substitutes into paths).
                    "path": f"{config.path}?project_id={{project_id}}",
                    "params": {
                        "project_id": {"type": "resolve", "resource": "projects", "field": "id"},
                        "per_page": PAGE_SIZE,
                    },
                    # A project without access to this feature (e.g. campaigns on a non-Web project)
                    # returns 400/403/404 — treat that as a valid empty page and move to the next
                    # project rather than failing the whole stream, matching the old per-project skip.
                    "response_actions": [
                        {"status_code": 400, "action": "ignore"},
                        {"status_code": 403, "action": "ignore"},
                        {"status_code": 404, "action": "ignore"},
                    ],
                },
            },
        ],
    }
    resources = rest_api_resources(rest_config, team_id, job_id, None)
    # Only the child rows are emitted; the projects list is iterated internally to drive the fan-out.
    return next(resource for resource in resources if resource.name == endpoint)


def optimizely_source(api_token: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    config = OPTIMIZELY_ENDPOINTS[endpoint]

    if config.project_scoped:
        resource = _fan_out_source(api_token, endpoint, config, team_id, job_id)
    else:
        resource = _simple_source(api_token, endpoint, config, team_id, job_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


def validate_credentials(api_token: str) -> bool:
    """Confirm the personal access token is valid with a cheap projects probe.

    Any reachable response other than 401 means the token is usable (a 403 is a valid token missing
    a scope); a transport error (status None) means "not validated" — matching the old probe.
    """
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{OPTIMIZELY_BASE_URL}/projects?per_page=1",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    return status is not None and status != 401
