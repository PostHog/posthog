from datetime import UTC, date, datetime
from typing import Any, Optional

from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.rewardful.settings import (
    PAGE_LIMIT,
    REWARDFUL_BASE_URL,
    REWARDFUL_ENDPOINTS,
)

REQUEST_TIMEOUT = (10, 60)
# Setup waits on the probe, so it gets one short attempt.
PROBE_TIMEOUT_SECONDS = 30

CAMPAIGNS_PAGED_ERROR = "Rewardful returned more than one page of campaigns"


@frozen
class RewardfulResumeConfig:
    next_page: int


def format_updated_since(value: Any) -> str:
    """Format the watermark as the ISO 8601 UTC timestamp `updated_since` expects."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def unwrap_envelope(item: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    """Return the rows of a `{"pagination", "data"}` envelope, or the item itself when it is a row.

    An unpaged endpoint is read without a selector, so a bare array arrives as rows and an envelope
    arrives as one item holding them.
    """
    data = item.get("data")
    if "pagination" in item and isinstance(data, list):
        # One request reads only the first page, so a paged answer would sync a partial table.
        if (item.get("pagination") or {}).get("next_page"):
            raise ValueError(CAMPAIGNS_PAGED_ERROR)
        return data
    return item


def rewardful_source(
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RewardfulResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = REWARDFUL_ENDPOINTS[endpoint]
    is_incremental = should_use_incremental_field and bool(config.incremental_fields)

    params: dict[str, Any] = {"limit": PAGE_LIMIT, **dict(config.params)}
    if is_incremental and db_incremental_field_last_value is not None:
        params["updated_since"] = {
            "type": "incremental",
            "cursor_path": "updated_at",
            "initial_value": None,
            "convert": format_updated_since,
        }

    endpoint_config: Endpoint = {"path": config.path, "params": params}
    if config.paginated:
        endpoint_config["data_selector"] = "data"
        endpoint_config["data_selector_required"] = True
    else:
        endpoint_config["paginator"] = "single_page"

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": REWARDFUL_BASE_URL,
            # The API secret is the username; the password is empty.
            "auth": {"type": "http_basic", "username": api_secret, "password": ""},
            "paginator": PageNumberPaginator(base_page=1, page_param="page", total_path="pagination.total_pages"),
            "request_timeout": REQUEST_TIMEOUT,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "primary_key": list(config.primary_keys),
                "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
                "endpoint": endpoint_config,
                "table_format": "delta",
                **({} if config.paginated else {"data_map": unwrap_envelope}),
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page"):
            resumable_source_manager.save_state(RewardfulResumeConfig(next_page=int(state["page"])))

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
        primary_keys=list(config.primary_keys),
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Rows arrive newest-first by creation date and `updated_since` is the only filter, so the
        # watermark can only be taken once the whole run has been read.
        sort_mode="desc",
    )


def validate_credentials(api_secret: str) -> tuple[bool, str | None]:
    is_valid, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_secret,), retry=Retry(total=0)),
        f"{REWARDFUL_BASE_URL}/affiliates?limit=1",
        auth=HTTPBasicAuth(api_secret, ""),
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    if is_valid:
        return True, None
    if status == 401:
        return False, "Rewardful rejected the API secret. Copy it again from Company settings in Rewardful."
    return False, "Could not connect to Rewardful. Check the API secret and try again."
