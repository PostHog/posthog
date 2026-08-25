import time
import itertools
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import jwt
import requests
import structlog
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.settings import (
    APPLE_SEARCH_ADS_ENDPOINTS,
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    MAX_INITIAL_LOOKBACK_DAYS,
    PAGE_SIZE,
    REPORT_WINDOW_DAYS,
    AppleSearchAdsEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

APPLE_SEARCH_ADS_HOST = "https://api.searchads.apple.com"
# Apple Search Ads authenticates through Apple ID's OAuth token endpoint, not a Search Ads host.
APPLE_OAUTH_TOKEN_URL = "https://appleid.apple.com/auth/oauth2/token"
APPLE_OAUTH_AUDIENCE = "https://appleid.apple.com"
APPLE_OAUTH_SCOPE = "searchadsorg"

# Lifetime of the ES256 client-secret assertion we sign per token exchange. Apple allows up to
# 180 days; we mint a fresh short-lived one every time so no long-lived secret is stored.
CLIENT_SECRET_TTL_SECONDS = 30 * 60
REQUEST_TIMEOUT_SECONDS = 120

# Cheap org-scoped probe for credential validation: it exercises the access token *and* the
# `X-AP-Context` org id, which `/acls` would not.
CREDENTIAL_PROBE_PATH = "/campaigns"

# Apple's documented ceiling is 100 requests/minute per account, surfaced as 429 with
# `Retry-After`. The transport honors that header; POST is added to the retryable methods
# because every read path here except `/campaigns` and `/acls` is a side-effect-free POST
# (`/find`, `/reports/...`) that urllib3 would otherwise refuse to retry.
APPLE_SEARCH_ADS_RETRY = Retry(
    total=5,
    backoff_factor=1.0,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS", "POST"]),
    respect_retry_after_header=True,
    raise_on_status=False,
)

logger = structlog.get_logger(__name__)


class AppleSearchAdsAuthError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class AppleSearchAdsCredentials:
    org_id: str
    client_id: str
    team_id: str
    key_id: str
    # repr=False: keep the PEM out of tracebacks, logs, and pytest assertion diffs.
    private_key: str = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class AppleSearchAdsResumeConfig:
    # Offset into the current page set. Entity endpoints only ever use this field.
    offset: int = 0
    # ISO date of the reporting window in progress, and the campaign it was being fanned out
    # to. Both are matched by value on resume, so a changed campaign list restarts the run's
    # window range rather than silently skipping a campaign.
    window_start: Optional[str] = None
    campaign_id: Optional[int] = None


def _normalize_private_key(private_key: str) -> str:
    """Accept a PEM pasted with literal ``\\n`` escapes as well as real newlines."""
    return private_key.replace("\\n", "\n").strip()


def build_client_secret(credentials: AppleSearchAdsCredentials, *, issued_at: Optional[int] = None) -> str:
    """Sign the ES256 client-secret assertion Apple's token endpoint expects.

    Apple Search Ads has no static client secret: the caller signs a JWT with the private key
    whose public half was uploaded in the Search Ads UI (`kid` = key id, `iss` = team id,
    `sub` = client id) and presents that as `client_secret`.
    """
    now = int(issued_at if issued_at is not None else time.time())
    try:
        return jwt.encode(
            {
                "sub": credentials.client_id,
                "aud": APPLE_OAUTH_AUDIENCE,
                "iat": now,
                "exp": now + CLIENT_SECRET_TTL_SECONDS,
                "iss": credentials.team_id,
            },
            _normalize_private_key(credentials.private_key),
            algorithm="ES256",
            headers={"alg": "ES256", "kid": credentials.key_id},
        )
    except (jwt.PyJWTError, ValueError, TypeError) as e:
        raise AppleSearchAdsAuthError(
            "Could not sign the Apple Search Ads client secret. The private key must be the "
            f"unencrypted EC (P-256) PEM generated for your Search Ads API key: {e}"
        ) from e


class AppleSearchAdsClient:
    """Minimal Campaign Management API client: token minting plus JSON request helpers."""

    def __init__(
        self,
        credentials: AppleSearchAdsCredentials,
        api_version: str,
        request_logger: Optional[FilteringBoundLogger] = None,
    ) -> None:
        self._credentials = credentials
        self._base_url = f"{APPLE_SEARCH_ADS_HOST}/api/{api_version}"
        self._logger: FilteringBoundLogger = request_logger or logger
        self._access_token: Optional[str] = None
        self._session = make_tracked_session(
            retry=APPLE_SEARCH_ADS_RETRY,
            redact_values=(credentials.private_key,),
        )
        # The token exchange body carries the signed assertion and the response the bearer
        # token, neither of which the name-based sample scrubbers would recognise.
        self._token_session = make_tracked_session(
            retry=APPLE_SEARCH_ADS_RETRY,
            redact_values=(credentials.private_key,),
            capture=False,
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    def authenticate(self) -> str:
        self._access_token = self._mint_access_token()
        return self._access_token

    def _mint_access_token(self) -> str:
        client_secret = build_client_secret(self._credentials)
        response = self._token_session.post(
            APPLE_OAUTH_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._credentials.client_id,
                "client_secret": client_secret,
                "scope": APPLE_OAUTH_SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if not response.ok:
            self._logger.error(
                f"Apple Search Ads token exchange failed: status={response.status_code}, url={APPLE_OAUTH_TOKEN_URL}"
            )
            response.raise_for_status()

        access_token = response.json().get("access_token")
        if not access_token:
            raise AppleSearchAdsAuthError("Apple's token response did not contain an access token")
        return str(access_token)

    def _headers(self, requires_org_context: bool) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}
        if requires_org_context:
            headers["X-AP-Context"] = f"orgId={self._credentials.org_id}"
        return headers

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]],
        body: Optional[dict[str, Any]],
        requires_org_context: bool,
    ) -> requests.Response:
        headers = self._headers(requires_org_context)
        if method == "POST":
            return self._session.post(url, json=body or {}, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        return self._session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        requires_org_context: bool = True,
    ) -> requests.Response:
        if self._access_token is None:
            self.authenticate()

        url = f"{self._base_url}{path}"
        response = self._send(method, url, params=params, body=body, requires_org_context=requires_org_context)
        # Access tokens live an hour, which a backfill routinely outlives — re-mint once and
        # replay before treating a 401 as a credential problem.
        if response.status_code == 401:
            self.authenticate()
            response = self._send(method, url, params=params, body=body, requires_org_context=requires_org_context)
        return response

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        requires_org_context: bool = True,
    ) -> dict[str, Any]:
        response = self._request(method, path, params=params, body=body, requires_org_context=requires_org_context)
        if not response.ok:
            self._logger.error(
                f"Apple Search Ads API error: status={response.status_code}, "
                f"body={response.text}, url={self._base_url}{path}"
            )
            response.raise_for_status()

        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def probe_status(self, path: str, *, params: Optional[dict[str, Any]] = None) -> int:
        return self._request("GET", path, params=params).status_code


def validate_credentials(
    credentials: AppleSearchAdsCredentials,
    api_version: str,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Mint a token and probe one org-scoped endpoint.

    A 403 means the credentials are genuine but the role can't read this resource; accepted at
    source-create (``schema_name is None``) so a user who only granted a subset of access can
    still connect, and reported per-table otherwise.
    """
    client = AppleSearchAdsClient(credentials, api_version)
    try:
        client.authenticate()
    except AppleSearchAdsAuthError as e:
        return False, str(e)
    except requests.RequestException as e:
        return False, f"Could not exchange the Apple Search Ads credentials for an access token: {e}"

    try:
        status = client.probe_status(CREDENTIAL_PROBE_PATH, params={"limit": 1})
    except requests.RequestException as e:
        return False, f"Could not reach the Apple Search Ads API: {e}"

    if status == 200:
        return True, None
    if status == 401:
        return False, "Apple Search Ads rejected the access token. Check the client ID, team ID and key ID."
    if status == 403:
        if schema_name is None:
            return True, None
        return False, "These Apple Search Ads credentials do not have permission to read this table."
    return False, f"Apple Search Ads returned an unexpected status code: {status}"


def _today() -> date:
    return datetime.now(UTC).date()


def _to_date(value: Any) -> Optional[date]:
    """Coerce an incremental cursor value (date/datetime/ISO string) to a plain date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo is not None else value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _report_start_date(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    start_date: Optional[str],
    today: date,
) -> date:
    """First reporting day to request.

    The pipeline already shifts the stored watermark back by the schema's lookback, so it is
    used verbatim. Without a watermark the run starts at the user's configured start date, or
    a bounded default so a first sync can't walk the whole account history.
    """
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            return watermark

    configured = _to_date(start_date) if start_date else None
    if configured is not None:
        # Apple rejects a DAILY-granularity report whose startTime is more than 24 months in
        # the past with a 400, so a configured date older than that is floored here.
        return max(configured, today - timedelta(days=MAX_INITIAL_LOOKBACK_DAYS))
    return today - timedelta(days=DEFAULT_INITIAL_LOOKBACK_DAYS)


@frozen
class ReportWindow:
    start: date
    end: date


def _report_windows(start: date, end: date) -> list[ReportWindow]:
    """Split ``start..end`` (inclusive) into ascending windows of at most one week."""
    windows: list[ReportWindow] = []
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=REPORT_WINDOW_DAYS - 1), end)
        windows.append(ReportWindow(start=window_start, end=window_end))
        window_start = window_end + timedelta(days=1)
    return windows


def _report_body(window_start: date, window_end: date, offset: int) -> dict[str, Any]:
    return {
        "startTime": window_start.isoformat(),
        "endTime": window_end.isoformat(),
        "granularity": "DAILY",
        # Report in the organization's own time zone so the `date` column matches what the
        # Search Ads UI shows for the same campaign.
        "timeZone": "ORTZ",
        "selector": {
            "conditions": [],
            # No `orderBy`: Apple's sortable-field enum differs per report level and rejects
            # unknown fields, and rows are keyed by entity + date so merge order is irrelevant.
            "pagination": {"offset": offset, "limit": PAGE_SIZE},
        },
        "returnRecordsWithNoMetrics": False,
        "returnRowTotals": False,
        "returnGrandTotals": False,
    }


def _report_page_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    reporting_data = payload.get("data") or {}
    if not isinstance(reporting_data, dict):
        return []
    response = reporting_data.get("reportingDataResponse") or {}
    if not isinstance(response, dict):
        return []
    rows = response.get("row") or []
    return [row for row in rows if isinstance(row, dict)]


def flatten_report_rows(payload: dict[str, Any], campaign_id: Optional[int]) -> list[dict[str, Any]]:
    """Explode one report page into a row per entity per day.

    Apple returns one row per entity carrying a `metadata` block plus a `granularity` array of
    daily metric buckets; the warehouse wants those flattened so `date` is a real column.
    """
    flattened: list[dict[str, Any]] = []
    for row in _report_page_rows(payload):
        metadata = dict(row.get("metadata") or {})
        if campaign_id is not None:
            # Ad-group and keyword reports are requested per campaign and their metadata does
            # not repeat the campaign id the primary key needs.
            metadata.setdefault("campaignId", campaign_id)
        for daily in row.get("granularity") or []:
            if isinstance(daily, dict):
                flattened.append({**metadata, **daily})
    return flattened


def _entity_page(
    client: AppleSearchAdsClient, config: AppleSearchAdsEndpointConfig, offset: int
) -> list[dict[str, Any]]:
    if config.kind == "find":
        payload = client.request_json(
            "POST",
            config.path,
            body={"conditions": [], "pagination": {"offset": offset, "limit": PAGE_SIZE}},
            requires_org_context=config.requires_org_context,
        )
    elif config.kind == "query_page":
        payload = client.request_json(
            "GET",
            config.path,
            params={"limit": PAGE_SIZE, "offset": offset},
            requires_org_context=config.requires_org_context,
        )
    else:
        payload = client.request_json("GET", config.path, requires_org_context=config.requires_org_context)

    rows = payload.get("data")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _iter_entity_rows(
    client: AppleSearchAdsClient,
    config: AppleSearchAdsEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppleSearchAdsResumeConfig],
    resume: Optional[AppleSearchAdsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    offset = resume.offset if resume is not None else 0

    while True:
        rows = _entity_page(client, config, offset)
        if rows:
            yield rows

        if config.kind == "single" or len(rows) < PAGE_SIZE:
            break

        offset += len(rows)
        resumable_source_manager.save_state(AppleSearchAdsResumeConfig(offset=offset))


def _list_campaign_ids(client: AppleSearchAdsClient) -> list[int]:
    """Campaign ids to fan the per-campaign report endpoints out over, in a stable order."""
    campaigns_config = APPLE_SEARCH_ADS_ENDPOINTS["campaigns"]
    ids: set[int] = set()
    offset = 0
    while True:
        rows = _entity_page(client, campaigns_config, offset)
        for row in rows:
            campaign_id = row.get("id")
            if campaign_id is not None:
                ids.add(int(campaign_id))
        if len(rows) < PAGE_SIZE:
            break
        offset += len(rows)
    return sorted(ids)


ReportTask = tuple[date, date, Optional[int]]


def _report_tasks(start: date, end: date, campaign_ids: list[Optional[int]]) -> Iterator[ReportTask]:
    """Every (window, campaign) report request this run must make, lazily.

    Yielded rather than listed so a large window range never materialises as millions of
    tuples up front.
    """
    for window in _report_windows(start, end):
        for campaign_id in campaign_ids:
            yield window.start, window.end, campaign_id


def _advance_to_resume(
    make_tasks: Callable[[], Iterator[ReportTask]],
    resume: Optional[AppleSearchAdsResumeConfig],
    request_logger: FilteringBoundLogger,
) -> tuple[Iterator[ReportTask], int]:
    """Fast-forward the lazy task stream to a saved checkpoint, matched by value not position.

    A checkpoint from a different window range (e.g. the start date changed) is never found, so
    the run restarts from the first task with a fresh stream.
    """
    if resume is None or not resume.window_start:
        return make_tasks(), 0

    key = (resume.window_start, resume.campaign_id)
    tasks = make_tasks()
    for task in tasks:
        window_start, _window_end, campaign_id = task
        if (window_start.isoformat(), campaign_id) == key:
            return itertools.chain([task], tasks), resume.offset

    request_logger.debug(
        f"Apple Search Ads: saved checkpoint {key} is not in this run's window range, starting from the beginning"
    )
    return make_tasks(), 0


def _iter_report_rows(
    client: AppleSearchAdsClient,
    config: AppleSearchAdsEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AppleSearchAdsResumeConfig],
    resume: Optional[AppleSearchAdsResumeConfig],
    request_logger: FilteringBoundLogger,
    *,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    start_date: Optional[str],
) -> Iterator[list[dict[str, Any]]]:
    today = _today()
    start = _report_start_date(should_use_incremental_field, db_incremental_field_last_value, start_date, today)
    campaign_ids: list[Optional[int]] = [None]
    if config.fan_out_over_campaigns:
        campaign_ids = list(_list_campaign_ids(client))

    tasks, start_offset = _advance_to_resume(lambda: _report_tasks(start, today, campaign_ids), resume, request_logger)

    current = next(tasks, None)
    resume_offset = start_offset
    while current is not None:
        window_start, window_end, campaign_id = current
        # Peek at the next task so a completed window can checkpoint where the run should pick up.
        upcoming = next(tasks, None)
        path = config.path.format(campaign_id=campaign_id) if campaign_id is not None else config.path
        offset = resume_offset
        resume_offset = 0

        while True:
            payload = client.request_json(
                "POST",
                path,
                body=_report_body(window_start, window_end, offset),
                requires_org_context=config.requires_org_context,
            )
            rows = flatten_report_rows(payload, campaign_id)
            if rows:
                yield rows

            page_size = len(_report_page_rows(payload))
            if page_size < PAGE_SIZE:
                break

            offset += page_size
            resumable_source_manager.save_state(
                AppleSearchAdsResumeConfig(
                    offset=offset, window_start=window_start.isoformat(), campaign_id=campaign_id
                )
            )

        if upcoming is not None:
            next_window_start, _next_window_end, next_campaign_id = upcoming
            resumable_source_manager.save_state(
                AppleSearchAdsResumeConfig(
                    offset=0, window_start=next_window_start.isoformat(), campaign_id=next_campaign_id
                )
            )
        current = upcoming


def get_rows(
    credentials: AppleSearchAdsCredentials,
    endpoint: str,
    api_version: str,
    request_logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppleSearchAdsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    start_date: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APPLE_SEARCH_ADS_ENDPOINTS[endpoint]
    client = AppleSearchAdsClient(credentials, api_version, request_logger)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.kind == "report":
        yield from _iter_report_rows(
            client,
            config,
            resumable_source_manager,
            resume,
            request_logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            start_date=start_date,
        )
    else:
        yield from _iter_entity_rows(client, config, resumable_source_manager, resume)

    # The stream ran to completion; leaving the last checkpoint would make a later attempt
    # resume mid-range instead of restarting cleanly.
    resumable_source_manager.clear_state()


def apple_search_ads_source(
    credentials: AppleSearchAdsCredentials,
    endpoint: str,
    api_version: str,
    request_logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppleSearchAdsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    start_date: Optional[str] = None,
) -> SourceResponse:
    config = APPLE_SEARCH_ADS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            credentials=credentials,
            endpoint=endpoint,
            api_version=api_version,
            request_logger=request_logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            start_date=start_date,
        ),
        primary_keys=list(config.primary_keys),
        # Reporting windows are walked oldest-first, so `date` only ever moves forward across
        # batches by at most one window — which the schema's trailing lookback re-reads.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
