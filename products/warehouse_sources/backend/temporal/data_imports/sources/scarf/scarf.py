import csv
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from requests import Session

from posthog.dataclasses import frozen

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
    EVENT_BATCH_SIZE,
    LIST_PAGE_SIZE,
    NUMERIC_COLUMNS,
    REQUEST_TIMEOUT,
    ScarfEndpointConfig,
)

INVALID_TOKEN_MESSAGE = "Scarf rejected your API token. Create a new token in Scarf and reconnect."
OWNER_MESSAGE = "Scarf couldn't find that account or organization. Check the owner name, then reconnect."
PLAN_MESSAGE = "Scarf refused the export. Exports need a Scarf Basic or Premium plan, and a member role or higher."
RUNS_MESSAGE = "Your Scarf organization has no export runs left. Add runs in Scarf, then resync."
OWNER_FORMAT_MESSAGE = "Enter the Scarf user or organization name only, without a URL or slashes."


@frozen
class ScarfResumeConfig:
    # The day an event export is reading. A resume reads that whole day again; rows merge on id.
    day: str | None = None
    paginator_state: dict[str, Any] | None = None


def validate_owner(owner: str) -> str:
    stripped = owner.strip()
    if not stripped or not all(char.isalnum() or char in "-_." for char in stripped) or ".." in stripped:
        raise ValueError(OWNER_FORMAT_MESSAGE)
    return stripped


def _session(api_token: str) -> Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,), allow_redirects=False
    )


def shape_event(row: dict[str | None, str | None]) -> dict[str, Any]:
    """Turn a CSV row into typed values: empty cells are null, flags are booleans, coordinates are numbers.

    DictReader files cells past the header under a None key; they have no column to land in.
    """
    shaped: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        if value is None or value == "":
            shaped[key] = None
        elif key in BOOLEAN_COLUMNS:
            shaped[key] = value.strip().lower() == "true"
        elif key in NUMERIC_COLUMNS:
            try:
                shaped[key] = float(value)
            except ValueError:
                shaped[key] = None
        else:
            shaped[key] = value
    return shaped


def _iter_csv_rows(session: Session, url: str, params: dict[str, str]) -> Iterator[dict[str, Any]]:
    with session.get(url, params=params, stream=True, timeout=REQUEST_TIMEOUT) as response:
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        for row in csv.DictReader(response.iter_lines(decode_unicode=True)):
            yield shape_event(row)


def _watermark_day(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value).date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def iter_daily_events(
    session: Session,
    url: str,
    first_day: date,
    last_day: date,
    manager: ResumableSourceManager[ScarfResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    day = max(first_day, date.fromisoformat(resume.day)) if resume and resume.day else first_day
    while day <= last_day:
        # One day per request: a resume reads that day again, and the order of rows inside it
        # cannot move the watermark past rows not read yet.
        manager.save_state(ScarfResumeConfig(day=day.isoformat()))
        batch: list[dict[str, Any]] = []
        delivered = False
        for row in _iter_csv_rows(session, url, {"start_date": day.isoformat(), "end_date": day.isoformat()}):
            batch.append(row)
            if len(batch) >= EVENT_BATCH_SIZE:
                yield batch
                delivered = True
                batch = []
        if batch:
            yield batch
        elif not delivered:
            manager.safe_point()
        day += timedelta(days=1)


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
    today: date | None = None,
) -> SourceResponse:
    endpoint = ENDPOINTS[inputs.schema_name]
    owner = validate_owner(owner)
    url = f"{BASE_URL}{endpoint.path.replace('{owner}', owner)}"

    if endpoint.daily:
        last_day = today or datetime.now(UTC).date()
        watermark = (
            _watermark_day(inputs.db_incremental_field_last_value) if inputs.should_use_incremental_field else None
        )
        first_day = watermark or last_day - timedelta(days=backfill_days or DEFAULT_BACKFILL_DAYS)

        def items() -> Iterator[list[dict[str, Any]]]:
            return iter_daily_events(_session(api_token), url, first_day, last_day, manager)

    elif endpoint.csv_export:

        def items() -> Iterator[list[dict[str, Any]]]:
            yield list(_iter_csv_rows(_session(api_token), url, {}))

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
