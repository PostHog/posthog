"""Transport for the Open-Meteo weather API.

Hand-rolled rather than built on the shared `rest_source` framework: Open-Meteo has no list
endpoint and no pagination, responses are column-oriented (parallel arrays under `hourly`/`daily`)
and need pivoting into rows, and the archive endpoints are walked as date windows per configured
coordinate. None of that is expressible as a declarative endpoint config. It still rides
`make_tracked_session()`, so retries, rate-limit handling and egress telemetry are the framework's.
"""

import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.settings import (
    HOSTS,
    OPEN_METEO_ENDPOINTS,
    OpenMeteoEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60

# Every location costs one request per date window, so cap the config to bound worker time and
# outbound fan-out. The cap also bounds the per-window batch held in memory (see ARCHIVE_WINDOW_DAYS).
MAX_LOCATIONS = 25

# Archive backfills are walked a month at a time. One window holds every location's rows before it is
# yielded (see `_windowed_rows`), so this times MAX_LOCATIONS times 24 is the worst-case batch size:
# roughly 18k hourly rows.
ARCHIVE_WINDOW_DAYS = 31

# Labels are stamped onto every row of every batch, so an oversized one is amplified by the row
# count (a whole hourly window is ~744 rows per location). Cap it at something comfortably longer
# than any real place name.
MAX_LABEL_LENGTH = 256

# Used as the archive backfill start when the user leaves the start date blank. The archive reaches
# back to 1940, so defaulting to "everything" would be a multi-decade first sync nobody asked for.
DEFAULT_ARCHIVE_BACKFILL_DAYS = 365

# All timestamps are requested and stored in UTC so the incremental watermark and the partition key
# are comparable across locations in different zones.
REQUEST_TIMEZONE = "GMT"


@dataclasses.dataclass
class OpenMeteoResumeConfig:
    """Resume cursor.

    Windowed (archive) endpoints iterate date windows outermost and cover every location within a
    window before yielding, so `next_start_date` alone describes progress. Rolling endpoints make one
    request per location and track `location_index`.
    """

    next_start_date: str | None = None
    location_index: int = 0


@dataclasses.dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    label: str | None = None

    @property
    def id(self) -> str:
        # Stable string key so the primary key doesn't rely on float equality in the Delta merge.
        return f"{self.latitude},{self.longitude}"


def parse_locations(raw: str | None) -> list[Location]:
    """Parse the user's free-text `locations` field into coordinate pairs.

    Each non-empty line is `latitude,longitude` with an optional trailing `,label`. Raises
    `ValueError` with an actionable message on malformed input so the user can fix the config rather
    than getting a silently empty sync.
    """
    if not raw:
        raise ValueError("At least one location (latitude,longitude) is required.")

    locations: list[Location] = []
    seen: set[str] = set()
    for line_number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue

        # Split on the first two commas only so a label may itself contain commas (e.g. "New York, NY").
        parts = stripped.split(",", 2)
        if len(parts) < 2:
            raise ValueError(
                f"Line {line_number} ({stripped!r}) must be in the form 'latitude,longitude' or "
                "'latitude,longitude,label'."
            )

        try:
            latitude = float(parts[0].strip())
            longitude = float(parts[1].strip())
        except ValueError:
            raise ValueError(f"Line {line_number} ({stripped!r}) has a non-numeric latitude or longitude.")

        if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
            raise ValueError(
                f"Line {line_number} ({stripped!r}) is out of range: latitude must be in [-90, 90] and "
                "longitude in [-180, 180]."
            )

        label = parts[2].strip() if len(parts) > 2 else None
        # The label is copied onto every row, so a huge one is multiplied by the batch's row count.
        if label is not None and len(label) > MAX_LABEL_LENGTH:
            raise ValueError(
                f"Line {line_number} has a label of {len(label)} characters: at most {MAX_LABEL_LENGTH} are allowed."
            )

        location = Location(latitude=latitude, longitude=longitude, label=label or None)

        # Duplicates would collide on the `location_id` primary key and merge into one row.
        if location.id in seen:
            raise ValueError(f"Line {line_number} ({stripped!r}) repeats a location already listed above.")
        seen.add(location.id)

        locations.append(location)
        if len(locations) > MAX_LOCATIONS:
            raise ValueError(f"Too many locations: at most {MAX_LOCATIONS} are allowed per source.")

    if not locations:
        raise ValueError("At least one location (latitude,longitude) is required.")

    return locations


def parse_start_date(raw: str | None) -> date | None:
    """Parse the optional archive backfill start date (`YYYY-MM-DD`)."""
    if not raw or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ValueError(f"Start date {raw.strip()!r} must be in YYYY-MM-DD form, for example 2024-01-01.")


def base_url(endpoint: OpenMeteoEndpointConfig, api_key: str | None) -> str:
    free_host, commercial_host = HOSTS[endpoint.host]
    return commercial_host if api_key else free_host


def build_params(
    endpoint: OpenMeteoEndpointConfig,
    location: Location,
    api_key: str | None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        endpoint.block: ",".join(endpoint.variables),
        "timezone": REQUEST_TIMEZONE,
        "timeformat": "iso8601",
        **endpoint.extra_params,
    }
    if start is not None and end is not None:
        params["start_date"] = start.isoformat()
        params["end_date"] = end.isoformat()
    if api_key:
        params["apikey"] = api_key
    return params


# The commercial API key rides in the `apikey` query param, so it lands in `response.url` and in the
# message `raise_for_status()` builds. Strip it before any of that reaches stored errors or logs.
_APIKEY_RE = re.compile(r"(apikey=)[^&\s]+", re.IGNORECASE)


def _redact_apikey(text: str) -> str:
    return _APIKEY_RE.sub(r"\1REDACTED", text)


def _get_with_redacted_errors(session: requests.Session, url: str) -> requests.Response:
    """`session.get` with the API key stripped from any transport-level failure.

    urllib3 builds connection, timeout and retry-exhausted messages out of the full URL, query
    string included, and those exceptions propagate out of the sync all the way to
    `ExternalDataJob.latest_error` and the operational logs. `make_tracked_session(redact_values=...)`
    only masks the session's own log lines, not the exception it raises, so the key is scrubbed here.
    `from None` keeps the unredacted original off the chained traceback too.
    """
    try:
        return session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        redacted = _redact_apikey(str(exc))
        try:
            # The concrete class is preserved so callers keep classifying the failure as before.
            rebuilt: requests.RequestException = type(exc)(redacted)
        except Exception:
            # A subclass with a stricter signature (e.g. `JSONDecodeError`) still must not leak.
            rebuilt = requests.RequestException(redacted)
        raise rebuilt from None


def _fetch(session: requests.Session, url: str) -> dict[str, Any]:
    """Fetch one Open-Meteo response.

    Retries for 429 and transient 5xx are handled by the tracked session's adapter, so nothing is
    layered on top here. Open-Meteo answers a bad request with a 4xx whose body carries a `reason`
    string; that is surfaced verbatim because it names the offending parameter.
    """
    response = _get_with_redacted_errors(session, url)

    if not response.ok:
        reason: str | None = None
        try:
            body = response.json()
            if isinstance(body, dict):
                raw_reason = body.get("reason")
                reason = str(raw_reason) if raw_reason is not None else None
        except ValueError:
            reason = None

        if response.status_code == 401:
            raise requests.HTTPError(
                f"Open-Meteo rejected the API key (status 401): {reason or response.reason}", response=response
            )
        if 400 <= response.status_code < 500 and response.status_code != 429:
            raise requests.HTTPError(
                f"Open-Meteo rejected the request (status {response.status_code}): {reason or response.reason}",
                response=response,
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise requests.HTTPError(_redact_apikey(str(exc)), response=exc.response) from None

    return response.json()


def parse_time(value: str) -> datetime:
    """Turn an Open-Meteo timestamp into a tz-aware UTC datetime.

    Values are `2026-01-01T00:00` for hourly blocks and `2026-01-01` for daily blocks; neither
    carries an offset, and both are UTC because every request pins `timezone=GMT`.
    """
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _base_row(payload: dict[str, Any], location: Location) -> dict[str, Any]:
    """Columns stamped onto every row of a response.

    The requested coordinates are stored as `latitude`/`longitude` (they are what the primary key is
    built from and never move), while the grid cell Open-Meteo actually served is kept separately as
    `resolved_latitude`/`resolved_longitude`.
    """
    return {
        "location_id": location.id,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "location_label": location.label,
        "resolved_latitude": payload.get("latitude"),
        "resolved_longitude": payload.get("longitude"),
        "elevation": payload.get("elevation"),
        "timezone": payload.get("timezone"),
        "utc_offset_seconds": payload.get("utc_offset_seconds"),
    }


def normalize_rows(
    endpoint: OpenMeteoEndpointConfig, payload: dict[str, Any], location: Location
) -> list[dict[str, Any]]:
    """Pivot a column-oriented Open-Meteo response into one row per timestamp."""
    block = payload.get(endpoint.block)
    if not isinstance(block, dict):
        return []

    base = _base_row(payload, location)

    if endpoint.block == "current":
        # A `current` block without `time` has no partition key, so it is dropped rather than
        # raising, matching how a missing `time` array is handled for the hourly/daily blocks below.
        timestamp = block.get("time")
        if timestamp is None:
            return []
        row = {**base, **block}
        row["time_utc"] = parse_time(str(timestamp))
        return [row]

    times = block.get("time")
    if not isinstance(times, list):
        return []

    series = {name: values for name, values in block.items() if name != "time" and isinstance(values, list)}
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(times):
        row = {**base, "time": timestamp, "time_utc": parse_time(str(timestamp))}
        for name, values in series.items():
            row[name] = values[index] if index < len(values) else None
        rows.append(row)
    return rows


def _date_windows(start: date, end: date) -> Iterator[tuple[date, date]]:
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=ARCHIVE_WINDOW_DAYS - 1), end)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _windowed_rows(
    session: requests.Session,
    endpoint: OpenMeteoEndpointConfig,
    locations: list[Location],
    api_key: str | None,
    start: date,
    end: date,
    resumable_source_manager: ResumableSourceManager[OpenMeteoResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Walk the archive in date windows, emitting one batch per window.

    Date windows are the outer loop and locations the inner one so every batch is bounded above by
    the window's end timestamp for *all* locations. With locations outermost the pipeline would
    checkpoint the incremental watermark at the first location's newest row while later locations
    still had history outstanding, and a mid-sync failure would skip it permanently.
    """
    host = base_url(endpoint, api_key)
    for window_start, window_end in _date_windows(start, end):
        rows: list[dict[str, Any]] = []
        for location in locations:
            params = build_params(endpoint, location, api_key, start=window_start, end=window_end)
            payload = _fetch(session, f"{host}{endpoint.path}?{urlencode(params)}")
            rows.extend(normalize_rows(endpoint, payload, location))

        if rows:
            yield rows

        # Saved after the yield: a crash before the next window replays this one, and incremental
        # merge dedupes it on the primary key.
        next_start = window_end + timedelta(days=1)
        resumable_source_manager.save_state(OpenMeteoResumeConfig(next_start_date=next_start.isoformat()))
        logger.debug(f"Open-Meteo archive window complete. endpoint={endpoint.name}, through={window_end.isoformat()}")


def _rolling_rows(
    session: requests.Session,
    endpoint: OpenMeteoEndpointConfig,
    locations: list[Location],
    api_key: str | None,
    start_index: int,
    resumable_source_manager: ResumableSourceManager[OpenMeteoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    host = base_url(endpoint, api_key)
    for index in range(start_index, len(locations)):
        location = locations[index]
        params = build_params(endpoint, location, api_key)
        payload = _fetch(session, f"{host}{endpoint.path}?{urlencode(params)}")
        rows = normalize_rows(endpoint, payload, location)
        if rows:
            yield rows
        resumable_source_manager.save_state(OpenMeteoResumeConfig(location_index=index + 1))


def resolve_archive_range(
    configured_start: date | None,
    db_incremental_field_last_value: Any,
    today: date,
) -> tuple[date, date]:
    """Work out the archive date range for this run.

    The incremental watermark wins when present; the framework has already shifted it back by the
    schema's lookback, so recently revised ERA5 days get re-read. Otherwise the run starts at the
    user's configured date, falling back to a bounded default rather than 1940.
    """
    start = configured_start or today - timedelta(days=DEFAULT_ARCHIVE_BACKFILL_DAYS)

    if db_incremental_field_last_value is not None:
        if isinstance(db_incremental_field_last_value, datetime):
            start = db_incremental_field_last_value.astimezone(UTC).date()
        elif isinstance(db_incremental_field_last_value, date):
            start = db_incremental_field_last_value
        else:
            start = parse_time(str(db_incremental_field_last_value)).date()

    return start, today


def get_rows(
    endpoint_name: str,
    locations: list[Location],
    api_key: str | None,
    configured_start: date | None,
    db_incremental_field_last_value: Any,
    resumable_source_manager: ResumableSourceManager[OpenMeteoResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = OPEN_METEO_ENDPOINTS[endpoint_name]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    # One session reused across every request so urllib3 keeps the connection alive.
    session = make_tracked_session(redact_values=(api_key,) if api_key else ())

    if endpoint.windowed:
        start, end = resolve_archive_range(configured_start, db_incremental_field_last_value, datetime.now(UTC).date())
        if resume is not None and resume.next_start_date:
            start = date.fromisoformat(resume.next_start_date)
        if start > end:
            logger.debug(f"Open-Meteo archive is already up to date. endpoint={endpoint.name}")
        else:
            yield from _windowed_rows(
                session, endpoint, locations, api_key, start, end, resumable_source_manager, logger
            )
    else:
        start_index = resume.location_index if resume is not None else 0
        yield from _rolling_rows(session, endpoint, locations, api_key, start_index, resumable_source_manager)

    resumable_source_manager.clear_state()


def open_meteo_source(
    endpoint_name: str,
    locations_raw: str | None,
    api_key: str | None,
    start_date_raw: str | None,
    db_incremental_field_last_value: Any,
    resumable_source_manager: ResumableSourceManager[OpenMeteoResumeConfig],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint = OPEN_METEO_ENDPOINTS[endpoint_name]
    locations = parse_locations(locations_raw)
    configured_start = parse_start_date(start_date_raw)

    return SourceResponse(
        name=endpoint_name,
        items=lambda: get_rows(
            endpoint_name=endpoint_name,
            locations=locations,
            api_key=api_key,
            configured_start=configured_start,
            db_incremental_field_last_value=db_incremental_field_last_value,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
        ),
        primary_keys=endpoint.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format=endpoint.partition_format,
        partition_keys=["time_utc"],
        # Archive batches are emitted one whole date window at a time (every location included), so
        # each batch's newest timestamp is genuinely the high-water mark. Rolling endpoints return a
        # single ascending time series per request.
        sort_mode="asc",
    )


def validate_credentials(
    locations_raw: str | None, api_key: str | None, start_date_raw: str | None
) -> tuple[bool, str | None]:
    """Probe the forecast endpoint with the first configured location.

    Open-Meteo's core API is keyless, so this mostly checks that the location list is usable and the
    API is reachable. When a commercial key is supplied it also proves the key works, because the
    request then goes to the `customer-` host, which rejects an unknown key with a 401.
    """
    try:
        locations = parse_locations(locations_raw)
        parse_start_date(start_date_raw)
    except ValueError as exc:
        return False, str(exc)

    endpoint = OPEN_METEO_ENDPOINTS["weather_current"]
    params = build_params(endpoint, locations[0], api_key)
    url = f"{base_url(endpoint, api_key)}{endpoint.path}?{urlencode(params)}"

    session = make_tracked_session(redact_values=(api_key,) if api_key else ())
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, "Could not reach the Open-Meteo API. Please try again."

    if response.ok:
        return True, None
    if response.status_code == 401:
        return False, "Open-Meteo rejected the API key. Check the key in your Open-Meteo customer account."

    reason: str | None = None
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("reason") is not None:
            reason = str(body["reason"])
    except ValueError:
        reason = None

    return False, f"Open-Meteo returned status {response.status_code}{f': {reason}' if reason else ''}"
