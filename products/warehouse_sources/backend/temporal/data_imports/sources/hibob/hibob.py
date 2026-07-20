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
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.settings import HIBOB_ENDPOINTS

HIBOB_BASE_URL = "https://api.hibob.com"


def validate_credentials(service_user_id: str, service_user_token: str) -> tuple[bool, str | None]:
    """Confirm the service user credentials are valid with a cheap tasks probe.

    Service users need explicit per-category permission grants (403); only 401
    means the credentials themselves are bad. Transport failures surface their
    real reason rather than masquerading as an auth error."""
    session = make_tracked_session(redact_values=(service_user_token,))
    session.auth = (service_user_id, service_user_token)
    try:
        response = session.get(f"{HIBOB_BASE_URL}/v1/tasks", timeout=10)
        if response.status_code == 401:
            return False, "Invalid HiBob Service User credentials"
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        session.close()


def hibob_source(
    service_user_id: str,
    service_user_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = HIBOB_ENDPOINTS[endpoint]

    # Basic auth carries the token; supplying it via the framework auth config redacts the
    # token from any raised error. Repeated 401/403s trip HiBob's WAF, so auth errors must
    # fail loud (raise_for_status) rather than retry — the client only retries 429/5xx.
    api_endpoint: dict[str, Any] = {
        "path": config.path,
        "method": config.method,
        # A missing data key is a legit "no rows" answer (not a shape error), so the selector
        # stays optional — an absent key yields an empty page, matching the old behaviour.
        "data_selector": config.data_key,
    }
    if config.body is not None:
        api_endpoint["json"] = config.body

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HIBOB_BASE_URL,
            "auth": {"type": "http_basic", "username": service_user_id, "password": service_user_token},
            # Both shipped endpoints return their full result set in one response.
            "paginator": SinglePagePaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": api_endpoint,
            }
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
