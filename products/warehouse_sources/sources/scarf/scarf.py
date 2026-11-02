import csv
import tempfile
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, BinaryIO, ClassVar

import pyarrow as pa
import pyarrow.compute as pc
from pyarrow import csv as pa_csv
from requests import Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.scarf.settings import (
    BASE_URL,
    BOOLEAN_COLUMNS,
    DEFAULT_BACKFILL_DAYS,
    ENDPOINTS,
    FLOAT_COLUMNS,
    INTEGER_COLUMNS,
    LIST_PAGE_SIZE,
    MAX_BACKFILL_DAYS,
    MAX_EXPORT_BYTES,
    REQUEST_TIMEOUT,
    TIMESTAMP_COLUMNS,
    ScarfEndpointConfig,
)

INVALID_TOKEN_MESSAGE = "Scarf rejected your API token. Create a new token in Scarf and reconnect."
OWNER_MESSAGE = "Scarf couldn't find that account or organization. Check the owner name, then reconnect."
PLAN_MESSAGE = "Scarf refused the export. Exports need a Scarf Basic or Premium plan, and a member role or higher."
RUNS_MESSAGE = "Your Scarf organization has no export runs left. Add runs in Scarf, then resync."
OWNER_FORMAT_MESSAGE = "Enter the Scarf user or organization name only, without a URL or slashes."
BACKFILL_MESSAGE = f"Enter between 0 and {MAX_BACKFILL_DAYS} days of event history."
EXPORT_TOO_LARGE_MESSAGE = (
    "One day of Scarf events is larger than PostHog can import in one piece. Contact PostHog support."
)


@frozen
class ScarfResumeConfig:
    # The next day an event export reads. Staged before the day it follows is handed over.
    day: str | None = None
    paginator_state: dict[str, Any] | None = None


@frozen
class ScarfExportCursor:
    """The first day the next incremental run exports. It moves on even when a day had no events."""

    cursor_kind: ClassVar[str] = "scarf_export_day"

    next_day: str


def validate_owner(owner: str) -> str:
    stripped = owner.strip()
    if not stripped or not all(char.isalnum() or char in "-_." for char in stripped) or ".." in stripped:
        raise ValueError(OWNER_FORMAT_MESSAGE)
    return stripped


def backfill_is_valid(backfill_days: int | None) -> bool:
    return backfill_days is None or 0 <= backfill_days <= MAX_BACKFILL_DAYS


def _session(api_token: str) -> Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,), allow_redirects=False
    )


def _to_utc_timestamp(column: Any) -> Any:
    # Scarf writes times in UTC, some with a zone suffix and some without, so the suffix is dropped
    # value by value before the column is read as UTC.
    naive = pc.replace_substring_regex(column, pattern=r"(Z|[+-]00(:?00)?)$", replacement="")
    return pc.assume_timezone(pc.cast(naive, pa.timestamp("us")), "UTC")


def csv_to_table(source: BinaryIO) -> pa.Table:
    """Read a Scarf CSV export into typed columns: empty cells are null, flags are booleans, measures are numbers.

    Every column is read as text first. Letting Arrow infer types would type a column differently
    from one day to the next, for example a `version` of 1.2 as a float.
    """
    header = source.readline().strip()
    has_rows = bool(source.readline().strip())
    if not header or not has_rows:
        # A day with no events is the header alone, which Arrow refuses to parse.
        return pa.table({})
    source.seek(0)
    # utf-8-sig drops a byte order mark, and the csv reader handles quoted names.
    names = next(csv.reader([header.decode("utf-8-sig")]))
    table = pa_csv.read_csv(
        source,
        convert_options=pa_csv.ConvertOptions(
            column_types=dict.fromkeys(names, pa.string()),
            # Only an empty cell is null; Arrow's default markers would also null a version named "NA".
            null_values=[""],
            strings_can_be_null=True,
        ),
    )
    columns: dict[str, Any] = {}
    for name in table.column_names:
        column: Any = table[name]
        if name in BOOLEAN_COLUMNS:
            column = pc.equal(pc.utf8_lower(column), pa.scalar("true"))
        elif name in FLOAT_COLUMNS:
            column = pc.cast(column, pa.float64())
        elif name in INTEGER_COLUMNS:
            column = pc.cast(column, pa.int64())
        elif name in TIMESTAMP_COLUMNS:
            column = _to_utc_timestamp(column)
        columns[name] = column
    return pa.table(columns)


def _read_export(session: Session, url: str, params: dict[str, str]) -> pa.Table:
    # The export is spooled to disk, so the day is held in memory once, as the Arrow table.
    with session.get(url, params=params, timeout=REQUEST_TIMEOUT, stream=True) as response:
        response.raise_for_status()
        with tempfile.TemporaryFile() as spool:
            for chunk in response.iter_content(chunk_size=1 << 20):
                if spool.tell() + len(chunk) > MAX_EXPORT_BYTES:
                    raise ValueError(EXPORT_TOO_LARGE_MESSAGE)
                spool.write(chunk)
            spool.seek(0)
            return csv_to_table(spool)


def _watermark_day(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value).date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _lookback_applied(inputs: SourceInputs) -> bool:
    before = inputs.db_incremental_field_last_value_before_lookback
    return before is not None and before != inputs.db_incremental_field_last_value


def iter_daily_events(
    session: Session,
    url: str,
    first_day: date,
    last_day: date,
    manager: ResumableSourceManager[ScarfResumeConfig],
) -> Iterator[pa.Table]:
    resume = manager.load_state() if manager.can_resume() else None
    day = max(first_day, date.fromisoformat(resume.day)) if resume and resume.day else first_day
    while day <= last_day:
        # A whole day goes to the pipeline as one item, with the next day staged before it. A
        # hand-off then never reads part of a day twice: a first sync appends, so a replayed day
        # would stay duplicated. The order of rows inside the day also cannot move the watermark.
        table = _read_export(session, url, {"start_date": day.isoformat(), "end_date": day.isoformat()})
        day += timedelta(days=1)
        manager.save_state(ScarfResumeConfig(day=day.isoformat()))
        if table.num_rows:
            yield table
        else:
            manager.safe_point()


def _list_resource(
    api_token: str,
    endpoint: ScarfEndpointConfig,
    owner: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[ScarfResumeConfig],
) -> Any:
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state:
            manager.save_state(ScarfResumeConfig(paginator_state=state))

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": api_token},
            "allow_redirects": False,
            # The next link comes from the response body, so it must stay on Scarf's API host.
            "allowed_hosts": [],
            "request_timeout": REQUEST_TIMEOUT,
        },
        "resources": [
            {
                "name": endpoint.name,
                "endpoint": {
                    "path": endpoint.path.replace("{owner}", owner),
                    "params": {"per_page": LIST_PAGE_SIZE},
                    "data_selector": "results",
                    "data_selector_required": True,
                    "paginator": JSONResponsePaginator(next_url_path="_links.next"),
                },
                "write_disposition": "replace",
                "table_format": "delta",
            }
        ],
    }
    return rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.paginator_state if resume and resume.paginator_state else None,
    )


def scarf_source(
    api_token: str,
    owner: str,
    backfill_days: int | None,
    inputs: SourceInputs,
    manager: ResumableSourceManager[ScarfResumeConfig],
    cursor_manager: SourceCursorManager[ScarfExportCursor] | None,
) -> SourceResponse:
    endpoint = ENDPOINTS[inputs.schema_name]
    owner = validate_owner(owner)
    if not backfill_is_valid(backfill_days):
        raise ValueError(BACKFILL_MESSAGE)
    url = f"{BASE_URL}{endpoint.path.replace('{owner}', owner)}"

    if endpoint.daily:
        incremental = inputs.should_use_incremental_field

        def items() -> Iterator[pa.Table]:
            today = datetime.now(UTC).date()
            cursor = cursor_manager.load() if incremental and cursor_manager is not None else None
            watermark = _watermark_day(inputs.db_incremental_field_last_value) if incremental else None
            if cursor is not None:
                first_day = date.fromisoformat(cursor.next_day)
                # A configured lookback moves the watermark back; the export day follows it.
                if watermark is not None and _lookback_applied(inputs):
                    first_day = min(first_day, watermark)
            elif watermark is not None:
                first_day = watermark
            else:
                first_day = today - timedelta(days=DEFAULT_BACKFILL_DAYS if backfill_days is None else backfill_days)
            yield from iter_daily_events(_session(api_token), url, first_day, today, manager)
            if incremental and cursor_manager is not None:
                # Today is still filling up, so the next run exports it again and merges on id.
                cursor_manager.stage(ScarfExportCursor(next_day=today.isoformat()))

    elif endpoint.csv_export:

        def items() -> Iterator[pa.Table]:
            yield _read_export(_session(api_token), url, {})

    else:
        return SourceResponse(
            name=endpoint.name,
            items=lambda: _list_resource(api_token, endpoint, owner, inputs.team_id, inputs.job_id, manager),
            primary_keys=endpoint.primary_keys,
        )

    return SourceResponse(
        name=endpoint.name,
        items=items,
        primary_keys=endpoint.primary_keys,
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        sort_mode="asc",
    )


def probe_owner(api_token: str, owner: str) -> int | None:
    """Status of a one-row package list, which checks the token and the owner together."""
    url = f"{BASE_URL}/v2/packages/{validate_owner(owner)}"
    try:
        response = _session(api_token).get(url, params={"per_page": "1"}, timeout=REQUEST_TIMEOUT)
    except Exception:
        return None
    return response.status_code
