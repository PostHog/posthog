import base64
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.settings import CONFIGCAT_ENDPOINTS

CONFIGCAT_BASE_URL = "https://api.configcat.com"
# Cheap org-level list used to confirm the Public API credential is genuine. The credential is
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/v1/organizations"


def _headers(username: str, password: str) -> dict[str, str]:
    # ConfigCat's Public Management API authenticates with HTTP Basic credentials (a username and
    # password pair generated on the Public API credentials page — not the SDK keys).
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def configcat_source(
    username: str,
    password: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = CONFIGCAT_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CONFIGCAT_BASE_URL,
            # Basic auth via the framework so the credential is redacted from logs; the client
            # retries 429/5xx (documented ~20 req/sec, ~500 req/min per endpoint) on its own.
            "auth": {"type": "http_basic", "username": username, "password": password},
            "headers": {"Accept": "application/json"},
            # The Public Management API list endpoints return the full collection in one response.
            "paginator": SinglePagePaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # The body is a bare JSON array; require it to be a list so an unexpected object
                    # payload fails loud instead of syncing the object as a single row.
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


def check_access(username: str, password: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the Public API credential.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(username, password), redact_values=(username, password))
    try:
        response = session.get(f"{CONFIGCAT_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to ConfigCat: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"ConfigCat returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(username: str, password: str) -> tuple[bool, str | None]:
    status, message = check_access(username, password)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid ConfigCat Public API credentials"
    return False, message or "Could not validate ConfigCat Public API credentials"
