import base64
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, ClassVar, Optional
from urllib.parse import urlencode

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.blueshift.settings import (
    BLUESHIFT_ENDPOINTS,
    BLUESHIFT_REGION_URLS,
    DEFAULT_REGION,
    PAGE_SIZE,
    STATS_BACKFILL_DAYS,
    STATS_REREAD_DAYS,
    BlueshiftEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

STATS_REQUEST_TIMEOUT = 120
_ISO_UTC = "%Y-%m-%dT%H:%M:%S.000Z"


@frozen
class BlueshiftResumeConfig:
    # Next page of a paginated list endpoint.
    next_page: Optional[int] = None
    # Next UTC day (ISO date) the stats walk fetches.
    next_date: Optional[str] = None


@frozen
class BlueshiftStatsCursor:
    """The first UTC day (ISO date) the next `campaign_stats` sync reads.

    Days with no campaign activity yield no rows, so the row watermark cannot record that they
    were read. Without this cursor every sync of a quiet account would walk the whole backfill again.
    """

    cursor_kind: ClassVar[str] = "blueshift_campaign_stats_day"
    next_date: str


def base_url(region: str) -> str:
    return BLUESHIFT_REGION_URLS.get(region, BLUESHIFT_REGION_URLS[DEFAULT_REGION])


def _basic_auth_value(api_key: str) -> str:
    token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    return f"Basic {token}"


def _client_config(region: str, api_key: str) -> ClientConfig:
    return {
        "base_url": base_url(region),
        # Blueshift sends the key as the basic-auth username. The framework's `http_basic` auth
        # redacts only the password, so send the whole header as a redacted API key value.
        "auth": {
            "type": "api_key",
            "name": "Authorization",
            "api_key": _basic_auth_value(api_key),
            "location": "header",
        },
        "headers": {"Accept": "application/json"},
    }


def _list_endpoint(config: BlueshiftEndpointConfig) -> Endpoint:
    endpoint: Endpoint = {"path": config.path}
    if config.pagination == "page":
        endpoint["params"] = {"per_page": PAGE_SIZE}
        endpoint["paginator"] = PageNumberPaginator(base_page=1, page_param="page")
    else:
        endpoint["paginator"] = SinglePagePaginator()
    if config.data_selector is not None:
        endpoint["data_selector"] = config.data_selector
    return endpoint


def get_resource(config: BlueshiftEndpointConfig) -> EndpointResource:
    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": "replace",
        "endpoint": _list_endpoint(config),
        "table_format": "delta",
    }


def _stats_window(day: date) -> dict[str, str]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    return {"start_time": start.strftime(_ISO_UTC), "end_time": end.strftime(_ISO_UTC)}


def _campaign_stats_rows(
    region: str,
    api_key: str,
    resumable_source_manager: ResumableSourceManager[BlueshiftResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    cursor_manager: Optional[SourceCursorManager[BlueshiftStatsCursor]],
    db_incremental_field_last_value_before_lookback: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    """Yield the per-campaign performance summary for each UTC day, oldest first, through today."""
    config = BLUESHIFT_ENDPOINTS["campaign_stats"]
    auth_value = _basic_auth_value(api_key)
    session = make_tracked_session(redact_values=(api_key, auth_value))
    headers = {"Authorization": auth_value, "Accept": "application/json"}
    url = f"{base_url(region)}{config.path}"
    today = datetime.now(UTC).date()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    stored = cursor_manager.load() if cursor_manager is not None else None
    last_value = parse_datetime_value(db_incremental_field_last_value)
    # The pipeline moves the watermark back by the schema's lookback. The cursor moves back by the
    # same amount, so a lookback still reads earlier days again.
    before_lookback = parse_datetime_value(db_incremental_field_last_value_before_lookback)
    lookback = max(before_lookback - last_value, timedelta(0)) if before_lookback and last_value else timedelta(0)
    known_starts = [
        *([(datetime.combine(date.fromisoformat(stored.next_date), time.min) - lookback).date()] if stored else []),
        *([last_value.date()] if last_value is not None else []),
    ]
    if resume is not None and resume.next_date is not None:
        day = date.fromisoformat(resume.next_date)
    elif known_starts:
        day = max(known_starts) - timedelta(days=STATS_REREAD_DAYS)
    else:
        day = today - timedelta(days=STATS_BACKFILL_DAYS)

    while day <= today:
        response = session.get(url, params=_stats_window(day), headers=headers, timeout=STATS_REQUEST_TIMEOUT)
        response.raise_for_status()
        campaigns = response.json().get(config.data_selector) or []
        next_day = day + timedelta(days=1)
        if next_day <= today:
            resumable_source_manager.save_state(BlueshiftResumeConfig(next_date=next_day.isoformat()))
        if not campaigns:
            # Nothing to yield means the pipeline cannot see a worker shutdown, so hand over here.
            resumable_source_manager.safe_point()
        else:
            yield [{"date": day.isoformat(), **campaign} for campaign in campaigns]
        day = next_day

    if cursor_manager is not None:
        cursor_manager.stage(BlueshiftStatsCursor(next_date=today.isoformat()))


def _source_response(config: BlueshiftEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def blueshift_source(
    region: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BlueshiftResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    cursor_manager: Optional[SourceCursorManager[BlueshiftStatsCursor]] = None,
    db_incremental_field_last_value_before_lookback: Optional[Any] = None,
) -> SourceResponse:
    config = BLUESHIFT_ENDPOINTS[endpoint]

    if config.pagination == "daily":
        return _source_response(
            config,
            lambda: _campaign_stats_rows(
                region,
                api_key,
                resumable_source_manager,
                db_incremental_field_last_value,
                cursor_manager,
                db_incremental_field_last_value_before_lookback,
            ),
        )

    rest_config: RESTAPIConfig = {
        "client": _client_config(region, api_key),
        "resource_defaults": {},
        "resources": [get_resource(config)],
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_page is not None:
        initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(BlueshiftResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _source_response(config, lambda: resource)


def _probe_url(region: str, schema_name: Optional[str]) -> str:
    config = BLUESHIFT_ENDPOINTS[schema_name or "segments"]
    if config.pagination == "daily":
        params = _stats_window(datetime.now(UTC).date())
    elif config.pagination == "page":
        params = {"per_page": "1"}
    else:
        params = {}
    return f"{base_url(region)}{config.path}" + (f"?{urlencode(params)}" if params else "")


def probe_credentials(region: str, api_key: str, schema_name: Optional[str] = None) -> tuple[bool, int | None]:
    """Probe the table `schema_name` reads, or the segments list when no table is named."""
    auth_value = _basic_auth_value(api_key)
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key, auth_value)),
        _probe_url(region, schema_name),
        headers={"Authorization": auth_value, "Accept": "application/json"},
        ok_statuses=(200,),
    )
