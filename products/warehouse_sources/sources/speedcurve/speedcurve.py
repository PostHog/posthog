import io
import gzip
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast

from requests import Session
from requests.exceptions import HTTPError
from urllib3.util.retry import Retry

from products.warehouse_sources.sources.sdk import (
    Endpoint,
    HttpBasicAuth,
    PaginatorConfig,
    RequestPacer,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    frozen,
    make_tracked_session,
    rest_api_resource,
    schema_for_resource,
)
from products.warehouse_sources.sources.speedcurve.settings import (
    BASE_URL,
    ENDPOINTS,
    RUM_EXPORT_CHUNK_SIZE,
    RUM_EXPORT_COLUMNS,
    RUM_EXPORT_ENDPOINT,
    RUM_EXPORT_HISTORY_DAYS,
    RUM_EXPORT_READY_HOUR,
    RUM_EXPORT_REQUESTS_PER_SECOND,
    TEST_HISTORY_DAYS,
)

AUTH_ERROR = "SpeedCurve rejected the API key. Check the key and confirm that your SpeedCurve account is active."
PERMISSION_ERROR = "SpeedCurve denied access. Check the API key permissions for your team."


@frozen
class SpeedcurveResumeConfig:
    page: int
    start_timestamp: int | None
    end_timestamp: int
    # RUM export only: rows of the day at `start_timestamp` that were already handed over.
    row_offset: int = 0


REQUEST_TIMEOUT = 60


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


def _day_start(day: date) -> int:
    return int(datetime.combine(day, time(), tzinfo=UTC).timestamp())


def _day_of(timestamp: int | float | str) -> date:
    return datetime.fromtimestamp(int(timestamp), UTC).date()


def _typed(value: str, kind: type) -> Any:
    if value == "":
        return None
    if kind is str:
        return value
    try:
        return kind(value)
    except ValueError:
        return None


def _rum_export_row(line: str, day: date, index: int) -> dict[str, Any]:
    row: dict[str, Any] = {"export_date": day.isoformat(), "export_row": index}
    row.update(dict.fromkeys(name for name, _ in RUM_EXPORT_COLUMNS))
    for position, value in enumerate(line.split("^")):
        if position < len(RUM_EXPORT_COLUMNS):
            name, kind = RUM_EXPORT_COLUMNS[position]
            row[name] = _typed(value, kind)
        else:
            # SpeedCurve appends columns without notice; keep them under the names its own parser uses.
            row[f"column_{position}"] = value or None
    return row


def _rum_export_download_url(session: Session, api_key: str, api_version: str, day: date) -> str:
    response = session.get(
        f"{BASE_URL}/{api_version}/lux/export",
        params={"date": day.strftime("%Y%m%d")},
        auth=(api_key, "x"),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    download_url = response.json().get("download_url")
    if not isinstance(download_url, str) or not download_url:
        raise ValueError("SpeedCurve returned no download_url for the RUM export")
    return download_url


def _rum_export_file_rows(session: Session, download_url: str, day: date, row_offset: int) -> Iterator[dict[str, Any]]:
    with session.get(download_url, stream=True, timeout=REQUEST_TIMEOUT) as response:
        # S3 answers 403 or 404 for a day with no file, for example before the export was enabled.
        if response.status_code in (403, 404):
            return
        response.raise_for_status()
        # The io readers read once more at the end of the body, which fails on a raw stream that closed itself.
        response.raw.auto_close = False
        raw = io.BufferedReader(response.raw)
        content = gzip.GzipFile(fileobj=raw) if raw.peek(2)[:2] == b"\x1f\x8b" else raw
        for index, line in enumerate(io.TextIOWrapper(content, encoding="utf-8", errors="replace", newline="")):
            line = line.rstrip("\r\n")
            if index >= row_offset and line:
                yield _rum_export_row(line, day, index)


def _rum_export_source(
    api_key: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[SpeedcurveResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: int | float | str | None,
) -> SourceResponse:
    now = datetime.now(UTC)
    last_day = now.date() - timedelta(days=1 if now.hour >= RUM_EXPORT_READY_HOUR else 2)
    first_day = last_day - timedelta(days=RUM_EXPORT_HISTORY_DAYS - 1)
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # Each file holds one complete UTC day, so the day of the watermark was already read in full.
        first_day = _day_of(db_incremental_field_last_value) + timedelta(days=1)
    row_offset = 0
    if resumable_source_manager.can_resume():
        saved = resumable_source_manager.load_state()
        if saved is not None and saved.start_timestamp is not None:
            first_day = _day_of(saved.start_timestamp)
            last_day = _day_of(saved.end_timestamp)
            row_offset = saved.row_offset

    def save_checkpoint(day: date, offset: int) -> None:
        resumable_source_manager.save_state(
            SpeedcurveResumeConfig(
                page=1, start_timestamp=_day_start(day), end_timestamp=_day_start(last_day), row_offset=offset
            )
        )

    def items() -> Iterator[list[dict[str, Any]]]:
        pacer = RequestPacer(RUM_EXPORT_REQUESTS_PER_SECOND)
        offset = row_offset
        day = first_day
        with (
            make_tracked_session(redact_values=(api_key,)) as api_session,
            make_tracked_session(capture=False) as file_session,
        ):
            while day <= last_day:
                save_checkpoint(day, offset)
                resumable_source_manager.safe_point()
                pacer.wait_turn()
                download_url = _rum_export_download_url(api_session, api_key, api_version, day)
                chunk: list[dict[str, Any]] = []
                for row in _rum_export_file_rows(file_session, download_url, day, offset):
                    chunk.append(row)
                    if len(chunk) >= RUM_EXPORT_CHUNK_SIZE:
                        save_checkpoint(day, chunk[-1]["export_row"] + 1)
                        yield chunk
                        chunk = []
                if chunk:
                    save_checkpoint(day, chunk[-1]["export_row"] + 1)
                    yield chunk
                day += timedelta(days=1)
                offset = 0

    return SourceResponse(
        name=RUM_EXPORT_ENDPOINT,
        items=items,
        primary_keys=list(ENDPOINTS[RUM_EXPORT_ENDPOINT].primary_keys),
        partition_keys=["epoch"],
        partition_mode="datetime",
        partition_format="day",
        supports_resume=True,
        on_complete=resumable_source_manager.clear_state,
    )


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
    if endpoint == RUM_EXPORT_ENDPOINT:
        return _rum_export_source(
            api_key,
            api_version,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

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
