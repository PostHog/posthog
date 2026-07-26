import re
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.toast.settings import (
    RESTAURANT_GUID_FIELD,
    TOAST_ENDPOINTS,
    PaginationMode,
    ToastEndpointConfig,
    WindowMode,
)

TOAST_HOSTS: dict[str, str] = {
    "production": "https://ws-api.toasttab.com",
    "sandbox": "https://ws-sandbox-api.toasttab.com",
}
LOGIN_PATH = "/authentication/v1/authentication/login"
# The only access type a server-to-server API client can log in with.
MACHINE_CLIENT_ACCESS_TYPE = "TOAST_MACHINE_CLIENT"
RESTAURANT_HEADER = "Toast-Restaurant-External-ID"
NEXT_PAGE_TOKEN_HEADER = "Toast-Next-Page-Token"

REQUEST_TIMEOUT_SECONDS = 120
# Re-mint a little before the token actually lapses so a long page walk can't straddle expiry.
TOKEN_EXPIRY_SKEW_SECONDS = 60
# How far back windowed endpoints reach when the user gives no start date.
DEFAULT_BACKFILL_DAYS = 365

# Stable marker for a login that answered 200 without a usable token — matched by
# `get_non_retryable_errors`, so keep it in sync with the source class.
TOAST_LOGIN_FAILED_MESSAGE = "Toast login did not return an access token"


class ToastAuthenticationError(Exception):
    pass


@dataclasses.dataclass
class ToastResumeConfig:
    """Position of the last batch we yielded: which location, which window, which page.

    Saved after each yielded batch, so a resumed run re-fetches that page (merge dedupes on the
    primary key) rather than skipping past it.
    """

    restaurant_guid: Optional[str] = None
    # Window key: an ISO datetime for date-range endpoints, an ISO date for business-date ones.
    window_start: Optional[str] = None
    page: Optional[int] = None
    page_token: Optional[str] = None


def base_url_for(environment: str) -> str:
    host = TOAST_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid Toast environment: {environment}")
    return host


def parse_restaurant_guids(raw: Optional[str]) -> list[str]:
    """Split the comma/whitespace separated restaurant GUID field, keeping order and dropping dupes."""
    seen: set[str] = set()
    guids: list[str] = []
    for chunk in re.split(r"[,\s]+", raw or ""):
        guid = chunk.strip()
        if guid and guid not in seen:
            seen.add(guid)
            guids.append(guid)
    return guids


def format_toast_datetime(value: datetime) -> str:
    """Toast's date-range filters take ISO-8601 with a numeric UTC offset."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def coerce_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


class ToastClient:
    """Authenticated Toast API client: mints and refreshes the machine-client JWT, scopes every
    request to one restaurant, and paces requests to the endpoint's rate limit."""

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        min_request_interval_seconds: float = 0.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._min_request_interval = min_request_interval_seconds
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._last_request_at: float = 0.0
        self._session = make_tracked_session(redact_values=(client_secret,))
        # The login response carries the minted JWT under `token.accessToken`, a name the sample
        # scrubber's key denylist doesn't recognise — keep that exchange out of capture entirely.
        self._auth_session = make_tracked_session(redact_values=(client_secret,), capture=False)

    def access_token(self) -> str:
        if self._token is None or time.monotonic() >= self._token_expires_at:
            self._mint_token()
        assert self._token is not None
        return self._token

    def _mint_token(self) -> None:
        response = self._auth_session.post(
            f"{self._base_url}{LOGIN_PATH}",
            json={
                "clientId": self._client_id,
                "clientSecret": self._client_secret,
                "userAccessType": MACHINE_CLIENT_ACCESS_TYPE,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        body = response.json()
        raw_token = body.get("token") if isinstance(body, dict) else None
        token: dict[str, Any] = raw_token if isinstance(raw_token, dict) else {}
        access_token = token.get("accessToken")
        if not access_token:
            raise ToastAuthenticationError(TOAST_LOGIN_FAILED_MESSAGE)

        try:
            expires_in = float(token.get("expiresIn") or 0)
        except (TypeError, ValueError):
            expires_in = 0.0

        self._token = access_token
        self._token_expires_at = time.monotonic() + max(expires_in - TOKEN_EXPIRY_SKEW_SECONDS, 0.0)

    def _throttle(self) -> None:
        if self._min_request_interval <= 0:
            return
        wait = self._last_request_at + self._min_request_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _send(self, path: str, restaurant_guid: Optional[str], params: dict[str, Any]) -> requests.Response:
        headers = {"Authorization": f"Bearer {self.access_token()}"}
        if restaurant_guid:
            headers[RESTAURANT_HEADER] = restaurant_guid
        return self._session.get(
            f"{self._base_url}{path}",
            headers=headers,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def get(
        self,
        path: str,
        restaurant_guid: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> requests.Response:
        """GET a Toast endpoint. 429s and transient 5xx are already retried by the tracked session."""
        self._throttle()
        response = self._send(path, restaurant_guid, params or {})
        if response.status_code == 401:
            # The JWT can lapse mid-sync (or be revoked and reissued); re-mint once before giving up.
            self._token = None
            response = self._send(path, restaurant_guid, params or {})
        response.raise_for_status()
        return response


def validate_credentials(
    environment: str,
    client_id: str,
    client_secret: str,
    restaurant_guids: Optional[str],
) -> tuple[bool, Optional[str]]:
    """Confirm the API client can log in. Scopes are granted per credential and per restaurant, so a
    successful token mint is the only probe that is valid for every endpoint."""
    if not parse_restaurant_guids(restaurant_guids):
        return False, "Enter at least one Toast restaurant GUID."

    try:
        base_url = base_url_for(environment)
    except ValueError as error:
        return False, str(error)

    try:
        ToastClient(base_url, client_id, client_secret).access_token()
    except (ToastAuthenticationError, requests.RequestException):
        return False, "Invalid Toast API credentials. Check the client ID and secret for your Toast API access."

    return True, None


def resolve_window(
    config: ToastEndpointConfig,
    start_date: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    now: Optional[datetime] = None,
) -> tuple[datetime, datetime, bool]:
    """Resolve the (start, end) filter window and whether it filters on the modified timestamp."""
    window_end = now or datetime.now(UTC)
    use_modified_window = should_use_incremental_field and config.modified_window_params is not None

    window_start: Optional[datetime] = None
    if should_use_incremental_field:
        window_start = coerce_datetime(db_incremental_field_last_value)
    if window_start is None:
        window_start = coerce_datetime(start_date)
    if window_start is None:
        window_start = window_end - timedelta(days=DEFAULT_BACKFILL_DAYS)

    return min(window_start, window_end), window_end, use_modified_window


def _iter_windows(start: datetime, end: datetime, window_days: int) -> Iterator[tuple[datetime, datetime]]:
    cursor = start
    while cursor < end:
        window_end = min(cursor + timedelta(days=window_days), end)
        yield cursor, window_end
        cursor = window_end


def _iter_business_dates(start: datetime, end: datetime) -> Iterator[date]:
    day = start.astimezone(UTC).date()
    last = end.astimezone(UTC).date()
    while day <= last:
        yield day
        day += timedelta(days=1)


def iter_request_units(
    config: ToastEndpointConfig,
    window_start: datetime,
    window_end: datetime,
    use_modified_window: bool,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield `(resume key, filter params)` for each request the endpoint's window needs.

    Resume keys are ISO strings so they sort in the same order they are produced, which is what lets
    a resumed run skip everything before its checkpoint without matching it exactly.
    """
    if config.window is WindowMode.BUSINESS_DATE:
        for day in _iter_business_dates(window_start, window_end):
            yield day.isoformat(), {"businessDate": day.strftime("%Y%m%d")}
        return

    if config.window is WindowMode.DATE_RANGE:
        start_param, end_param = (
            config.modified_window_params
            if use_modified_window and config.modified_window_params is not None
            else config.window_params
        )
        for start, end in _iter_windows(window_start, window_end, config.window_days):
            yield start.isoformat(), {start_param: format_toast_datetime(start), end_param: format_toast_datetime(end)}
        return

    yield "", {}


def extract_rows(
    response: requests.Response,
    config: ToastEndpointConfig,
    restaurant_guid: str,
) -> list[dict[str, Any]]:
    try:
        body = response.json()
    except ValueError:
        return []

    if config.single_object:
        items = [body] if isinstance(body, dict) else []
    elif isinstance(body, list):
        items = [row for row in body if isinstance(row, dict)]
    elif isinstance(body, dict):
        wrapped = body.get("data")
        items = [row for row in wrapped if isinstance(row, dict)] if isinstance(wrapped, list) else []
    else:
        items = []

    return [{**row, RESTAURANT_GUID_FIELD: restaurant_guid} for row in items]


def _page_params(config: ToastEndpointConfig, page: int, page_token: Optional[str]) -> dict[str, Any]:
    if config.pagination is PaginationMode.PAGE:
        return {"page": page, "pageSize": config.page_size}
    if config.pagination is PaginationMode.PAGE_TOKEN:
        params: dict[str, Any] = {"pageSize": config.page_size}
        if page_token:
            params["pageToken"] = page_token
        return params
    return {}


def get_rows(
    client: ToastClient,
    endpoint: str,
    restaurant_guids: list[str],
    window_start: datetime,
    window_end: datetime,
    use_modified_window: bool,
    resumable_source_manager: ResumableSourceManager[ToastResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = TOAST_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.restaurant_guid not in restaurant_guids:
        # The configured locations changed since the checkpoint was written, so it no longer names a
        # position in this walk — start over rather than silently skipping every location.
        logger.debug(f"Discarding Toast resume state for unknown restaurant: {resume.restaurant_guid}")
        resume = None

    pending_resume = resume

    for restaurant_guid in restaurant_guids:
        if pending_resume is not None and restaurant_guid != pending_resume.restaurant_guid:
            continue

        active_resume = pending_resume
        pending_resume = None
        path = config.path.format(restaurant_guid=restaurant_guid)

        for unit_key, unit_params in iter_request_units(config, window_start, window_end, use_modified_window):
            if (
                active_resume is not None
                and active_resume.window_start is not None
                and unit_key < active_resume.window_start
            ):
                continue

            page = active_resume.page if active_resume is not None and active_resume.page else 1
            page_token = active_resume.page_token if active_resume is not None else None
            # Only the first unit we land on resumes mid-pagination; later ones start from the top.
            active_resume = None

            while True:
                params = {**unit_params, **_page_params(config, page, page_token)}
                response = client.get(path, restaurant_guid, params)
                rows = extract_rows(response, config, restaurant_guid)

                if rows:
                    yield rows
                    resumable_source_manager.save_state(
                        ToastResumeConfig(
                            restaurant_guid=restaurant_guid,
                            window_start=unit_key or None,
                            page=page if config.pagination is PaginationMode.PAGE else None,
                            page_token=page_token,
                        )
                    )

                if config.pagination is PaginationMode.PAGE:
                    if len(rows) < config.page_size:
                        break
                    page += 1
                elif config.pagination is PaginationMode.PAGE_TOKEN:
                    next_token = response.headers.get(NEXT_PAGE_TOKEN_HEADER)
                    if not next_token or not rows:
                        break
                    page_token = next_token
                else:
                    break

    # The walk completed, so a later attempt must start clean instead of replaying the last page.
    resumable_source_manager.clear_state()


def toast_source(
    environment: str,
    client_id: str,
    client_secret: str,
    restaurant_guids: Optional[str],
    start_date: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[ToastResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TOAST_ENDPOINTS[endpoint]
    guids = parse_restaurant_guids(restaurant_guids)
    window_start, window_end, use_modified_window = resolve_window(
        config, start_date, should_use_incremental_field, db_incremental_field_last_value
    )

    def items() -> Iterator[list[dict[str, Any]]]:
        client = ToastClient(
            base_url_for(environment),
            client_id,
            client_secret,
            min_request_interval_seconds=config.min_request_interval_seconds,
        )
        return get_rows(
            client=client,
            endpoint=endpoint,
            restaurant_guids=guids,
            window_start=window_start,
            window_end=window_end,
            use_modified_window=use_modified_window,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=list(config.primary_key),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
