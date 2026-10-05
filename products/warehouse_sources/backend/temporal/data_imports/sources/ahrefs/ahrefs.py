from collections.abc import Iterator
from typing import cast

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.settings import (
    API_BASE_URL,
    ENDPOINTS,
    MAX_PAGE_ROWS,
    NON_RETRYABLE_ERRORS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

logger = structlog.get_logger(__name__)

RESPONSE_ACTIONS: list[ResponseAction] = [
    cast(
        ResponseAction,
        {"status_code": status, "content": content, "action": "raise", "message": "ahrefs_quota_exceeded"},
    )
    for status in (400, 403)
    for content in ("units", "Units", "quota", "Quota")
]
RESPONSE_ACTIONS.extend(
    [
        {"status_code": 402, "action": "raise", "message": "ahrefs_quota_exceeded"},
        {"status_code": 401, "action": "raise", "message": "ahrefs_invalid_api_key"},
        {"status_code": 403, "action": "raise", "message": "ahrefs_access_denied"},
    ]
)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=API_BASE_URL,
        auth=BearerTokenAuth(token=api_key),
        max_retry_attempts=1,
        request_timeout=(10, 60),
    )
    try:
        list(
            client.paginate(
                path="subscription-info/limits-and-usage",
                params={"output": "json"},
                data_selector="limits_and_usage",
                data_selector_required=True,
                paginator=SinglePagePaginator(),
                hooks=create_response_hooks(RESPONSE_ACTIONS),
            )
        )
    except ValueError as error:
        message = NON_RETRYABLE_ERRORS.get(str(error))
        if message is None:
            raise
        return False, message
    return True, None


def ahrefs_source(api_key: str, project_id: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    normalized_project_id = str(int(project_id))

    def add_project_id(row: dict[str, object]) -> dict[str, object]:
        return {**row, "project_id": normalized_project_id}

    config: RESTAPIConfig = {
        "client": {
            "base_url": API_BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "paginator": "single_page",
            "request_timeout": (10, 60),
        },
        "resources": [
            {
                "name": endpoint,
                "write_disposition": "replace",
                "endpoint": {
                    "path": settings["path"],
                    "data_selector": settings["data_selector"],
                    "data_selector_required": True,
                    "params": {"output": "json", "project_id": normalized_project_id, **settings["params"]},
                    "response_actions": RESPONSE_ACTIONS,
                },
                "data_map": add_project_id,
            }
        ],
    }
    resource = rest_api_resource(config, team_id, job_id, None)

    def items() -> Iterator[list[dict[str, object]]]:
        for page in resource:
            if endpoint == "site_audit_pages" and len(page) >= MAX_PAGE_ROWS:
                logger.info("ahrefs_page_sample_limit_reached", team_id=team_id, limit=MAX_PAGE_ROWS)
                page = page[:MAX_PAGE_ROWS]
            yield page

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=settings["primary_keys"],
        sort_mode=None,
        supports_resume=False,
    )
