import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.profound.settings import (
    PROFOUND_ENDPOINTS,
    ProfoundEndpointConfig,
)

logger = logging.getLogger(__name__)

PROFOUND_BASE_URL = "https://api.tryprofound.com"
CATEGORIES_PATH = "/v1/org/categories"
REQUEST_TIMEOUT_SECONDS = 30.0
# The v2 report endpoints cap `limit` at 50.
REPORT_PAGE_SIZE = 50
# How far back a first report sync reaches when there is no watermark yet. `start_date` is required,
# so some window has to be chosen; a year keeps the first sync bounded.
DEFAULT_REPORT_LOOKBACK_DAYS = 365


class ProfoundCategoriesError(Exception):
    pass


@frozen
class ProfoundResumeConfig:
    # Reports walk one category at a time, so resuming needs both which category was in flight and
    # how far through its pages we got.
    category_id: Optional[str] = None
    cursor: Optional[str] = None


def _headers() -> dict[str, str]:
    # X-API-Key travels through the framework auth config so its value is redacted from logs and
    # raised errors; only the non-secret headers are set here.
    return {"Accept": "application/json", "Content-Type": "application/json"}


def _to_report_date(value: Any) -> Optional[str]:
    """The report endpoints take `start_date` and `end_date` as YYYY-MM-DD."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return (parsed.astimezone(UTC) if parsed.tzinfo else parsed).date().isoformat()


def fetch_category_ids(api_key: str) -> list[str]:
    """List the organization's category ids, which every report body has to name."""
    session = make_tracked_session(redact_values=(api_key,))
    response = session.get(
        f"{PROFOUND_BASE_URL}{CATEGORIES_PATH}",
        headers={"X-API-Key": api_key, **_headers()},
        timeout=REQUEST_TIMEOUT_SECONDS,
        # The API key rides a custom header, which requests would replay to a redirect target.
        allow_redirects=False,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ProfoundCategoriesError("Profound returned an unexpected shape for the category list")
    return [str(item["id"]) for item in payload if isinstance(item, dict) and item.get("id")]


def _reference_endpoint(config: ProfoundEndpointConfig) -> Endpoint:
    endpoint: Endpoint = {
        "path": config.path,
        # These lists are small and return everything in one response.
        "paginator": SinglePagePaginator(),
    }
    if config.data_key:
        endpoint["data_selector"] = config.data_key
        # A missing wrapper key means the response shape changed; fail loud rather than syncing 0 rows.
        endpoint["data_selector_required"] = True
    return endpoint


def _report_endpoint(
    config: ProfoundEndpointConfig,
    category_id: str,
    start_date: str,
    end_date: str,
) -> Endpoint:
    return {
        "path": config.path,
        "method": "POST",
        "json": {
            "category_id": category_id,
            "start_date": start_date,
            # v2 treats end_date as inclusive, unlike the v1 reports.
            "end_date": end_date,
            # Grouping by date turns one aggregate into a daily series, and echoes `date` onto
            # every row so it can serve as the incremental cursor.
            "group_by": ["date"],
            "metrics": config.metrics,
            "limit": REPORT_PAGE_SIZE,
        },
        "data_selector": config.data_key,
        "data_selector_required": True,
        # The page token is returned inside the `info` block and goes back in the POST body.
        "paginator": JSONResponseCursorPaginator(
            cursor_path="info.next_cursor",
            cursor_param="cursor",
            param_location="json",
        ),
    }


def _report_row_mapper(category_id: str):
    """Stamp the category onto each row, and flatten the nested asset so it can be a primary key."""

    def _map(row: dict[str, Any]) -> dict[str, Any]:
        mapped = dict(row)
        mapped["category_id"] = category_id
        asset = mapped.get("asset")
        if isinstance(asset, dict):
            mapped["asset_name"] = asset.get("name")
            mapped["asset_owned"] = asset.get("owned")
        return mapped

    return _map


def _reference_resource(
    config: ProfoundEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
) -> Any:
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PROFOUND_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Key", "location": "header"},
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            # The API key rides a custom header, which requests would replay to a redirect target.
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [{"name": config.name, "endpoint": _reference_endpoint(config)}],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def _report_pages(
    config: ProfoundEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    start_date: str,
    end_date: str,
    resumable_source_manager: ResumableSourceManager[ProfoundResumeConfig],
) -> Iterator[Any]:
    """Walk each category's report in turn, resuming from whichever one was in flight."""
    category_ids = fetch_category_ids(api_key)

    resume: Optional[ProfoundResumeConfig] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()

    pending = list(category_ids)
    if resume is not None and resume.category_id in pending:
        # Categories already finished on the previous attempt are behind the saved one.
        pending = pending[pending.index(resume.category_id) :]

    for category_id in pending:
        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume is not None and resume.category_id == category_id and resume.cursor:
            initial_paginator_state = {"cursor": resume.cursor}

        def save_checkpoint(state: Optional[dict[str, Any]], category_id: str = category_id) -> None:
            # Save after a page is yielded so a crash re-yields the last page (merge dedupes on the
            # primary key) instead of skipping it.
            if state and state.get("cursor"):
                resumable_source_manager.save_state(
                    ProfoundResumeConfig(category_id=category_id, cursor=str(state["cursor"]))
                )

        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": PROFOUND_BASE_URL,
                "headers": _headers(),
                "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Key", "location": "header"},
                "request_timeout": REQUEST_TIMEOUT_SECONDS,
                # The API key rides a custom header, which requests would replay to a redirect target.
                "allow_redirects": False,
            },
            "resource_defaults": {},
            "resources": [
                {
                    "name": config.name,
                    "endpoint": _report_endpoint(config, category_id, start_date, end_date),
                    "data_map": _report_row_mapper(category_id),
                }
            ],
        }

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        yield from resource

        # A finished category must not re-seed its cursor if a later one crashes.
        resumable_source_manager.save_state(ProfoundResumeConfig(category_id=category_id, cursor=None))


def profound_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ProfoundResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    today: Optional[date] = None,
) -> SourceResponse:
    config = PROFOUND_ENDPOINTS[endpoint]

    if config.kind == "reference":
        resource = _reference_resource(config, api_key, team_id, job_id)
        return SourceResponse(
            name=endpoint,
            items=lambda: resource,
            primary_keys=config.primary_keys,
            partition_count=1,
            partition_size=1,
            partition_mode="datetime" if config.partition_key else None,
            partition_format="month" if config.partition_key else None,
            partition_keys=[config.partition_key] if config.partition_key else None,
            column_hints=resource.column_hints,
        )

    end = today or datetime.now(UTC).date()
    watermark = _to_report_date(db_incremental_field_last_value) if should_use_incremental_field else None
    start = watermark or (end - timedelta(days=DEFAULT_REPORT_LOOKBACK_DAYS)).isoformat()

    return SourceResponse(
        name=endpoint,
        items=lambda: _report_pages(
            config,
            api_key,
            team_id,
            job_id,
            start,
            end.isoformat(),
            resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # Report rows carry no documented order, and the fan-out interleaves categories, so a
        # per-batch watermark could skip a category's older days. Under "desc" the pipeline writes
        # the watermark once the whole run finishes.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    # The category list is the cheapest call that proves the key is genuine, and every report needs
    # it anyway.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{PROFOUND_BASE_URL}{CATEGORIES_PATH}",
        headers={"X-API-Key": api_key, **_headers()},
        # The key rides a custom header, which requests would replay to a redirect target.
        allow_redirects=False,
    )
    return ok
