import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.settings import (
    OPENWEATHER_ENDPOINTS,
    OpenWeatherEndpointConfig,
)

OPENWEATHER_BASE_URL = "https://api.openweathermap.org"

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5

# Each location costs one request per enabled endpoint on every sync, so cap the config to bound
# worker time and outbound fan-out — a malformed/abusive config can't tie up the pipeline.
MAX_LOCATIONS = 100


class OpenWeatherRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    label: str | None = None


def parse_locations(raw: str | None) -> list[Location]:
    """Parse the user's free-text ``locations`` field into coordinate pairs.

    Each non-empty line is ``lat,lon`` with an optional trailing ``,label``. Raises
    ``ValueError`` with an actionable message on malformed input so the user can fix the
    config rather than getting a silently empty sync.
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


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{OPENWEATHER_BASE_URL}{path}?{urlencode(params)}"


# The API key is passed as the `appid` query param, so it ends up in `response.url`. `raise_for_status()`
# embeds that URL in its message, which would otherwise leak the key into the sync's stored error and logs.
_APPID_RE = re.compile(r"(appid=)[^&\s]+", re.IGNORECASE)


def _redact_appid(text: str) -> str:
    return _APPID_RE.sub(r"\1REDACTED", text)


@retry(
    retry=retry_if_exception_type((OpenWeatherRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (free tier is 60 req/min) and transient 5xx are retryable; back off and try again.
    if response.status_code == 429 or response.status_code >= 500:
        raise OpenWeatherRetryableError(f"OpenWeather API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"OpenWeather API error: status={response.status_code}, body={response.text}")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # Re-raise with the `appid` redacted so the key never reaches stored errors / logs, keeping the
            # `... for url: https://api.openweathermap.org` prefix intact for `get_non_retryable_errors()`.
            raise requests.HTTPError(_redact_appid(str(exc)), response=exc.response) from None

    return response.json()


def _dt_to_iso(dt: Any) -> str | None:
    """Convert an OpenWeather Unix timestamp into an ISO 8601 UTC string for partitioning."""
    if not isinstance(dt, int | float):
        return None
    return datetime.fromtimestamp(int(dt), tz=UTC).isoformat()


def _normalize_rows(
    config: OpenWeatherEndpointConfig, response: dict[str, Any], location: Location
) -> list[dict[str, Any]]:
    """Turn an API response into flat rows, stamping each with the requested coordinates.

    We inject the *requested* lat/lon (not the response's echoed ``coord``, which can snap to the
    nearest station and drift between syncs) so the ``[lat, lon, dt]`` primary key stays stable.
    """
    if config.data_key is None:
        items: list[dict[str, Any]] = [dict(response)]
    else:
        items = [dict(item) for item in response.get(config.data_key, []) if isinstance(item, dict)]
        # The forecast response carries city metadata alongside the per-slot list; attach it so
        # rows are self-describing.
        city = response.get("city")
        if city is not None:
            for item in items:
                item.setdefault("city", city)

    for item in items:
        item["lat"] = location.lat
        item["lon"] = location.lon
        item["location_label"] = location.label
        # `dt` is part of the primary key, so a row without it is degenerate — read it directly
        # so a missing field fails loudly rather than flowing a null partition key into the merge.
        item["dt_iso"] = _dt_to_iso(item["dt"])

    return items


def validate_credentials(api_key: str, locations_raw: str | None) -> tuple[bool, str | None]:
    """Probe the current-weather endpoint with the first configured location.

    OpenWeather returns 401 for a missing/invalid key (and, since paid products live behind the
    same auth, for a key not yet subscribed to a product). A freshly created key can take up to a
    couple of hours to activate, so the message points users at that.
    """
    try:
        locations = parse_locations(locations_raw)
    except ValueError as exc:
        return False, str(exc)

    location = locations[0]
    url = _build_url(
        OPENWEATHER_ENDPOINTS["current_weather"].path,
        {"lat": location.lat, "lon": location.lon, "appid": api_key},
    )

    try:
        response = make_tracked_session().get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, "Could not reach the OpenWeather API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, (
            "Invalid OpenWeather API key. Note that a newly created key can take up to a couple of hours to activate."
        )

    return False, f"OpenWeather API returned an unexpected status code: {response.status_code}"


def get_rows(
    api_key: str,
    endpoint: str,
    locations: list[Location],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = OPENWEATHER_ENDPOINTS[endpoint]
    # One session reused across every location so urllib3 keeps the connection alive.
    session = make_tracked_session()

    for location in locations:
        url = _build_url(config.path, {"lat": location.lat, "lon": location.lon, "appid": api_key})
        response = _fetch(session, url, logger)
        rows = _normalize_rows(config, response, location)
        if rows:
            yield rows


def openweather_source(
    api_key: str,
    endpoint: str,
    locations_raw: str | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = OPENWEATHER_ENDPOINTS[endpoint]
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
        # Forecast rows arrive in ascending `dt` order; single-snapshot endpoints have one row.
        sort_mode="asc",
    )
