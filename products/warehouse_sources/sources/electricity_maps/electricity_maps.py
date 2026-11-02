import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from dateutil import parser as dateutil_parser
from requests import Request, Response, Session
from requests.exceptions import RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.settings import (
    BASE_URL,
    CARBON_INTENSITY_FORECAST,
    CARBON_INTENSITY_FORECAST_PATH,
    DEFAULT_HISTORY_DAYS,
    NODE_ENDPOINTS,
    RANGE_ENDPOINT_PATHS,
    REQUEST_TIMEOUT_SECONDS,
    WINDOW_DAYS,
    ZONES,
    ZONES_PATH,
)

# Zone identifiers are short uppercase codes like DE, DK-DK1, US-CAL-CISO. The value goes into a
# query param, so this is a sanity check for typos (a pasted URL, a lowercase zone), not a
# security boundary.
_ZONE_RE = re.compile(r"^[A-Z0-9-]+$")


@frozen
class ElectricityMapsResumeConfig:
    window_start: str
    zone_index: int


def parse_zones(zones: str) -> list[str]:
    parsed: list[str] = []
    for zone in zones.split(","):
        normalized = zone.strip().upper()
        if normalized and normalized not in parsed:
            parsed.append(normalized)
    return parsed


def parse_pricing_nodes(pricing_nodes: Optional[str]) -> list[str]:
    # Node identifiers are vendor-defined (e.g. CORTINA_1_N106), so keep their case as entered.
    parsed: list[str] = []
    for node in (pricing_nodes or "").split(","):
        normalized = node.strip()
        if normalized and normalized not in parsed:
            parsed.append(normalized)
    return parsed


def invalid_zones(zones: list[str]) -> list[str]:
    return [zone for zone in zones if not _ZONE_RE.match(zone)]


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = dateutil_parser.parse(value)
        except (ValueError, OverflowError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def initial_window_start(db_incremental_field_last_value: Optional[Any], history_days: int, now: datetime) -> datetime:
    watermark = _coerce_datetime(db_incremental_field_last_value)
    if watermark is not None:
        # Start at the watermark itself (start is inclusive) so the last synced hour is
        # re-fetched and the merge picks up any revision the vendor made to it.
        return watermark
    return now - timedelta(days=history_days)


class ElectricityMapsRangePaginator(BasePaginator):
    """Walks fixed datetime windows across every configured zone (or pricing node).

    Iteration is window-major (every zone for a window, then the next window) rather than
    zone-major. The pipeline checkpoints the incremental watermark per batch assuming ascending
    order, so a zone-major walk that finished zone A up to now before starting zone B would, on a
    crash whose resume state has expired, leave zone B a whole backfill behind the watermark.
    Window-major bounds that loss to a single window.
    """

    def __init__(
        self,
        zones: list[str],
        initial_start: datetime,
        until: datetime,
        window: timedelta,
        zone_param: str = "zone",
    ) -> None:
        super().__init__()
        self._zones = zones
        self._zone_param = zone_param
        self._until = until
        self._window = window
        self._window_start = self._clamp_start(initial_start)
        self._zone_index = 0

    def _clamp_start(self, start: datetime) -> datetime:
        # `end` is exclusive and must be after `start`, so a watermark at or past `until` still
        # produces one valid window covering the latest hour.
        return min(start, self._until - timedelta(hours=1))

    def _window_end(self) -> datetime:
        return min(self._window_start + self._window, self._until)

    def _set_params(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self._zone_param] = self._zones[self._zone_index]
        request.params["start"] = _format_datetime(self._window_start)
        request.params["end"] = _format_datetime(self._window_end())

    def init_request(self, request: Request) -> None:
        self._set_params(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._zone_index += 1
        if self._zone_index < len(self._zones):
            return

        self._zone_index = 0
        next_start = self._window_end()
        if next_start >= self._until:
            self._has_next_page = False
            return
        self._window_start = next_start

    def update_request(self, request: Request) -> None:
        self._set_params(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"window_start": _format_datetime(self._window_start), "zone_index": self._zone_index}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        window_start = _coerce_datetime(state.get("window_start"))
        if window_start is not None:
            self._window_start = self._clamp_start(window_start)
        zone_index = state.get("zone_index")
        if zone_index is not None:
            # The zone list comes from the source config, which the user can edit between the
            # save and the resume, so an out-of-range index falls back to the first zone.
            index = int(zone_index)
            self._zone_index = index if 0 <= index < len(self._zones) else 0


def _get_resource(endpoint: str, should_use_incremental_field: bool) -> EndpointResource:
    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": RANGE_ENDPOINT_PATHS[endpoint],
            "data_selector": "data",
            "data_selector_required": True,
            "params": {},
        },
        "table_format": "delta",
        "columns": {
            "datetime": {"data_type": "timestamp"},
            "updatedAt": {"data_type": "timestamp"},
            "createdAt": {"data_type": "timestamp"},
        },
    }


def _make_session(api_token: str) -> Session:
    # The auth-token header must never leave the API host, so redirects are refused.
    return make_tracked_session(headers={"auth-token": api_token}, redact_values=(api_token,), allow_redirects=False)


def _get_json(session: Session, path: str, params: Optional[dict[str, str]] = None) -> Any:
    response = session.get(f"{BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _iter_carbon_intensity_forecast(
    api_token: str,
    zones: list[str],
    resumable_source_manager: ResumableSourceManager[ElectricityMapsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    session = _make_session(api_token)
    for zone in zones:
        body = _get_json(session, CARBON_INTENSITY_FORECAST_PATH, {"zone": zone})
        forecast = body.get("forecast")
        # A full refresh replaces the table, so a malformed response must fail the sync rather than
        # silently drop this zone's rows.
        if not isinstance(forecast, list):
            raise ValueError(f"Electricity Maps returned a forecast response without a forecast list for zone {zone}")
        # Forecast points carry only the target hour and value; the zone and the forecast's issue
        # time live on the envelope.
        updated_at = _coerce_datetime(body.get("updatedAt"))
        rows = [
            {
                **point,
                "datetime": _coerce_datetime(point.get("datetime")),
                "zone": body.get("zone") or zone,
                "updatedAt": updated_at,
            }
            for point in forecast
        ]
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def _iter_zones(api_token: str) -> Iterator[list[dict[str, Any]]]:
    body = _get_json(_make_session(api_token), ZONES_PATH)
    # The response is an object keyed by zone key rather than a list.
    rows = [{**zone, "zoneKey": zone.get("zoneKey") or zone_key} for zone_key, zone in body.items()]
    if rows:
        yield rows


def electricity_maps_source(
    api_token: str,
    zones: list[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ElectricityMapsResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    history_days: Optional[int] = None,
    pricing_nodes: Optional[list[str]] = None,
) -> SourceResponse:
    if endpoint not in RANGE_ENDPOINT_PATHS and endpoint not in (CARBON_INTENSITY_FORECAST, ZONES):
        raise ValueError(f"Unknown Electricity Maps endpoint: {endpoint}")

    if endpoint == ZONES:
        return SourceResponse(name=endpoint, items=lambda: _iter_zones(api_token), primary_keys=["zoneKey"])

    is_node_endpoint = endpoint in NODE_ENDPOINTS
    entities = (pricing_nodes or []) if is_node_endpoint else zones
    if not entities:
        raise ValueError(f"No Electricity Maps {'pricing nodes' if is_node_endpoint else 'zones'} configured")

    if endpoint == CARBON_INTENSITY_FORECAST:
        return SourceResponse(
            name=endpoint,
            items=lambda: _iter_carbon_intensity_forecast(api_token, zones, resumable_source_manager),
            primary_keys=["zone", "datetime"],
            partition_keys=["datetime"],
            partition_mode="datetime",
            partition_format="month",
        )

    if history_days is None or history_days <= 0:
        history_days = DEFAULT_HISTORY_DAYS

    now = datetime.now(UTC)
    start = initial_window_start(
        db_incremental_field_last_value if should_use_incremental_field else None, history_days, now
    )
    paginator = ElectricityMapsRangePaginator(
        zones=entities,
        initial_start=start,
        until=now,
        window=timedelta(days=WINDOW_DAYS),
        zone_param="node" if is_node_endpoint else "zone",
    )

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "api_key",
                "name": "auth-token",
                "api_key": api_token,
                "location": "header",
            },
            # The auth-token header must never leave the API host: refuse redirects and pin every
            # request (including resumed ones) to the base URL's host.
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            "paginator": paginator,
        },
        "resource_defaults": {},
        "resources": [_get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {
                "window_start": resume_config.window_start,
                "zone_index": resume_config.zone_index,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("window_start"):
            resumable_source_manager.save_state(
                ElectricityMapsResumeConfig(
                    window_start=str(state["window_start"]), zone_index=int(state.get("zone_index") or 0)
                )
            )

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["entityName", "datetime"] if is_node_endpoint else ["zone", "datetime"],
        column_hints=resource.column_hints,
        partition_keys=["datetime"],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc",
    )


def validate_credentials(api_token: str, zones: list[str]) -> tuple[bool, str | None]:
    session = _make_session(api_token)
    # `/carbon-intensity/latest` is the cheapest authenticated call and is available on every
    # plan, so it both proves the token and surfaces per-zone entitlement before the first sync.
    for zone in zones:
        try:
            response = session.get(
                f"{BASE_URL}/carbon-intensity/latest", params={"zone": zone}, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except RequestException as e:
            return False, str(e)

        if response.status_code == 200:
            continue
        if response.status_code == 401:
            return False, "Electricity Maps rejected your API token. Check the token in the Electricity Maps portal."
        if response.status_code == 403:
            return (
                False,
                f"Your Electricity Maps token does not have access to zone {zone}. "
                "Check your plan in the Electricity Maps portal, or remove the zone.",
            )
        if response.status_code == 404:
            return (
                False,
                f"Electricity Maps does not recognize zone {zone}. "
                "Check the zone identifier against the Electricity Maps zone list.",
            )
        return False, f"Electricity Maps returned an unexpected status code ({response.status_code})."
    return True, None
