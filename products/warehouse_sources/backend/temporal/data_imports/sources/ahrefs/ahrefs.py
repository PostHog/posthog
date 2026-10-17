from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.settings import (
    API_BASE_URL,
    ENDPOINTS,
    HISTORY_DAYS,
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


def _site_audit_target(api_key: str, project_id: str) -> dict[str, Any]:
    client = RESTClient(base_url=API_BASE_URL, auth=BearerTokenAuth(token=api_key), request_timeout=(10, 60))
    for page in client.paginate(
        path="site-audit/projects",
        params={"output": "json", "project_id": project_id},
        data_selector="healthscores",
        data_selector_required=True,
        paginator=SinglePagePaginator(),
        hooks=create_response_hooks(RESPONSE_ACTIONS),
    ):
        for row in page:
            if row.get("target_url"):
                return row
    raise ValueError("ahrefs_project_not_found")


def _target_params(api_key: str, project_id: str, names: list[str]) -> dict[str, str]:
    if not names:
        return {}
    project = _site_audit_target(api_key, project_id)
    values = {
        "target": project["target_url"],
        "mode": project.get("target_mode"),
        "protocol": project.get("target_protocol"),
    }
    return {name: value for name, value in values.items() if name in names and value}


def _history_start(should_use_incremental_field: bool, last_value: Any, today: date) -> str:
    if should_use_incremental_field and last_value:
        if isinstance(last_value, datetime):
            return last_value.date().isoformat()
        if isinstance(last_value, date):
            return last_value.isoformat()
        return date.fromisoformat(str(last_value)[:10]).isoformat()
    return (today - timedelta(days=HISTORY_DAYS)).isoformat()


def _unique_rows(page: list[dict[str, object]], primary_keys: list[str]) -> list[dict[str, object]]:
    seen: set[tuple[object, ...]] = set()
    rows = []
    for row in page:
        key = tuple(row.get(field) for field in primary_keys)
        if key not in seen:
            seen.add(key)
            rows.append(row)
    return rows


def ahrefs_source(
    api_key: str,
    project_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    normalized_project_id = str(int(project_id))
    project_scoped = settings.get("project_scoped", True)
    history = settings.get("history", False)
    row_limit = settings["params"].get("limit")

    def add_project_id(row: dict[str, object]) -> dict[str, object]:
        return {**row, "project_id": normalized_project_id}

    def items() -> Iterator[list[dict[str, object]]]:
        params: dict[str, Any] = {
            "output": "json",
            **settings["params"],
            **_target_params(api_key, normalized_project_id, settings.get("target_params", [])),
        }
        if project_scoped and not settings.get("target_params"):
            params["project_id"] = normalized_project_id
        if history:
            params["date_from"] = _history_start(
                should_use_incremental_field, db_incremental_field_last_value, datetime.now(UTC).date()
            )
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
                    "write_disposition": {"disposition": "merge", "strategy": "upsert"}
                    if history and should_use_incremental_field
                    else "replace",
                    "endpoint": {
                        "path": settings["path"],
                        "data_selector": settings["data_selector"],
                        "data_selector_required": True,
                        "params": params,
                        "response_actions": RESPONSE_ACTIONS,
                    },
                    "data_map": add_project_id if project_scoped else None,
                }
            ],
        }
        resource = rest_api_resource(config, team_id, job_id, None)
        for page in resource:
            if row_limit is not None and len(page) >= int(row_limit):
                logger.info("ahrefs_sample_limit_reached", team_id=team_id, endpoint=endpoint, limit=row_limit)
                page = page[: int(row_limit)]
            page = _unique_rows(page, settings["primary_keys"])
            if history:
                page = sorted(page, key=lambda row: str(row.get("date") or ""))
            yield page

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=settings["primary_keys"],
        sort_mode="asc" if history else None,
        supports_resume=False,
    )
