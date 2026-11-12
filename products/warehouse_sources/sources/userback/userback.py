import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import (
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.userback.settings import USERBACK_ENDPOINTS

USERBACK_API_VERSION = "1.0"
USERBACK_BASE_URL = f"https://rest.userback.io/{USERBACK_API_VERSION}"
# The list endpoints cap a page at 100 records.
PAGE_SIZE = 100
FIRST_PAGE = 1


@dataclasses.dataclass(frozen=True)
class UserbackResumeConfig:
    page: int


def format_filter_timestamp(value: Any) -> str:
    """Format an incremental cursor value as the RFC 3339 UTC timestamp the API returns."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def build_params(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str],
) -> dict[str, Any]:
    config = USERBACK_ENDPOINTS[endpoint]
    params: dict[str, Any] = {"limit": PAGE_SIZE}

    supported_fields = [f["field"] for f in config.incremental_fields]
    cursor_field = incremental_field if incremental_field in supported_fields else None
    if should_use_incremental_field and cursor_field is None and supported_fields:
        cursor_field = supported_fields[0]

    if should_use_incremental_field and cursor_field is not None:
        # `ge` rather than `gt`: rows that share the watermark second are read again and merge dedupes them.
        if db_incremental_field_last_value is not None:
            params["filter"] = f"{cursor_field} ge '{format_filter_timestamp(db_incremental_field_last_value)}'"
        params["sort"] = f"{cursor_field},asc"
    elif config.full_refresh_sort is not None:
        params["sort"] = f"{config.full_refresh_sort},asc"

    return params


def userback_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[UserbackResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = USERBACK_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": USERBACK_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            "paginator": PageNumberPaginator(base_page=FIRST_PAGE, total_path="_pagination.totalPages"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": build_params(
                        endpoint, should_use_incremental_field, db_incremental_field_last_value, incremental_field
                    ),
                    "data_selector": "data",
                    # A 200 without a `data` array means the response shape changed. Fail instead of syncing 0 rows.
                    "data_selector_required": True,
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(UserbackResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # The request asks for `sort=<cursor>,asc`, but we could not confirm the order against a live
        # account, so the rows are not declared as ordered. An interrupted run restarts from the watermark.
        sort_mode=None,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{USERBACK_BASE_URL}/project?limit=1",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Userback rejected the API token. Check the token and try again."
    if status == 403:
        return (
            False,
            "Userback accepted the token but refused API access. The REST API needs a Premium plan and an admin account.",
        )
    if status is None:
        return False, "Could not reach Userback to check the API token. Try again."
    return False, f"Userback could not check the API token right now (status {status}). Try again."
