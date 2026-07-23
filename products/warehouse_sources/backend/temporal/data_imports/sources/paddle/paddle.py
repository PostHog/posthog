import dataclasses
from datetime import UTC, date, datetime, time
from typing import Any, Optional

import requests
from dateutil import parser

from products.warehouse_sources.backend.models.external_table_definitions import get_dlt_mapping_for_external_table
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)

PADDLE_BASE_URL = "https://api.paddle.com"
PAGE_SIZE = 200


@dataclasses.dataclass
class PaddleResumeConfig:
    # Self-contained next-page URL from Paddle's `meta.pagination.next`. Empty once the sync is done.
    next_url: str = ""


class PaddlePermissionError(Exception):
    pass


def _format_paddle_datetime_query_value(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, tzinfo=UTC)
    else:
        parsed = parser.isoparse(str(value))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)

    return parsed.isoformat().replace("+00:00", "Z")


def _get_paddle_session(api_key: str) -> requests.Session:
    # DEFAULT_RETRY backs off on 429/5xx (honoring Retry-After) but leaves auth/4xx
    # failures to surface immediately, so a transient rate-limit doesn't fail the sync.
    # The bearer token is set on the session and registered with redact_values so the
    # tracked transport scrubs it from logged URLs, headers, and captured samples.
    return make_tracked_session(
        retry=DEFAULT_RETRY,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        redact_values=(api_key,),
    )


def paddle_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    column_mapping = get_dlt_mapping_for_external_table(f"paddle_{endpoint.lower()}")
    column_hints = {key: value.get("data_type") for key, value in column_mapping.items()}

    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else None

    params: dict[str, Any] = {"per_page": PAGE_SIZE}
    params["order_by"] = f"{incremental_field_name}[ASC]" if incremental_field_name else "id[ASC]"

    # Server-side incremental filter: Paddle supports a `<field>[GT]` query param, so only rows newer
    # than the last-synced watermark are returned. The paginator's self-contained `next` links carry
    # this filter forward, so it's set once on the first request.
    if should_use_incremental_field and incremental_field_name and db_incremental_field_last_value:
        params[f"{incremental_field_name}[GT]"] = _format_paddle_datetime_query_value(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PADDLE_BASE_URL,
            "headers": {"Content-Type": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": JSONResponsePaginator(next_url_path="meta.pagination.next"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": endpoint,
                    "params": params,
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge dedupes) rather than
        # skipping it. Persist the self-contained next-page URL while pages remain, and an empty
        # marker once the last page is reached.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(PaddleResumeConfig(next_url=str(state["next_url"])))
        else:
            resumable_source_manager.save_state(PaddleResumeConfig(next_url=""))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        items=lambda: resource,
        primary_keys=["id"],
        name=endpoint,
        column_hints=column_hints,
        sort_mode="asc",
        partition_keys=[incremental_field_name] if incremental_field_name else None,
        partition_mode="datetime" if incremental_field_name else None,
        partition_count=1,
        partition_size=1,
        partition_format="week" if incremental_field_name else None,
    )


def validate_credentials(api_key: str, table_name: Optional[str] = None) -> bool:
    endpoints_to_check = [table_name] if table_name else ENDPOINTS

    for endpoint in endpoints_to_check:
        ok, status = validate_via_probe(
            lambda: _get_paddle_session(api_key),
            f"{PADDLE_BASE_URL}/{endpoint}",
        )
        if status == 403:
            raise PaddlePermissionError(f"Missing permissions for {endpoint}")
        if not ok:
            return False

    return True
