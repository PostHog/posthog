from typing import Optional

from requests import PreparedRequest

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.settings import MY_HOURS_ENDPOINTS

MY_HOURS_BASE_URL = "https://api2.myhours.com/api"
# Cheap list endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/Clients"


class MyHoursApiKeyAuth(AuthConfigBase):
    """My Hours expects the literal ``apikey `` prefix before the key on the Authorization header;
    omitting it (or using ``Bearer``) returns 400/401. Framework ``bearer``/``api_key`` auth can't
    emit that scheme, so this thin auth carries the raw key (declared secret so it's redacted from
    every logged URL/header and every raised error message)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"apikey {self.api_key}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.api_key,) if self.api_key else ()


def _headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def my_hours_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = MY_HOURS_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": MY_HOURS_BASE_URL,
            "headers": _headers(),
            "auth": MyHoursApiKeyAuth(api_key),
            # The list endpoints are unpaginated: a single request returns the whole collection.
            "paginator": SinglePagePaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # My Hours list endpoints return a bare JSON array. A 200 whose body isn't a
                    # list is treated as transient (a truncating proxy / stray error object) and the
                    # request is reissued, matching the hand-rolled retryable behavior.
                    "data_selector_malformed_retryable": True,
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
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers={"Authorization": f"apikey {api_key}", **_headers()}, redact_values=(api_key,)
    )
    try:
        response = session.get(f"{MY_HOURS_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to My Hours: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"My Hours returned HTTP {response.status_code}"

    return 200, None
