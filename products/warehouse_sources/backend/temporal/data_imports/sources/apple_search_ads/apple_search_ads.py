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
    APPLE_ADS_API_VERSION_V1,
    APPLE_SEARCH_ADS_API_VERSION_V5,
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    PAGE_SIZE,
    REPORT_WINDOW_DAYS,
    AppleSearchAdsEndpointConfig,
    ReportingLimits,
    endpoints_for_version,
    reporting_limits_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

APPLE_SEARCH_ADS_HOST = "https://api.searchads.apple.com"
APPLE_ADS_HOST = "https://api.ads.apple.com"
# Both API versions authenticate through Apple ID's OAuth token endpoint, not an ads host.
APPLE_OAUTH_TOKEN_URL = "https://appleid.apple.com/auth/oauth2/token"
APPLE_OAUTH_AUDIENCE = "https://appleid.apple.com"
APPLE_OAUTH_SCOPE = "searchadsorg"

# Lifetime of the ES256 client-secret assertion we sign per token exchange. Apple allows up to
# 180 days; we mint a fresh short-lived one every time so no long-lived secret is stored.
CLIENT_SECRET_TTL_SECONDS = 30 * 60
REQUEST_TIMEOUT_SECONDS = 120

# Kinds whose whole result set arrives in one response, so there is no next page to ask for.
_UNPAGINATED_KINDS = frozenset({"single", "acls"})

# Where each version puts the per-day metric buckets on a report row.
_REPORT_METRICS_KEY = {
    APPLE_SEARCH_ADS_API_VERSION_V5: "granularity",
    APPLE_ADS_API_VERSION_V1: "granularMetrics",
}

# Apple's documented ceiling is 100 requests/minute per account, surfaced as 429 with
# `Retry-After`. The transport honors that header; POST is added to the retryable methods
# because every read path here except v5's `/campaigns` and `/acls` is a side-effect-free POST
# (`/find`, `/query`, `/reports/...`) that urllib3 would otherwise refuse to retry.
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
    client_id: str
    team_id: str
    key_id: str
    # repr=False: keep the PEM out of tracebacks, logs, and pytest assertion diffs.
    private_key: str = dataclasses.field(repr=False)
    # v5 scopes every request to an organization, the Platform API to an ad account, and the
    # two are different identifiers. Which one a source needs follows its version pin, which
    # the connect form cannot express — so both are optional here and `validate_credentials`
    # enforces the one that applies.
    org_id: Optional[str] = None
    ad_account_id: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class AppleSearchAdsResumeConfig:
    # Offset into the current page set.
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

    Apple has no static client secret: the caller signs a JWT with the private key whose public
    half was uploaded in the Apple Ads UI (`kid` = key id, `iss` = team id, `sub` = client id)
    and presents that as `client_secret`. Unchanged between v5 and the Platform API.
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
            "Could not sign the Apple Ads client secret. The private key must be the unencrypted "
            f"EC (P-256) PEM generated for your Apple Ads API client: {e}"
        ) from e


def base_url_for_version(api_version: str) -> str:
    if api_version == APPLE_ADS_API_VERSION_V1:
        return f"{APPLE_ADS_HOST}/{api_version}"
    return f"{APPLE_SEARCH_ADS_HOST}/api/{api_version}"


def _context_header(credentials: AppleSearchAdsCredentials, api_version: str) -> str:
    if api_version == APPLE_ADS_API_VERSION_V1:
        return f"adAccountId={credentials.ad_account_id}"
    return f"orgId={credentials.org_id}"


def missing_context_id(credentials: AppleSearchAdsCredentials, api_version: str) -> Optional[str]:
    """Message naming the context id this version needs, when the form did not collect it."""
    if api_version == APPLE_ADS_API_VERSION_V1:
        if not credentials.ad_account_id:
            return (
                "Enter the ad account ID. The Apple Ads Platform API scopes every request to an "
                "ad account, which is not the same as the organization ID the older API used."
            )
        return None
    if not credentials.org_id:
        return "Enter the organization ID. The Apple Search Ads API scopes every request to an organization."
    return None


class AppleSearchAdsClient:
    """Minimal Apple Ads client: token minting plus JSON request helpers."""

    def __init__(
        self,
        credentials: AppleSearchAdsCredentials,
        api_version: str,
        request_logger: Optional[FilteringBoundLogger] = None,
    ) -> None:
        self._credentials = credentials
        self._api_version = api_version
        self._base_url = base_url_for_version(api_version)
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
                f"Apple Ads token exchange failed: status={response.status_code}, url={APPLE_OAUTH_TOKEN_URL}"
            )
            response.raise_for_status()

        access_token = response.json().get("access_token")
        if not access_token:
            raise AppleSearchAdsAuthError("Apple's token response did not contain an access token")
        return str(access_token)

    def _headers(self, requires_context: bool) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}
        if requires_context:
            headers["X-AP-Context"] = _context_header(self._credentials, self._api_version)
        return headers

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]],
        body: Optional[dict[str, Any]],
        requires_context: bool,
    ) -> requests.Response:
        headers = self._headers(requires_context)
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
        requires_context: bool = True,
    ) -> requests.Response:
        if self._access_token is None:
            self.authenticate()

        url = f"{self._base_url}{path}"
        response = self._send(method, url, params=params, body=body, requires_context=requires_context)
        # Access tokens live an hour, which a backfill routinely outlives — re-mint once and
        # replay before treating a 401 as a credential problem.
        if response.status_code == 401:
            self.authenticate()
            response = self._send(method, url, params=params, body=body, requires_context=requires_context)
        return response

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        requires_context: bool = True,
    ) -> dict[str, Any]:
        response = self._request(method, path, params=params, body=body, requires_context=requires_context)
        if not response.ok:
            self._logger.error(
                f"Apple Ads API error: status={response.status_code}, body={response.text}, url={self._base_url}{path}"
            )
            response.raise_for_status()

        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def probe_status(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
    ) -> int:
        return self._request(method, path, params=params, body=body).status_code


def validate_credentials(
    credentials: AppleSearchAdsCredentials,
    api_version: str,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Mint a token and probe one account-scoped endpoint.

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
        return False, f"Could not exchange the Apple Ads credentials for an access token: {e}"

    # Checked after the token exchange so a bad key pair is reported as such, and so the
    # message can name the ids this API client can actually read.
    missing = missing_context_id(credentials, api_version)
    if missing is not None:
        return False, missing + _readable_ad_accounts(client, api_version)

    # The campaign list is the cheapest account-scoped read: it exercises the access token
    # *and* the `X-AP-Context` id, which the ACL endpoint would not.
    config = endpoints_for_version(api_version)["campaigns"]
    request = page_request(config, api_version, RequestScope(), offset=0, page_size=1)
    try:
        status = client.probe_status(request.method, request.path, params=request.params, body=request.body)
    except requests.RequestException as e:
        return False, f"Could not reach the Apple Ads API: {e}"

    if status == 200:
        return True, None
    if status == 401:
        return False, "Apple rejected the access token. Check the client ID, team ID and key ID."
    if status == 403:
        if schema_name is None:
            return True, None
        return False, (
            "These Apple Ads credentials cannot read this table. Give the API user the API "
            "Account Read Only role for this ad account in Apple Ads."
        )
    return False, f"The Apple Ads API returned an unexpected status code: {status}"


def _readable_ad_accounts(client: AppleSearchAdsClient, api_version: str) -> str:
    """Sentence naming the ad accounts these credentials can read, to append to an error.

    Best effort. The ACL lookup carries no context id, so it works before one is entered, but
    a failure here must not replace the more useful message asking for the id.
    """
    if api_version != APPLE_ADS_API_VERSION_V1:
        return ""

    config = endpoints_for_version(api_version)["acls"]
    request = page_request(config, api_version, RequestScope(), offset=0)
    try:
        payload = client.request_json(
            request.method, request.path, params=request.params, body=request.body, requires_context=False
        )
    except (requests.RequestException, ValueError):
        return ""

    named = []
    for account in flatten_acl_rows(page_rows(payload, config, api_version)):
        account_id = account.get("id")
        if account_id is None:
            continue
        name = account.get("name")
        named.append(f"{account_id} ({name})" if name else str(account_id))

    if not named:
        return " These credentials cannot read any ad account yet. Check the API user's role in Apple Ads."
    return " These credentials can read: " + ", ".join(named) + "."


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
    limits: ReportingLimits,
) -> date:
    """First reporting day to request.

    The pipeline already shifts the stored watermark back by the schema's lookback, so it is
    used verbatim. Without a watermark the run starts at the user's configured start date, or
    a bounded default so a first sync can't walk the whole account history. Everything is
    floored at the version's oldest requestable day, including the watermark — Apple serves no
    DAILY data past it, so a source that fell further behind would otherwise fail every run
    instead of resuming at the oldest day it can still read.
    """
    floor = today - timedelta(days=limits.max_lookback_days)

    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            return max(watermark, floor)

    configured = _to_date(start_date) if start_date else None
    if configured is not None:
        return max(configured, floor)
    return max(today - timedelta(days=DEFAULT_INITIAL_LOOKBACK_DAYS), floor)


@frozen
class ReportWindow:
    start: date
    end: date


@frozen
class RequestScope:
    """One paginated request series: an optional campaign, and an optional reporting window."""

    campaign_id: Optional[int] = None
    window: Optional[ReportWindow] = None


def _report_windows(start: date, end: date, min_window_days: int = 1) -> list[ReportWindow]:
    """Split ``start..end`` (inclusive) into ascending windows of at most one week."""
    windows: list[ReportWindow] = []
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=REPORT_WINDOW_DAYS - 1), end)
        if (window_end - window_start).days + 1 < min_window_days:
            # The Platform API rejects a DAILY range covering a single day, so a short trailing
            # window reaches back until it is long enough. Report tables merge on their primary
            # key, so re-reading a day already imported cannot duplicate rows.
            window_start = window_end - timedelta(days=min_window_days - 1)
        windows.append(ReportWindow(start=window_start, end=window_end))
        window_start = window_end + timedelta(days=1)
    return windows


def _v5_report_body(window: ReportWindow, offset: int, page_size: int) -> dict[str, Any]:
    return {
        "startTime": window.start.isoformat(),
        "endTime": window.end.isoformat(),
        "granularity": "DAILY",
        # Report in the organization's own time zone so the `date` column matches what the
        # Apple Ads UI shows for the same campaign.
        "timeZone": "ORTZ",
        "selector": {
            "conditions": [],
            # No `orderBy`: Apple's sortable-field enum differs per report level and rejects
            # unknown fields, and rows are keyed by entity + date so merge order is irrelevant.
            "pagination": {"offset": offset, "limit": page_size},
        },
        "returnRecordsWithNoMetrics": False,
        "returnRowTotals": False,
        "returnGrandTotals": False,
    }


def _platform_report_body(
    window: ReportWindow, campaign_id: Optional[int], offset: int, page_size: int
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "pagination": {"offset": offset, "pageSize": page_size},
        "timeRange": {
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            # Report in the ad account's own time zone so the `date` column matches what the
            # Apple Ads UI shows for the same campaign.
            "timeZone": "ORTZ",
            "granularity": "DAILY",
        },
    }
    if campaign_id is not None:
        body["filters"] = [_campaign_filter(campaign_id, as_string=True)]
    # No `groupBy`: it splits each entity's metrics across dimension values, and these tables
    # carry one row per entity per day.
    return body


def _campaign_filter(campaign_id: int, *, as_string: bool) -> dict[str, Any]:
    # Apple documents the report filter's value as an array of strings, and the entity query
    # filter's as the field's own integer type.
    value: Any = [str(campaign_id)] if as_string else campaign_id
    return {"field": "campaignId", "operator": "EQUALS", "value": value}


def _platform_query_body(scope: RequestScope, offset: int, page_size: int) -> dict[str, Any]:
    body: dict[str, Any] = {"pagination": {"offset": offset, "pageSize": page_size}}
    if scope.campaign_id is not None:
        body["filters"] = [_campaign_filter(scope.campaign_id, as_string=False)]
    return body


@frozen
class PageRequest:
    """HTTP method, path, query params and JSON body for one page of a request."""

    method: str
    path: str
    params: Optional[dict[str, Any]] = None
    body: Optional[dict[str, Any]] = None


def page_request(
    config: AppleSearchAdsEndpointConfig,
    api_version: str,
    scope: RequestScope,
    offset: int,
    page_size: int = PAGE_SIZE,
) -> PageRequest:
    """HTTP method, path, query params and JSON body for one page of ``config``."""
    path = config.path
    if scope.campaign_id is not None and "{campaign_id}" in path:
        path = path.format(campaign_id=scope.campaign_id)

    if config.kind == "report":
        if scope.window is None:
            raise ValueError(f"Apple Ads: a {config.name} request needs a reporting window")
        if api_version == APPLE_ADS_API_VERSION_V1:
            body = _platform_report_body(scope.window, scope.campaign_id, offset, page_size)
        else:
            body = _v5_report_body(scope.window, offset, page_size)
        return PageRequest(method="POST", path=path, body=body)
    if config.kind == "query":
        return PageRequest(method="POST", path=path, body=_platform_query_body(scope, offset, page_size))
    if config.kind == "find":
        return PageRequest(
            method="POST",
            path=path,
            body={"conditions": [], "pagination": {"offset": offset, "limit": page_size}},
        )
    if config.kind == "query_page":
        return PageRequest(method="GET", path=path, params={"limit": page_size, "offset": offset})
    return PageRequest(method="GET", path=path)


def page_rows(payload: dict[str, Any], config: AppleSearchAdsEndpointConfig, api_version: str) -> list[dict[str, Any]]:
    """Entity rows on one page — what pagination counts, before any flattening."""
    if api_version == APPLE_ADS_API_VERSION_V1:
        result = payload.get("result")
        if config.kind == "report":
            rows = result.get("rows") if isinstance(result, dict) else None
        elif config.kind == "acls":
            rows = result.get("acls") if isinstance(result, dict) else None
        else:
            rows = result
    elif config.kind == "report":
        data = payload.get("data")
        response = data.get("reportingDataResponse") if isinstance(data, dict) else None
        rows = response.get("row") if isinstance(response, dict) else None
    else:
        rows = payload.get("data")

    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def flatten_report_rows(
    rows: list[dict[str, Any]],
    *,
    metrics_key: str,
    entity_id_field: Optional[str] = None,
    campaign_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Explode report rows into a row per entity per day.

    Apple returns one row per entity carrying a `metadata` block plus an array of daily metric
    buckets; the warehouse wants those flattened so `date` is a real column.
    """
    flattened: list[dict[str, Any]] = []
    for row in rows:
        metadata = dict(row.get("metadata") or {})
        if entity_id_field is not None:
            # The Platform API names every report level's own entity `id`, where v5 named it
            # `campaignId`/`adGroupId`/`keywordId`. Project it back so the table keeps the
            # primary key it had, and so the column does not arrive twice under two names.
            entity_id = metadata.pop("id", None)
            if entity_id is not None:
                metadata.setdefault(entity_id_field, entity_id)
        if campaign_id is not None:
            # v5's ad-group and keyword report metadata does not repeat the campaign id the
            # primary key needs. The Platform API does supply it, so this only fills a gap.
            metadata.setdefault("campaignId", campaign_id)
        for daily in row.get(metrics_key) or []:
            if isinstance(daily, dict):
                flattened.append({**metadata, **daily})
    return flattened


def flatten_acl_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per ad account the credentials can read.

    The Platform API nests the account under `adAccount` and lists the caller's roles beside
    it. Flattening keeps `orgId` a column while `id` — the value the connect form asks for —
    identifies the row.
    """
    flattened: list[dict[str, Any]] = []
    for entry in rows:
        account = entry.get("adAccount")
        if isinstance(account, dict):
            flattened.append({**account, "roles": entry.get("roles") or []})
    return flattened


def _project_rows(
    rows: list[dict[str, Any]],
    config: AppleSearchAdsEndpointConfig,
    api_version: str,
    campaign_id: Optional[int],
) -> list[dict[str, Any]]:
    if config.kind == "report":
        return flatten_report_rows(
            rows,
            metrics_key=_REPORT_METRICS_KEY[api_version],
            entity_id_field=config.entity_id_field,
            campaign_id=campaign_id,
        )
    if config.kind == "acls":
        return flatten_acl_rows(rows)
    return rows


def _list_campaign_ids(client: AppleSearchAdsClient, api_version: str) -> list[int]:
    """Campaign ids to scope the per-campaign endpoints by, in a stable order."""
    config = endpoints_for_version(api_version)["campaigns"]
    ids: set[int] = set()
    offset = 0
    while True:
        request = page_request(config, api_version, RequestScope(), offset)
        payload = client.request_json(
            request.method,
            request.path,
            params=request.params,
            body=request.body,
            requires_context=config.requires_context,
        )
        rows = page_rows(payload, config, api_version)
        for row in rows:
            campaign_id = row.get("id")
            if campaign_id is not None:
                ids.add(int(campaign_id))
        if len(rows) < PAGE_SIZE:
            break
        offset += len(rows)
    return sorted(ids)


def _scopes(campaign_ids: list[Optional[int]], windows: Optional[list[ReportWindow]]) -> Iterator[RequestScope]:
    """Every paginated request series this run must make, lazily.

    ``windows is None`` for the entity tables, which are not date-bounded. Yielded rather than
    listed so a large window range never materialises as millions of tuples up front.
    """
    if windows is None:
        for campaign_id in campaign_ids:
            yield RequestScope(campaign_id=campaign_id)
        return
    for window in windows:
        for campaign_id in campaign_ids:
            yield RequestScope(campaign_id=campaign_id, window=window)


def _scope_key(scope: RequestScope) -> tuple[Optional[str], Optional[int]]:
    return (scope.window.start.isoformat() if scope.window is not None else None, scope.campaign_id)


def _checkpoint(scope: RequestScope, offset: int) -> AppleSearchAdsResumeConfig:
    window_start, campaign_id = _scope_key(scope)
    return AppleSearchAdsResumeConfig(offset=offset, window_start=window_start, campaign_id=campaign_id)


def _advance_to_resume(
    make_scopes: Callable[[], Iterator[RequestScope]],
    resume: Optional[AppleSearchAdsResumeConfig],
    request_logger: FilteringBoundLogger,
) -> tuple[Iterator[RequestScope], int]:
    """Fast-forward the lazy scope stream to a saved checkpoint, matched by value not position.

    A checkpoint from a different window range or campaign list (e.g. the start date changed,
    or a campaign was deleted) is never found, so the run restarts from the first scope with a
    fresh stream.
    """
    if resume is None:
        return make_scopes(), 0

    key = (resume.window_start, resume.campaign_id)
    scopes = make_scopes()
    for scope in scopes:
        if _scope_key(scope) == key:
            return itertools.chain([scope], scopes), resume.offset

    request_logger.debug(f"Apple Ads: saved checkpoint {key} is not in this run's scopes, starting from the beginning")
    return make_scopes(), 0


def _iter_rows(
    client: AppleSearchAdsClient,
    config: AppleSearchAdsEndpointConfig,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[AppleSearchAdsResumeConfig],
    resume: Optional[AppleSearchAdsResumeConfig],
    request_logger: FilteringBoundLogger,
    *,
    campaign_ids: list[Optional[int]],
    windows: Optional[list[ReportWindow]],
) -> Iterator[list[dict[str, Any]]]:
    scopes, resume_offset = _advance_to_resume(lambda: _scopes(campaign_ids, windows), resume, request_logger)

    current = next(scopes, None)
    while current is not None:
        # Peek at the next scope so a completed one can checkpoint where the run picks up.
        upcoming = next(scopes, None)
        offset = resume_offset
        resume_offset = 0

        while True:
            request = page_request(config, api_version, current, offset)
            payload = client.request_json(
                request.method,
                request.path,
                params=request.params,
                body=request.body,
                requires_context=config.requires_context,
            )
            page = page_rows(payload, config, api_version)
            rows = _project_rows(page, config, api_version, current.campaign_id)
            if rows:
                yield rows

            if config.kind in _UNPAGINATED_KINDS or len(page) < PAGE_SIZE:
                break

            offset += len(page)
            resumable_source_manager.save_state(_checkpoint(current, offset))

        if upcoming is not None:
            resumable_source_manager.save_state(_checkpoint(upcoming, 0))
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
    config = endpoints_for_version(api_version)[endpoint]
    client = AppleSearchAdsClient(credentials, api_version, request_logger)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    # Listed once, up front: the scope stream is lazy and rebuilt on a missed checkpoint, so
    # deriving the campaign list inside it would re-request the whole campaign list.
    campaign_ids: list[Optional[int]] = [None]
    if config.fan_out_over_campaigns:
        campaign_ids = list(_list_campaign_ids(client, api_version))

    windows: Optional[list[ReportWindow]] = None
    if config.kind == "report":
        limits = reporting_limits_for_version(api_version)
        today = _today()
        start = _report_start_date(
            should_use_incremental_field, db_incremental_field_last_value, start_date, today, limits
        )
        windows = _report_windows(start, today, limits.min_window_days)

    yield from _iter_rows(
        client,
        config,
        api_version,
        resumable_source_manager,
        resume,
        request_logger,
        campaign_ids=campaign_ids,
        windows=windows,
    )

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
    config = endpoints_for_version(api_version)[endpoint]

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
