import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.settings import (
    BASE_URL,
    DEFAULT_START_DATE,
    DEFAULT_UNITS,
    INCREMENTAL_OVERLAP_DAYS,
    MAX_STATIONS,
    METEOSTAT_ENDPOINTS,
    MINIMUM_START_DATE,
    MeteostatEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60

NO_STATIONS_ERROR = "No weather station IDs configured"

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


@dataclasses.dataclass(frozen=True)
class MeteostatResumeConfig:
    # Index into the configured station list of the station currently being fetched.
    station_index: int
    # ISO date (YYYY-MM-DD) of the first day the next window should fetch for that station.
    next_start: str


def _parse_station_ids(station_ids: Optional[str]) -> list[str]:
    if not station_ids:
        return []
    # Bound the number of parts split() ever materializes, regardless of how many commas the
    # input contains, so a pathological string can't burn worker memory before the MAX_STATIONS
    # check downstream ever runs.
    stations: list[str] = []
    seen: set[str] = set()
    for raw in station_ids.split(",", MAX_STATIONS)[: MAX_STATIONS + 1]:
        station = raw.strip()
        if station and station not in seen:
            seen.add(station)
            stations.append(station)
    return stations


def _coerce_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def start_date_error(start_date: Optional[str]) -> Optional[str]:
    """Validation-time check for a too-old `start_date`.

    A parsed value earlier than `MINIMUM_START_DATE` is rejected here (credential validation)
    so a new source can't be configured to run away, and re-checked in `_get_rows` so a
    previously stored configuration can't either. An unparseable value is left to the existing
    per-field validation rather than duplicated here.
    """
    parsed = _coerce_date(start_date) if start_date else None
    if parsed is not None and parsed < MINIMUM_START_DATE:
        return f"Start date can't be earlier than {MINIMUM_START_DATE.isoformat()}."
    return None


def _parse_timestamp(value: Any) -> Any:
    """Parse a Meteostat `time`/`date` string into a `datetime` for correct downstream typing.

    Falls back to the raw value when it doesn't match either observed format, so an
    unexpected response shape doesn't drop the row.
    """
    if not isinstance(value, str):
        return value
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return value


def _request_headers(api_key: str) -> dict[str, str]:
    return {"x-rapidapi-key": api_key, "x-rapidapi-host": "meteostat.p.rapidapi.com"}


def _fetch_window(
    session: requests.Session,
    headers: dict[str, str],
    endpoint: MeteostatEndpointConfig,
    station_id: str,
    window_start: date,
    window_end: date,
    units: str,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {
        "station": station_id,
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
    }
    if units != DEFAULT_UNITS:
        params["units"] = units
    url = f"{BASE_URL}{endpoint.path}?{urlencode(params)}"
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    data = response.json().get("data")
    return data if isinstance(data, list) else []


def _get_rows(
    api_key: str,
    station_ids: str,
    endpoint: MeteostatEndpointConfig,
    units: str,
    start_date: Optional[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MeteostatResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    stations = _parse_station_ids(station_ids)
    if not stations:
        raise ValueError(NO_STATIONS_ERROR)
    if len(stations) > MAX_STATIONS:
        logger.warning(f"Meteostat: {len(stations)} station IDs configured, syncing only the first {MAX_STATIONS}")
        stations = stations[:MAX_STATIONS]

    session = make_tracked_session(redact_values=(api_key,))
    headers = _request_headers(api_key)

    # Re-checked here (not just at credential validation) so a configuration stored before this
    # floor existed can't schedule a runaway backfill either.
    base_start = max(_coerce_date(start_date) or DEFAULT_START_DATE, MINIMUM_START_DATE)
    if should_use_incremental_field:
        last_value = _coerce_date(db_incremental_field_last_value)
        if last_value is not None:
            # Re-fetch a trailing overlap window: weather services can revise recent records
            # for days after they first land, and merge dedupes on the primary key.
            base_start = max(base_start, last_value - timedelta(days=INCREMENTAL_OVERLAP_DAYS))

    end_boundary = datetime.now(UTC).date()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.station_index if resume is not None else 0

    for index in range(start_index, len(stations)):
        station_id = stations[index]

        cursor = base_start
        if resume is not None and index == start_index:
            resumed_start = _coerce_date(resume.next_start)
            if resumed_start is not None:
                cursor = resumed_start
                logger.debug(f"Meteostat: resuming {endpoint.name} for station {station_id} from {cursor.isoformat()}")

        while cursor <= end_boundary:
            window_end = min(cursor + timedelta(days=endpoint.window_days - 1), end_boundary)
            data = _fetch_window(session, headers, endpoint, station_id, cursor, window_end, units)

            if data:
                rows = []
                for row in data:
                    row = dict(row)
                    row["station_id"] = station_id
                    row[endpoint.date_field] = _parse_timestamp(row.get(endpoint.date_field))
                    rows.append(row)
                yield rows

            cursor = window_end + timedelta(days=1)
            # Save AFTER yielding so a crash re-fetches (and merge dedupes) the last window
            # instead of skipping it.
            resumable_source_manager.save_state(
                MeteostatResumeConfig(station_index=index, next_start=cursor.isoformat())
            )


def meteostat_source(
    api_key: str,
    station_ids: str,
    units: str,
    start_date: Optional[str],
    endpoint_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MeteostatResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint = METEOSTAT_ENDPOINTS[endpoint_name]

    return SourceResponse(
        name=endpoint.name,
        items=lambda: _get_rows(
            api_key=api_key,
            station_ids=station_ids,
            endpoint=endpoint,
            units=units,
            start_date=start_date,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint.date_field],
        sort_mode="asc",
    )


def validate_station(api_key: str, station_id: str) -> tuple[bool, Optional[str]]:
    session = make_tracked_session(redact_values=(api_key,))
    try:
        response = session.get(
            f"{BASE_URL}/stations/meta",
            params={"id": station_id},
            headers=_request_headers(api_key),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return False, f"Could not reach the Meteostat API ({e}). Please retry."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid RapidAPI key. Check the key and try again."
    if response.status_code == 403:
        return (
            False,
            "This RapidAPI key isn't subscribed to the Meteostat API. Subscribe on RapidAPI and try again.",
        )
    if response.status_code == 404:
        return False, f"Weather station '{station_id}' was not found. Check the station ID and try again."
    return False, f"Unexpected response from the Meteostat API (status {response.status_code})."
