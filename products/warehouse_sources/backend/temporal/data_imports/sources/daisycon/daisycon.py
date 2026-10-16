from datetime import UTC, date, datetime
from typing import Any, Optional

from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.daisycon.settings import (
    DAISYCON_BASE_URL,
    DAISYCON_ENDPOINTS,
    FULL_HISTORY_START,
    PER_PAGE,
)

REQUEST_TIMEOUT = (10, 120)
# Setup waits on the probe, so it gets one short attempt.
PROBE_TIMEOUT = (10, 30)


class DaisyconPublisherError(Exception):
    pass


@frozen
class DaisyconResumeConfig:
    next_page: int
    # The date filter the interrupted attempt sent, so the resumed pages come from the same result set.
    date_filter: str | None = None


def format_datetime_filter(value: Any) -> str:
    """Format a watermark as the `YYYY-MM-DD HH:MM:SS` value Daisycon's datetime filters expect.

    Daisycon timestamps carry no zone. The watermark comes from those same values, so it is sent back
    without converting it.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return f"{value.isoformat()} 00:00:00"
    return str(value)[:19]


def format_date_filter(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def add_last_modified(row: dict[str, Any]) -> dict[str, Any]:
    """Lift the newest part modification time onto the transaction row.

    A transaction holds one or more parts, and each part carries its own `last_modified`. The server
    filters on that part time, so the newest one is the transaction's change time.
    """
    parts = row.get("parts") or []
    modified = [part["last_modified"] for part in parts if isinstance(part, dict) and part.get("last_modified")]
    row["last_modified"] = max(modified) if modified else row.get("date")
    return row


def resolve_publisher_id(requested: str | None, available: list[str]) -> str:
    """Pick the publisher to sync from the ones the connected login can read."""
    requested = (requested or "").strip()
    if requested:
        if requested not in available:
            raise DaisyconPublisherError(
                f"The connected Daisycon login cannot read publisher {requested}. "
                f"It can read: {', '.join(available) or 'none'}."
            )
        return requested
    if len(available) == 1:
        return available[0]
    raise DaisyconPublisherError(
        f"The connected Daisycon login can read more than one publisher. Pick the publisher to sync in the "
        f"source settings: {', '.join(available)}."
    )


def _date_filter(endpoint: str, should_use_incremental_field: bool, last_value: Any) -> str | None:
    if endpoint == "transactions":
        if should_use_incremental_field and last_value is not None:
            return format_datetime_filter(last_value)
        return f"{FULL_HISTORY_START} 00:00:00"
    if endpoint == "statistics_daily":
        if should_use_incremental_field and last_value is not None:
            return format_date_filter(last_value)
        return FULL_HISTORY_START
    return None


def _params(endpoint: str, date_filter: str | None, currency_code: str) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PER_PAGE}
    if endpoint == "transactions":
        params["date_modified_start"] = date_filter
    elif endpoint == "statistics_daily":
        params["start"] = date_filter
        params["end"] = datetime.now(UTC).date().isoformat()
        params["currency_code"] = currency_code
    return params


def daisycon_source(
    auth: AuthConfigBase,
    publisher_id: str,
    endpoint: str,
    currency_code: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DaisyconResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DAISYCON_ENDPOINTS[endpoint]
    is_incremental = should_use_incremental_field and bool(config.incremental_fields)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    date_filter = (
        resume.date_filter
        if resume is not None
        else _date_filter(endpoint, is_incremental, db_incremental_field_last_value)
    )

    endpoint_config: Endpoint = {
        "path": config.path.format(publisher_id=publisher_id),
        "params": _params(endpoint, date_filter, currency_code),
    }
    resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "primary_key": list(config.primary_keys),
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }
    if endpoint == "transactions":
        resource["data_map"] = add_last_modified

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": DAISYCON_BASE_URL,
            "auth": auth,
            # Lists are bare arrays and an exhausted list answers 204 with no body, which ends the walk.
            "paginator": PageNumberPaginator(base_page=1, page_param="page"),
            "request_timeout": REQUEST_TIMEOUT,
        },
        "resource_defaults": {},
        "resources": [resource],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page"):
            resumable_source_manager.save_state(
                DaisyconResumeConfig(next_page=int(state["page"]), date_filter=date_filter)
            )

    rest_resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": resume.next_page} if resume is not None else None,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: rest_resource,
        primary_keys=list(config.primary_keys),
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Daisycon cannot sort by modification time, so the watermark is taken once the run ends.
        sort_mode="desc" if config.incremental_fields else "asc",
    )


def probe_token(access_token: str) -> int:
    """Return the HTTP status of one cheap authorized read."""
    response = make_tracked_session(redact_values=(access_token,), allow_redirects=False, retry=Retry(total=0)).get(
        f"{DAISYCON_BASE_URL}/publishers",
        params={"per_page": 1},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=PROBE_TIMEOUT,
    )
    return response.status_code
