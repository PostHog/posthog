import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from dateutil import parser as date_parser
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2Auth,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.settings import (
    CRITEO_API_VERSION,
    CRITEO_BASE_URL,
    CRITEO_ENDPOINTS,
    CRITEO_TOKEN_URL,
    DEFAULT_REPORT_CURRENCY,
    DEFAULT_REPORT_TIMEZONE,
    REPORT_DIMENSIONS,
    REPORT_METRICS,
    CriteoEndpointConfig,
)

# The audiences search caps `limit` at 100; the ads listing accepts the same, so one size fits both.
PAGE_SIZE = 100
# (connect, read). The statistics report is computed synchronously, so the read budget has to cover a
# multi-day window over a whole portfolio.
REQUEST_TIMEOUT_SECONDS = (10, 180)
# Days of statistics per report call. The endpoint returns at most 100k rows per response, and the row
# count is days x campaigns x advertisers, so keep the window small enough that a large portfolio stays
# under the cap.
REPORT_WINDOW_DAYS = 7
# Criteo serves up to two years of statistics, so that's where a first (non-incremental) sync starts.
REPORT_MAX_HISTORY_DAYS = 730

CRITEO_NO_ADVERTISERS_ERROR = (
    "Criteo returned no advertisers for these credentials. Ask an advertiser admin to grant your "
    "Criteo Partners Portal app access via its consent URL, then reconnect."
)


@dataclasses.dataclass
class CriteoResumeConfig:
    # Next `offset` to request for an offset-paginated endpoint.
    offset: Optional[int] = None
    # Advertiser the fan-out was on when state was saved; earlier advertisers are already synced.
    advertiser_id: Optional[str] = None
    # First day (ISO) of the next statistics report window to request.
    next_start_date: Optional[str] = None


class CriteoReportShapeError(Exception):
    """The statistics report returned a body we can't read rows out of."""


def _retry_policy() -> Retry:
    # Criteo's search and report endpoints are read-only POSTs, so retrying them is safe; the shared
    # default only retries idempotent verbs and would leave every Criteo call unretried. Criteo
    # rate-limits at the app level (429), so retries need real headroom.
    return Retry(
        total=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD", "OPTIONS", "POST"]),
        raise_on_status=False,
    )


def _make_auth(client_id: str, client_secret: str) -> OAuth2Auth:
    """Criteo mints 900-second bearer tokens from client credentials posted in the request body.

    The framework auth caches the token for the run and re-mints shortly before expiry, which any sync
    outliving a 15-minute window needs."""
    return OAuth2Auth(
        token_url=CRITEO_TOKEN_URL,
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        client_auth_method="body",
    )


class CriteoClient:
    """Minimal Criteo Marketing Solutions client over the tracked session.

    Criteo's collections are POST searches with JSON filter bodies, the ads listing fans out per
    advertiser, and statistics come from a date-windowed report call — none of which the declarative
    REST config expresses — so requests are issued directly here. Token minting/refresh and 429/5xx
    backoff still come from the framework."""

    def __init__(self, client_id: str, client_secret: str, api_version: str = CRITEO_API_VERSION) -> None:
        self._auth = _make_auth(client_id, client_secret)
        self._api_version = api_version
        self._session = make_tracked_session(
            retry=_retry_policy(),
            redact_values=(client_secret,),
        )

    def url(self, path: str) -> str:
        return f"{CRITEO_BASE_URL}/{self._api_version}{path}"

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        response = self._session.get(self.url(path), params=params, auth=self._auth, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, body: dict[str, Any], params: Optional[dict[str, Any]] = None) -> Any:
        response = self._session.post(
            self.url(path), json=body, params=params, auth=self._auth, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()


def _resources(payload: Any) -> list[dict[str, Any]]:
    """Rows out of Criteo's `{"data": [...], "errors": [], "warnings": []}` envelope."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _total_items(payload: Any) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    total = meta.get("totalItems")
    return total if isinstance(total, int) and not isinstance(total, bool) else None


def _flatten_resource(resource: dict[str, Any], extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Lift a Criteo resource's `attributes` into the row root.

    Every entity comes back as `{"id", "type", "attributes": {...}}`; keeping that nesting would make
    the whole payload a single struct column. The envelope `id` wins over any `id` echoed inside
    `attributes`, since that's the identifier the primary key is declared on."""
    attributes = resource.get("attributes")
    row: dict[str, Any] = dict(attributes) if isinstance(attributes, dict) else {}
    row["id"] = resource.get("id")
    row["type"] = resource.get("type")
    if extra:
        row.update(extra)
    return row


def get_advertiser_ids(client: CriteoClient) -> list[str]:
    payload = client.get(CRITEO_ENDPOINTS["advertisers"].path)
    return [str(resource["id"]) for resource in _resources(payload) if resource.get("id") is not None]


def _portfolio_rows(client: CriteoClient) -> Iterator[list[dict[str, Any]]]:
    payload = client.get(CRITEO_ENDPOINTS["advertisers"].path)
    rows = [_flatten_resource(resource) for resource in _resources(payload)]
    if rows:
        yield rows


def _search_rows(client: CriteoClient, config: CriteoEndpointConfig) -> Iterator[list[dict[str, Any]]]:
    # The campaigns and ad-sets searches document no pagination — an unfiltered search returns the
    # whole portfolio in one response.
    payload = client.post(config.path, dict(config.body or {}))
    rows = [_flatten_resource(resource) for resource in _resources(payload)]
    if rows:
        yield rows


def _paged_rows(
    client: CriteoClient,
    config: CriteoEndpointConfig,
    path: str,
    *,
    start_offset: int,
    extra: Optional[dict[str, Any]],
    save_offset: Callable[[int], None],
) -> Iterator[list[dict[str, Any]]]:
    offset = start_offset
    while True:
        params = {"limit": PAGE_SIZE, "offset": offset}
        payload = (
            client.post(path, dict(config.body), params=params)
            if config.body is not None
            else client.get(path, params=params)
        )
        resources = _resources(payload)
        if resources:
            yield [_flatten_resource(resource, extra) for resource in resources]

        # A short page is the authoritative end of the collection; `meta.totalItems` is only present on
        # some endpoints, so it's an extra stop condition rather than the primary one.
        if len(resources) < PAGE_SIZE:
            return
        offset += PAGE_SIZE
        total = _total_items(payload)
        if total is not None and offset >= total:
            return
        # Saved after the batch was yielded, so a crash re-yields the last page (merge dedupes on the
        # primary key) instead of skipping it.
        save_offset(offset)


def _per_advertiser_rows(
    client: CriteoClient,
    config: CriteoEndpointConfig,
    *,
    resume: Optional[CriteoResumeConfig],
    save_state: Callable[[CriteoResumeConfig], None],
) -> Iterator[list[dict[str, Any]]]:
    advertiser_ids = get_advertiser_ids(client)
    if not advertiser_ids:
        raise ValueError(CRITEO_NO_ADVERTISERS_ERROR)

    resume_advertiser = resume.advertiser_id if resume else None
    if resume is not None and resume_advertiser is not None and resume_advertiser in advertiser_ids:
        advertiser_ids = advertiser_ids[advertiser_ids.index(resume_advertiser) :]
        start_offset = resume.offset or 0
    else:
        # An unknown saved advertiser (the portfolio changed between attempts) restarts the fan-out
        # rather than silently skipping advertisers.
        start_offset = 0

    for index, advertiser_id in enumerate(advertiser_ids):

        def save_offset(offset: int, advertiser_id: str = advertiser_id) -> None:
            save_state(CriteoResumeConfig(advertiser_id=advertiser_id, offset=offset))

        yield from _paged_rows(
            client,
            config,
            config.path.format(advertiser_id=advertiser_id),
            start_offset=start_offset,
            extra={"_advertiser_id": advertiser_id},
            save_offset=save_offset,
        )
        start_offset = 0
        # Checkpoint the boundary as the *next* advertiser, so a retry doesn't re-walk the one that
        # just finished. Nothing is saved after the last advertiser: the run is complete and clears state.
        if index + 1 < len(advertiser_ids):
            save_state(CriteoResumeConfig(advertiser_id=advertiser_ids[index + 1]))


def _today() -> date:
    return datetime.now(UTC).date()


def _report_timestamp(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    coerced = coerce_datetime_to_utc(value)
    if coerced is not None:
        return coerced.date()
    if isinstance(value, str) and value.strip():
        try:
            return date_parser.parse(value).date()
        except (ValueError, OverflowError):
            return None
    return None


def report_start_day(db_incremental_field_last_value: Any, today: date) -> date:
    """First report day to request.

    The watermark arrives already shifted back by the schema's configured lookback, so it is used as
    given; it's only clamped to Criteo's two-year retention and to today so a future watermark can't
    produce an empty backwards range."""
    floor = today - timedelta(days=REPORT_MAX_HISTORY_DAYS)
    watermark = _as_date(db_incremental_field_last_value)
    if watermark is None:
        return floor
    return min(max(floor, watermark), today)


def _report_payload_rows(payload: Any) -> list[dict[str, Any]]:
    """Rows out of a statistics report response.

    The endpoint returns the report in the requested format rather than the JSON:API envelope the rest
    of the API uses, so a `json` report body is a bare array of rows. Criteo doesn't publish a JSON
    response schema, so the plausible wrapped shapes are accepted too, and anything else fails loud
    rather than silently syncing zero rows."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("Rows", "rows", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    raise CriteoReportShapeError(
        f"Criteo statistics report returned an unexpected body shape: {type(payload).__name__}"
    )


def _report_rows(
    client: CriteoClient,
    config: CriteoEndpointConfig,
    *,
    currency: str,
    timezone: str,
    start_day: date,
    end_day: date,
    save_state: Callable[[CriteoResumeConfig], None],
) -> Iterator[list[dict[str, Any]]]:
    advertiser_ids = get_advertiser_ids(client)
    if not advertiser_ids:
        raise ValueError(CRITEO_NO_ADVERTISERS_ERROR)

    window_start = start_day
    while window_start <= end_day:
        window_end = min(window_start + timedelta(days=REPORT_WINDOW_DAYS - 1), end_day)
        payload = client.post(
            config.path,
            {
                "advertiserIds": ",".join(advertiser_ids),
                "dimensions": list(REPORT_DIMENSIONS),
                "metrics": list(REPORT_METRICS),
                "currency": currency,
                "timezone": timezone,
                "format": "json",
                "startDate": _report_timestamp(window_start),
                "endDate": _report_timestamp(window_end),
            },
        )
        rows = _report_payload_rows(payload)
        if rows:
            yield rows

        window_start = window_end + timedelta(days=1)
        if window_start <= end_day:
            save_state(CriteoResumeConfig(next_start_date=window_start.isoformat()))


def get_rows(
    client_id: str,
    client_secret: str,
    endpoint: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[CriteoResumeConfig],
    report_currency: Optional[str] = None,
    report_timezone: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CRITEO_ENDPOINTS[endpoint]
    client = CriteoClient(client_id, client_secret, api_version)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_state(state: CriteoResumeConfig) -> None:
        resumable_source_manager.save_state(state)

    if config.kind == "portfolio":
        yield from _portfolio_rows(client)
    elif config.kind == "search":
        yield from _search_rows(client, config)
    elif config.kind == "paged" and config.per_advertiser:
        yield from _per_advertiser_rows(client, config, resume=resume, save_state=save_state)
    elif config.kind == "paged":
        yield from _paged_rows(
            client,
            config,
            config.path,
            start_offset=(resume.offset or 0) if resume else 0,
            extra=None,
            save_offset=lambda offset: save_state(CriteoResumeConfig(offset=offset)),
        )
    else:
        today = _today()
        resumed_start = _as_date(resume.next_start_date) if resume and resume.next_start_date else None
        start_day = resumed_start or report_start_day(
            db_incremental_field_last_value if should_use_incremental_field else None, today
        )
        yield from _report_rows(
            client,
            config,
            currency=report_currency or DEFAULT_REPORT_CURRENCY,
            timezone=report_timezone or DEFAULT_REPORT_TIMEZONE,
            start_day=start_day,
            end_day=today,
            save_state=save_state,
        )

    resumable_source_manager.clear_state()


def validate_credentials(client_id: str, client_secret: str, api_version: str) -> tuple[bool, Optional[str]]:
    """Mint a token and read the advertiser portfolio.

    Minting alone only proves the client credentials exist — a Criteo app also has to be granted access
    by an advertiser admin through a consent URL before any data is readable, and that shows up as a
    403 (or an empty portfolio) here rather than at the token endpoint."""
    client = CriteoClient(client_id, client_secret, api_version)
    try:
        advertiser_ids = get_advertiser_ids(client)
    except OAuth2AuthRequestError:
        return False, "Criteo rejected these credentials. Check your client ID and client secret."
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, "Criteo rejected these credentials. Check your client ID and client secret."
        if status == 403:
            return False, CRITEO_NO_ADVERTISERS_ERROR
        return False, "Could not reach the Criteo API. Please try again."
    except requests.RequestException:
        return False, "Could not reach the Criteo API. Please try again."

    if not advertiser_ids:
        return False, CRITEO_NO_ADVERTISERS_ERROR
    return True, None


def criteo_source(
    client_id: str,
    client_secret: str,
    endpoint: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[CriteoResumeConfig],
    report_currency: Optional[str] = None,
    report_timezone: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CRITEO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            client_id=client_id,
            client_secret=client_secret,
            endpoint=endpoint,
            api_version=api_version,
            resumable_source_manager=resumable_source_manager,
            report_currency=report_currency,
            report_timezone=report_timezone,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_key),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # The report is walked oldest window first, and every listing endpoint is a full refresh, so
        # rows always arrive in ascending cursor order.
        sort_mode="asc",
    )
