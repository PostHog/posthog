import dataclasses
from collections import deque
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.settings import (
    CLOUDINARY_ENDPOINTS,
    LAST_ACCESS_REPORTS_PATH,
    MAX_RESULTS,
    USAGE_HISTORY_DAYS,
    USAGE_RESTATEMENT_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CLOUDINARY_API_HOSTS = {
    "global": "https://api.cloudinary.com",
    "eu": "https://api-eu.cloudinary.com",
    "ap": "https://api-ap.cloudinary.com",
}
REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass(frozen=True)
class CloudinaryResumeConfig:
    cursor: str
    # Set for last access report resources, where a cursor only means something within one report.
    report_id: Optional[str] = None
    # Set for subfolders: the folders still to list, where `cursor` continues the first one.
    pending_folders: Optional[list[str]] = None


def base_url(cloud_name: str, region: str) -> str:
    host = CLOUDINARY_API_HOSTS.get(region, CLOUDINARY_API_HOSTS["global"])
    return f"{host}/v1_1/{cloud_name}"


def cursor_paginator() -> JSONResponseCursorPaginator:
    return JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="next_cursor")


def get_resource(endpoint: str) -> EndpointResource:
    config = CLOUDINARY_ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": f"{config.data_key}[*]",
            "path": config.path,
            "params": dict(config.params),
        },
        "table_format": "delta",
    }


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def usage_start_date(should_use_incremental_field: bool, db_incremental_field_last_value: Any, today: date) -> date:
    earliest = today - timedelta(days=USAGE_HISTORY_DAYS)
    watermark = _as_date(db_incremental_field_last_value) if should_use_incremental_field else None
    if watermark is None:
        return earliest
    return min(max(watermark - timedelta(days=USAGE_RESTATEMENT_DAYS), earliest), today)


def iter_usage(
    client: RESTClient,
    start: date,
    end: date,
    manager: ResumableSourceManager[CloudinaryResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    resumed_day = _as_date(resume.cursor) if resume else None
    day = max(resumed_day, start) if resumed_day else start
    while day <= end:
        for page in client.paginate(
            path=CLOUDINARY_ENDPOINTS["usage"].path.format(date=day.isoformat()),
            paginator=SinglePagePaginator(),
            data_selector="$",
        ):
            rows = [{**row, "date": day.isoformat()} for row in page]
            manager.save_state(CloudinaryResumeConfig(cursor=(day + timedelta(days=1)).isoformat()))
            yield rows
        day += timedelta(days=1)


def iter_subfolders(
    client: RESTClient, manager: ResumableSourceManager[CloudinaryResumeConfig]
) -> Iterator[list[dict[str, Any]]]:
    # The folder tree has no listing below the root, so walk it one folder at a time.
    resume = manager.load_state() if manager.can_resume() else None
    cursor: Optional[str] = None
    pending: deque[str] = deque()
    if resume is not None and resume.pending_folders is not None:
        pending.extend(resume.pending_folders)
        cursor = resume.cursor or None
    else:
        for page in client.paginate(
            path=CLOUDINARY_ENDPOINTS["folders"].path, params={"max_results": MAX_RESULTS}, data_selector="folders"
        ):
            pending.extend(folder["path"] for folder in page)
            manager.safe_point()

    next_cursor: dict[str, Optional[str]] = {"value": None}

    def remember_cursor(state: Optional[dict[str, Any]], has_next_page: bool) -> None:
        next_cursor["value"] = str(state["cursor"]) if has_next_page and state and state.get("cursor") else None

    endpoint_config = CLOUDINARY_ENDPOINTS["subfolders"]
    while pending:
        parent = pending.popleft()
        manager.safe_point()
        for page in client.paginate(
            path=endpoint_config.path.format(folder=quote(parent, safe="/")),
            params=dict(endpoint_config.params),
            data_selector="folders",
            initial_paginator_state={"cursor": cursor} if cursor else None,
            page_state_hook=remember_cursor,
        ):
            pending.extend(folder["path"] for folder in page)
            if next_cursor["value"]:
                manager.save_state(
                    CloudinaryResumeConfig(cursor=next_cursor["value"], pending_folders=[parent, *pending])
                )
            else:
                manager.save_state(CloudinaryResumeConfig(cursor="", pending_folders=list(pending)))
            if page:
                yield page
            else:
                manager.safe_point()
        cursor = None


def _report_state_hook(
    manager: ResumableSourceManager[CloudinaryResumeConfig], report_id: str, next_report_id: Optional[str]
) -> Callable[[Optional[dict[str, Any]], bool], None]:
    def stage(state: Optional[dict[str, Any]], has_next_page: bool) -> None:
        if has_next_page and state and state.get("cursor"):
            manager.save_state(CloudinaryResumeConfig(cursor=str(state["cursor"]), report_id=report_id))
        elif not has_next_page and next_report_id is not None:
            manager.save_state(CloudinaryResumeConfig(cursor="", report_id=next_report_id))

    return stage


def iter_last_access_report_resources(
    client: RESTClient, manager: ResumableSourceManager[CloudinaryResumeConfig]
) -> Iterator[list[dict[str, Any]]]:
    report_ids: list[str] = []
    for page in client.paginate(
        path=LAST_ACCESS_REPORTS_PATH, params={"max_results": MAX_RESULTS}, data_selector="reports"
    ):
        # A report still being generated has no resources to list yet.
        report_ids.extend(report["id"] for report in page if report.get("status") == "done")
        manager.safe_point()

    resume = manager.load_state() if manager.can_resume() else None
    cursor: Optional[str] = None
    if resume is not None and resume.report_id in report_ids:
        report_ids = report_ids[report_ids.index(resume.report_id) :]
        cursor = resume.cursor or None

    endpoint_config = CLOUDINARY_ENDPOINTS["last_access_report_resources"]
    for index, report_id in enumerate(report_ids):
        next_report_id = report_ids[index + 1] if index + 1 < len(report_ids) else None
        manager.safe_point()
        for page in client.paginate(
            path=endpoint_config.path.format(report_id=quote(report_id, safe="")),
            params=dict(endpoint_config.params),
            data_selector="resources",
            initial_paginator_state={"cursor": cursor} if cursor else None,
            page_state_hook=_report_state_hook(manager, report_id, next_report_id),
        ):
            if page:
                yield [{**row, "report_id": report_id} for row in page]
        cursor = None


def _client(cloud_name: str, api_key: str, api_secret: str, region: str) -> RESTClient:
    return RESTClient(
        base_url=base_url(cloud_name, region),
        auth=HttpBasicAuth(username=api_key, password=api_secret),
        paginator=cursor_paginator(),
    )


def _custom_items(
    endpoint: str,
    client: RESTClient,
    manager: ResumableSourceManager[CloudinaryResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    try:
        if endpoint == "usage":
            today = datetime.now(UTC).date()
            start = usage_start_date(should_use_incremental_field, db_incremental_field_last_value, today)
            yield from iter_usage(client, start, today, manager)
        elif endpoint == "subfolders":
            yield from iter_subfolders(client, manager)
        else:
            yield from iter_last_access_report_resources(client, manager)
    finally:
        client.session.close()


CUSTOM_ENDPOINTS = ("usage", "subfolders", "last_access_report_resources")


def cloudinary_source(
    cloud_name: str,
    api_key: str,
    api_secret: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloudinaryResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint_config = CLOUDINARY_ENDPOINTS[endpoint]
    partition_key = endpoint_config.partition_key
    partitioning: dict[str, Any] = {
        "partition_count": 1 if partition_key else None,
        "partition_size": 1 if partition_key else None,
        "partition_mode": "datetime" if partition_key else None,
        "partition_format": endpoint_config.partition_format if partition_key else None,
        "partition_keys": [partition_key] if partition_key else None,
    }

    if endpoint in CUSTOM_ENDPOINTS:
        return SourceResponse(
            name=endpoint,
            items=lambda: _custom_items(
                endpoint,
                _client(cloud_name, api_key, api_secret, region),
                resumable_source_manager,
                should_use_incremental_field,
                db_incremental_field_last_value,
            ),
            primary_keys=endpoint_config.primary_keys,
            sort_mode="asc",
            **partitioning,
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(cloud_name, region),
            "auth": {"type": "http_basic", "username": api_key, "password": api_secret},
            "paginator": cursor_paginator(),
        },
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(CloudinaryResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        column_hints=resource.column_hints,
        **partitioning,
    )


def validate_credentials(cloud_name: str, api_key: str, api_secret: str, region: str) -> tuple[bool, Optional[str]]:
    """Ping is the one Admin API call that costs nothing against the hourly quota."""
    try:
        response = make_tracked_session(redact_values=(api_secret,)).get(
            f"{base_url(cloud_name, region)}/ping",
            auth=(api_key, api_secret),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        return False, "Could not reach the Cloudinary API. Check your connection and try again."

    if response.ok:
        return True, None
    if response.status_code in (401, 403):
        return False, (
            "Cloudinary rejected these credentials. Check the API key and secret in your Cloudinary console, "
            "under Settings then API Keys."
        )
    if response.status_code == 404:
        return False, "Cloudinary does not recognize this cloud name. Copy it from your Cloudinary console."
    if response.status_code == 420 or response.status_code == 429:
        return False, "This Cloudinary account has hit its hourly Admin API limit. Wait for the limit to reset."
    return False, f"Cloudinary returned an unexpected error ({response.status_code}) while checking these credentials."
