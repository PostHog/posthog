import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.settings import (
    BREEZOMETER_ENDPOINTS,
    BreezometerEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

# BreezoMeter's standalone API (api.breezometer.com) was sunset after Google acquired BreezoMeter and
# folded the product into Google Maps Platform. This connector targets the living successor APIs:
# the Air Quality API and the Pollen API. Both are REST/JSON, authenticated with an API key passed as
# the `key` query parameter. The per-endpoint base URLs live in `settings.py` (`config.base_url`).

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5

# Each location costs at least one request per enabled endpoint on every sync (more when a response
# paginates), so cap the config to bound worker time and outbound fan-out — a malformed/abusive
# config can't tie up the pipeline.
MAX_LOCATIONS = 100

# Defensive cap on pages followed per location so a misbehaving cursor can't loop unbounded. The
# documented windows are small (≤96 forecast hours, ≤30 history days, ≤5 pollen days), so a handful
# of pages is plenty.
MAX_PAGES_PER_LOCATION = 50

# Forecast horizon (hours). The Air Quality forecast API caps the window at 96 hours.
FORECAST_HOURS = 96
# History lookback (hours). The Air Quality history API allows up to 720 hours (30 days); 24h keeps
# each sync cheap while still building a rolling window when paired with append sync.
HISTORY_HOURS = 24
# Pollen forecast horizon (days). The Pollen API allows up to 5 days.
POLLEN_DAYS = 5


class BreezometerRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    label: str | None = None


def parse_locations(raw: str | None) -> list[Location]:
    """Parse the user's free-text ``locations`` field into coordinate pairs.

    Each non-empty line is ``lat,lon`` with an optional trailing ``,label``. Raises ``ValueError``
    with an actionable message on malformed input so the user can fix the config rather than getting
    a silently empty sync.
    """
    if not raw:
        raise ValueError("At least one location (lat,lon) is required.")

    locations: list[Location] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue

        # Split on the first two commas only so a label may itself contain commas (e.g. "New York, NY").
        parts = stripped.split(",", 2)
        if len(parts) < 2:
            raise ValueError(f"Line {line_number} ({stripped!r}) must be in the form 'lat,lon' or 'lat,lon,label'.")

        try:
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
        except ValueError:
            raise ValueError(f"Line {line_number} ({stripped!r}) has a non-numeric latitude or longitude.")

        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            raise ValueError(
                f"Line {line_number} ({stripped!r}) is out of range: latitude must be in [-90, 90] and "
                "longitude in [-180, 180]."
            )

        label = parts[2].strip() if len(parts) > 2 else None
        locations.append(Location(lat=lat, lon=lon, label=label or None))

        if len(locations) > MAX_LOCATIONS:
            raise ValueError(f"Too many locations: at most {MAX_LOCATIONS} are allowed per source.")

    if not locations:
        raise ValueError("At least one location (lat,lon) is required.")

    return locations


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    return f"{base_url}{path}?{urlencode(params)}"


# The API key is passed as the `key` query param, so it ends up in `response.url`. `raise_for_status()`
# embeds that URL in its message, which would otherwise leak the key into the sync's stored error and
# logs. Match only the `key=` query param, not any field that happens to contain "key".
_KEY_RE = re.compile(r"([?&]key=)[^&\s]+", re.IGNORECASE)


def _redact_key(text: str) -> str:
    return _KEY_RE.sub(r"\1REDACTED", text)


def _rfc3339(dt: datetime) -> str:
    """Format a datetime as RFC 3339 with a `Z` suffix, which the Google APIs expect."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_request(
    config: BreezometerEndpointConfig,
    api_key: str,
    location: Location,
    page_token: str | None,
) -> tuple[str, dict[str, Any] | None]:
    """Build the ``(url, json_body)`` for a single page of a single location.

    Air Quality endpoints are POST with a JSON body (``json_body`` is a dict); the Pollen endpoint is
    GET with query params (``json_body`` is ``None``). The API key always rides the ``key`` query param.
    """
    if config.request_kind == "pollen":
        params: dict[str, Any] = {
            "key": api_key,
            "location.latitude": location.lat,
            "location.longitude": location.lon,
            "days": POLLEN_DAYS,
        }
        if page_token:
            params["pageToken"] = page_token
        return _build_url(config.base_url, config.path, params), None

    # Air Quality (POST). The key stays in the query string; the location and request shape go in the body.
    body: dict[str, Any] = {
        "location": {"latitude": location.lat, "longitude": location.lon},
        "languageCode": "en",
    }
    if config.extra_computations:
        body["extraComputations"] = config.extra_computations
    if config.name == "air_quality_forecast":
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        body["period"] = {"startTime": _rfc3339(now), "endTime": _rfc3339(now + timedelta(hours=FORECAST_HOURS))}
    elif config.name == "air_quality_history":
        body["hours"] = HISTORY_HOURS
    if page_token:
        body["pageToken"] = page_token

    return _build_url(config.base_url, config.path, {"key": api_key}), body


@retry(
    retry=retry_if_exception_type((BreezometerRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    config: BreezometerEndpointConfig,
    api_key: str,
    location: Location,
    page_token: str | None,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    url, body = _build_request(config, api_key, location, page_token)

    if body is None:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    else:
        response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (rate limit) and transient 5xx are retryable; back off and try again.
    if response.status_code == 429 or response.status_code >= 500:
        raise BreezometerRetryableError(f"Breezometer API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"Breezometer API error: status={response.status_code}, body={_redact_key(response.text)}")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # Re-raise with the `key` redacted so the API key never reaches stored errors / logs, keeping
            # the `... for url: https://airquality.googleapis.com` prefix intact for non-retryable matching.
            raise requests.HTTPError(_redact_key(str(exc)), response=exc.response) from None

    return response.json()


def _date_obj_to_iso(value: Any) -> str | None:
    """Convert a Pollen ``date`` object (``{year, month, day}``) into an ISO 8601 UTC string."""
    if not isinstance(value, dict):
        return None
    try:
        return datetime(int(value["year"]), int(value["month"]), int(value["day"]), tzinfo=UTC).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def _datetime_str_to_iso(value: Any) -> str | None:
    """Normalize a Google ``dateTime`` string (RFC 3339, e.g. ``2023-08-11T08:00:00Z``) to ISO 8601 UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _extract_dt_iso(config: BreezometerEndpointConfig, item: dict[str, Any]) -> str | None:
    # `dt_iso` derives from this field and is part of the primary key, so index directly: a missing
    # field is a structural API change (e.g. a renamed `dateTime`/`date`) that should fail loudly with
    # a `KeyError` rather than silently dropping every row. A present-but-malformed value still parses
    # to `None` and is skipped per-row by the caller.
    if config.timestamp_kind == "date_obj":
        return _date_obj_to_iso(item[config.timestamp_field])
    return _datetime_str_to_iso(item[config.timestamp_field])


def _normalize_rows(
    config: BreezometerEndpointConfig, response: dict[str, Any], location: Location
) -> list[dict[str, Any]]:
    """Turn an API response into flat rows, stamping each with the requested coordinates.

    We inject the *requested* lat/lon (not any echoed coordinate, which can snap to a nearby grid cell
    and drift between syncs) so the ``[latitude, longitude, dt_iso]`` primary key stays stable. The raw
    timestamp field (``dateTime`` or ``date``) is preserved; ``dt_iso`` is the derived, parseable copy
    used for partitioning and as the append cursor.
    """
    if config.data_key is None:
        items: list[dict[str, Any]] = [dict(response)]
    else:
        items = [dict(item) for item in response.get(config.data_key, []) if isinstance(item, dict)]

    rows: list[dict[str, Any]] = []
    for item in items:
        item["latitude"] = location.lat
        item["longitude"] = location.lon
        item["location_label"] = location.label
        dt_iso = _extract_dt_iso(config, item)
        if dt_iso is None:
            # `dt_iso` is part of the primary key and the partition key; a row whose timestamp is
            # present but unparseable is degenerate, so skip it rather than flow a null key into the
            # merge. (A *missing* timestamp field raises in `_extract_dt_iso` — see its note.)
            continue
        item["dt_iso"] = dt_iso
        rows.append(item)

    return rows


def validate_credentials(api_key: str, locations_raw: str | None) -> tuple[bool, str | None]:
    """Probe the current air-quality endpoint with the first configured location.

    Google returns 400 (``API key not valid``) for a missing/invalid key and 403 (``PERMISSION_DENIED``)
    when the Air Quality API is not enabled for the project the key belongs to.
    """
    try:
        locations = parse_locations(locations_raw)
    except ValueError as exc:
        return False, str(exc)

    location = locations[0]
    config = BREEZOMETER_ENDPOINTS["air_quality_current"]
    url = _build_url(config.base_url, config.path, {"key": api_key})
    body = {"location": {"latitude": location.lat, "longitude": location.lon}}

    try:
        response = make_tracked_session().post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, "Could not reach the Google Maps Platform Air Quality API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (400, 403):
        return False, (
            "Invalid API key, or the Air Quality API is not enabled for your Google Cloud project. "
            "Check the key and enable the Air Quality and Pollen APIs, then reconnect."
        )

    return False, f"The Air Quality API returned an unexpected status code: {response.status_code}"


def get_rows(
    api_key: str,
    endpoint: str,
    locations: list[Location],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = BREEZOMETER_ENDPOINTS[endpoint]
    # One session reused across every location and page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    for location in locations:
        page_token: str | None = None
        for page in range(MAX_PAGES_PER_LOCATION):
            response = _fetch(session, config, api_key, location, page_token, logger)
            rows = _normalize_rows(config, response, location)
            if rows:
                yield rows

            page_token = response.get("nextPageToken")
            if not page_token:
                break
            if page == MAX_PAGES_PER_LOCATION - 1:
                logger.warning(
                    f"Breezometer: hit the {MAX_PAGES_PER_LOCATION}-page cap for endpoint={endpoint} "
                    f"at location=({location.lat},{location.lon}); stopping pagination."
                )


def breezometer_source(
    api_key: str,
    endpoint: str,
    locations_raw: str | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = BREEZOMETER_ENDPOINTS[endpoint]
    locations = parse_locations(locations_raw)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, locations=locations, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[config.partition_key],
        # Forecast/history rows arrive in ascending time order; single-snapshot endpoints have one row.
        sort_mode="asc",
    )
