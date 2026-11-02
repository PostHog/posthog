from datetime import UTC, datetime, timedelta
from typing import Any, cast

from requests.exceptions import HTTPError
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.speedcurve.settings import (
    BASE_URL,
    ENDPOINTS,
    TEST_HISTORY_DAYS,
)

AUTH_ERROR = "SpeedCurve rejected the API key. Check the key and confirm that your SpeedCurve account is active."
PERMISSION_ERROR = "SpeedCurve denied access. Check the API key permissions for your team."


@frozen
class SpeedcurveResumeConfig:
    page: int
    start_timestamp: int | None
    end_timestamp: int


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, str | None]:
    with make_tracked_session(redact_values=(api_key,), retry=Retry(total=0)) as session:
        client = RESTClient(
            base_url=f"{BASE_URL}/{api_version}/",
            auth=HttpBasicAuth(username=api_key, password="x"),
            session=session,
            request_timeout=60,
        )
        try:
            next(
                client.paginate(
                    "sites",
                    params={"median": 0},
                    paginator=SinglePagePaginator(),
                    data_selector="sites",
                    data_selector_required=True,
                )
            )
        except HTTPError as error:
            if error.response is not None:
                if error.response.status_code == 401:
                    return False, AUTH_ERROR
                if error.response.status_code == 403:
                    return False, PERMISSION_ERROR
            raise
    return True, None


def _site_urls(site: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**url, "site_id": site["site_id"]} for url in site["urls"]]


def speedcurve_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SpeedcurveResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: int | float | str | None,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    now = datetime.now(UTC)
    end_timestamp = int(now.timestamp())
    start_timestamp = None
    page = 1
    if settings.paginated:
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            start_timestamp = int(db_incremental_field_last_value)
        if endpoint == "tests":
            # Leave one day inside the API's rolling twelve-month retention limit.
            retention_start = int((now - timedelta(days=TEST_HISTORY_DAYS)).timestamp())
            start_timestamp = max(start_timestamp or retention_start, retention_start)
        if resumable_source_manager.can_resume():
            saved = resumable_source_manager.load_state()
            if saved is not None:
                page = saved.page
                start_timestamp = saved.start_timestamp
                end_timestamp = saved.end_timestamp

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                SpeedcurveResumeConfig(page=state["page"], start_timestamp=start_timestamp, end_timestamp=end_timestamp)
            )

    endpoint_config: Endpoint = {
        "path": endpoint,
        "data_selector": settings.selector,
        "data_selector_required": True,
        "paginator": "single_page",
    }
    if settings.paginated:
        endpoint_config["params"] = {
            "per_page": 100,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
        }
        endpoint_config["paginator"] = cast(
            PaginatorConfig,
            {
                "type": "page_number",
                "base_page": 1,
                "total_path": "meta.last_page" if endpoint == "tests" else None,
            },
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": f"{BASE_URL}/{api_version}/",
            "auth": {"type": "http_basic", "username": api_key, "password": "x"},
            "session": make_tracked_session(redact_values=(api_key,), retry=Retry(total=0)),
            "request_timeout": 60,
        },
        "resources": [
            {
                "name": endpoint,
                "table_format": "delta",
                "endpoint": endpoint_config,
            }
        ],
    }
    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint if settings.paginated else None,
        initial_paginator_state={"page": page} if settings.paginated else None,
    )
    if endpoint == "urls":
        resource.add_map(_site_urls)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(settings.primary_keys),
        # The API has no ascending sort option, so checkpoint the watermark after the complete scan.
        sort_mode="desc",
        partition_keys=["timestamp"] if settings.paginated else None,
        partition_mode="datetime" if settings.paginated else None,
        partition_format="month" if settings.paginated else None,
        supports_resume=settings.paginated,
        on_complete=resumable_source_manager.clear_state if settings.paginated else None,
    )
