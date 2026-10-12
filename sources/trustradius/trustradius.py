from requests.exceptions import HTTPError

from sources.sdk import (
    APIKeyAuth,
    RESTAPIConfig,
    RESTClient,
    SinglePagePaginator,
    SourceResponse,
    rest_api_resource,
    schema_for_resource,
)
from sources.trustradius.settings import AUTH_ERROR, BASE_URL, ENDPOINTS, PERMISSION_ERROR


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=api_key, name="x-api-key", location="header"),
        paginator=SinglePagePaginator(),
        request_timeout=(10, 60),
        allow_redirects=False,
    )
    try:
        next(client.paginate("product-ids", data_selector="", data_selector_required=True), None)
    except HTTPError as error:
        if error.response is not None:
            if error.response.status_code == 401:
                return False, AUTH_ERROR
            if error.response.status_code == 403:
                return False, PERMISSION_ERROR
        raise
    return True, None


def trustradius_source(api_key: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "api_key": api_key, "name": "x-api-key", "location": "header"},
            "paginator": "single_page",
            "headers": {"Accept": "application/json"},
            "request_timeout": (10, 60),
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "table_format": "delta",
                "write_disposition": "replace",
                "endpoint": {
                    "path": settings["path"],
                    "data_selector": settings["data_selector"],
                    "data_selector_required": True,
                    "params": {"include-anonymous": "true"} if endpoint == "trustquotes" else {},
                },
            }
        ],
    }
    resource = rest_api_resource(config, team_id, job_id, None)
    partition_key = settings["partition_key"]
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=settings["primary_keys"],
        column_hints=resource.column_hints,
        partition_keys=[partition_key] if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        sort_mode=None,
        supports_resume=False,
    )
