import time
import datetime as dt
import threading
import dataclasses
import collections.abc
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.cache import cache
from django.db import OperationalError, close_old_connections

import requests
import structlog
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials as OAuthCredentials

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.common import integration_secrets
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_adapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleadsense import (
    GoogleAdSenseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense.settings import (
    ENTITY_SCHEMAS,
    HEADER_TYPE_CASTS,
    REPORTS_SCHEMAS,
)

logger = structlog.get_logger(__name__)

ADSENSE_API_BASE = "https://adsense.googleapis.com/v2"

_MAX_INTEGRATION_FETCH_ATTEMPTS = 4

FRESHNESS_LAG_DAYS = 1  # ESTIMATED_EARNINGS is final "through yesterday"; today is still an estimate

DEFAULT_HISTORY_DAYS = 730  # 2 years, per spec default
DEFAULT_LOOKBACK_DAYS = 7

DEFAULT_INCREMENTAL_LOOKBACK_SECONDS = DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60

# Google AdSense is rate-limited at 100 requests/min per user per project, 500
# requests/min per project overall, and 10,000 requests/day per project (resets
# ~midnight Pacific; shared across every connected customer on this project).
# High request volume — many customers syncing concurrently, or paginated list
# calls (accounts, ad clients, sites) — can trip these caps, which Google reports
# as an HTTP 403 with reason `RATE_LIMIT_EXCEEDED` or similar (see google.rpc.ErrorInfo,
# not the legacy errors[] shape). There's also a separate, unpublished report-row
# quota capping reporting rows per user per day, returned as HTTP 429 with
# "Report row quota exceeded". Both are transient — back off and retry rather
# than failing the whole job.
# Quotas: https://developers.google.com/adsense/management/appendix/limits

QUOTA_ERROR_REASONS = frozenset(
    {
        "quotaExceeded",
        "rateLimitExceeded",
        "userRateLimitExceeded",  # legacy errors[]
        "QUOTA_EXCEEDED",
        "RATE_LIMIT_EXCEEDED",
        "USER_RATE_LIMIT_EXCEEDED",  # ErrorInfo
    }
)
# dailyLimitExceeded resets at midnight, so let Temporal retry the activity instead of blocking inline.
DAILY_QUOTA_REASONS = frozenset({"dailyLimitExceeded", "DAILY_LIMIT_EXCEEDED"})
# Compare case-insensitively against these (see _error_reasons).
_QUOTA_ERROR_REASONS_UPPER = frozenset(r.upper() for r in QUOTA_ERROR_REASONS)
_DAILY_QUOTA_REASONS_UPPER = frozenset(r.upper() for r in DAILY_QUOTA_REASONS)

QUOTA_MAX_RETRIES = 5
QUOTA_BACKOFF_BASE_SECONDS = 2.0  # exponential: ~2, 4, 8, 16, 32s — QPS windows reset within seconds

# Proactive client-side throttle, scoped per project rather than per site: AdSense
# quota is project-owned even though each customer's OAuth token is customer-owned
# (see quota notes above), so every connected customer shares one budget and must be
# throttled together. Targets the 500 requests/min project-wide cap with headroom;
# _is_quota_error above handles the reactive 403/429 backoff for the remainder.
MAX_REQUESTS_PER_MINUTE_PER_PROJECT = 500.0
_MIN_REQUEST_INTERVAL_SECONDS = 60.0 / MAX_REQUESTS_PER_MINUTE_PER_PROJECT

_PROJECT_THROTTLE_KEY = "google_adsense:project"

# The account's reporting time zone is fixed, so cache it per connection for an hour:
# without this, every enabled stats table re-fetches `accounts.get` on each sync (8 tables
# = 8 extra reads of the shared project quota, on top of the 1 per table the budget assumes).
_ACCOUNT_TIME_ZONE_CACHE_TTL_SECONDS = 60 * 60

_throttle_lock = threading.Lock()
_next_request_at: dict[str, float] = {}


class GoogleAdSenseQuotaExceededError(Exception):
    """Raised when AdSense quota stays exhausted after in-line retries.

    Deliberately NOT matched by `get_non_retryable_errors` so Temporal retries
    the activity later (the resumable source picks up from the last saved date),
    which is the right recovery for the longer 10-minute / daily load quotas. Its
    messages carry a `(retryable)` marker that `get_retryable_errors` matches, so
    the self-recovering failure is logged as a warning instead of tracked as noise.
    """


@dataclasses.dataclass
class GoogleAdSenseResumeConfig:
    schema_name: str
    window_start: str
    window_end: str


def _account_time_zone(session: AuthorizedSession, account_name: str) -> ZoneInfo:
    """The account's reporting time zone, straight from the API. Never memoised.

    AdSense interprets report dates in this zone, so "yesterday" must be resolved in it
    too — dt.date.today() is the worker's zone (usually UTC): an account ahead of UTC can
    have end_date land on its own today (an estimate), one behind can lag a full day.

    Deliberately uncached: a memo keyed on account_name alone serves one account's value
    to another (and one test's value to the next). Use _cached_account_time_zone for the
    cached, connection-keyed path.
    """
    # {..., "timeZone": {"id": "Africa/Lagos"}} — the value is an object, not a string.
    tz_name = (get_account(session, account_name).get("timeZone") or {}).get("id") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown AdSense time zone, falling back to UTC", account_name=account_name, tz=tz_name)
        return ZoneInfo("UTC")


def _account_time_zone_cache_key(team_id: int, integration_id: int, account_name: str) -> str:
    # Keyed on the connection AND the account: two teams can connect the same AdSense
    # account, and a per-account key would leak one team's tz into the other's cache.
    return f"@dwh/google_adsense/{team_id}/{integration_id}/time_zone/{account_name}"


def _cached_account_time_zone(
    team_id: int, integration_id: int, session: AuthorizedSession, account_name: str
) -> ZoneInfo:
    """_account_time_zone, cached per (team, integration, account) for an hour."""
    key = _account_time_zone_cache_key(team_id, integration_id, account_name)
    cached = cache.get(key)
    if cached:
        try:
            return ZoneInfo(cached)
        except (ZoneInfoNotFoundError, ValueError):
            # Stale entry (e.g. written before tzdata was present) — fall through and refetch.
            pass

    zone = _account_time_zone(session, account_name)
    cache.set(key, zone.key, _ACCOUNT_TIME_ZONE_CACHE_TTL_SECONDS)
    return zone


def _today(team_id: int, integration_id: int, session: AuthorizedSession, account_name: str) -> dt.date:
    """Today's date in the account's reporting time zone."""
    return dt.datetime.now(_cached_account_time_zone(team_id, integration_id, session, account_name)).date()


def _throttle() -> None:
    """Space requests against the project-wide 500 req/min cap.

    Keyed on the project, NOT the account: a per-account key would hand each connected
    customer its own 500/min budget, so N concurrent customers burst N x 500/min and trip
    the shared cap. (Per-process only — a true project-wide limiter needs shared state.)
    """
    with _throttle_lock:
        now = time.monotonic()
        scheduled = max(now, _next_request_at.get(_PROJECT_THROTTLE_KEY, 0.0))
        _next_request_at[_PROJECT_THROTTLE_KEY] = scheduled + _MIN_REQUEST_INTERVAL_SECONDS
        wait = scheduled - now
    if wait > 0:
        time.sleep(wait)


def _backoff_sleep(attempt: int) -> None:
    """Sleep before the next retry: linear growth capped at 30s (2s, 4s, 6s, ...)."""
    time.sleep(min(2 * attempt, 30))


def _get_integration(integration_id: int, team_id: int) -> Integration:
    """Fetch the OAuth ``Integration`` row, retrying a transient DB failure with backoff.

    Temporal activities run in a long-lived worker outside Django's request cycle, and this
    read happens lazily inside `get_rows` after the connection has often sat idle for minutes.
    A pooled Postgres connection can be closed server-side while idle, or the connection pooler
    can reject the query with a wait timeout (`query_wait_timeout`) when the pool is saturated.
    Both surface as a transient ``OperationalError`` that clears once a healthy connection is
    used. ``close_old_connections()`` evicts connections already known to be stale (and, after a
    failed query marks one unusable, drops it), so each attempt runs on a fresh connection; the
    short backoff also gives a saturated pool time to drain rather than retrying straight back
    into the same wait timeout. This read is idempotent, so repeating it is safe.
    ``Integration.DoesNotExist`` is left to propagate.
    """
    attempt = 0
    while True:
        close_old_connections()
        try:
            return Integration.objects.get(id=integration_id, team_id=team_id)
        except OperationalError:
            attempt += 1
            if attempt >= _MAX_INTEGRATION_FETCH_ATTEMPTS:
                raise
            _backoff_sleep(attempt)


def _credentials(integration_id: int, team_id: int) -> OAuthCredentials:
    integration = _get_integration(integration_id, team_id)
    resolved = integration_secrets.get_secrets(["GOOGLE_ADSENSE_APP_CLIENT_ID", "GOOGLE_ADSENSE_APP_CLIENT_SECRET"])
    return OAuthCredentials(
        token=None,
        refresh_token=integration.refresh_token,
        client_id=resolved["GOOGLE_ADSENSE_APP_CLIENT_ID"],
        client_secret=resolved["GOOGLE_ADSENSE_APP_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        # No `scopes=` on purpose. With a refresh-token grant, google-auth forwards the
        # requested scopes to Google's token endpoint, which rejects anything that isn't an
        # exact subset of what the original consent granted — surfacing as
        # "invalid_scope: Bad Request" and failing every sync/validation. Omitting it
        # refreshes with the originally-granted scopes (matching the Google AdSense client). A
        # genuinely missing scope then shows up as a 403 on the accounts call, which we map to
        # an actionable "reconnect" message instead.
    )


def google_adsense_session(integration_id: int, team_id: int) -> AuthorizedSession:
    creds = _credentials(integration_id, team_id)
    session = AuthorizedSession(creds)
    adapter = make_tracked_adapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get(session: AuthorizedSession, url: str, params: dict[str, Any] | None = None) -> requests.Response:
    """GET with the shared project throttle and quota classification.

    List/get endpoints draw on the same project-wide quota as reports. Without this a
    transient rate-limit 403 bubbles up raw and get_non_retryable_errors matches
    "403 Client Error" — a throttle reported to the user as an auth failure. Raise a
    retryable quota error instead so Temporal retries the activity.
    """
    _throttle()
    response = session.get(url, params=params)
    if not response.ok and _is_quota_error(response):
        raise GoogleAdSenseQuotaExceededError(f"AdSense quota exhausted fetching {url} (retryable)")
    response.raise_for_status()
    return response


def _get_paginated(
    session: AuthorizedSession,
    url: str,
    collection_key: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Follow nextPageToken to exhaustion.

    AdSense list endpoints return one page at a time (default pageSize 50), so
    without this loop any account with more rows than a single page silently
    loses data — and every child of it under the fan-out.
    """
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        query = dict(params or {})
        if page_token:
            query["pageToken"] = page_token
        body = _get(session, url, query).json()
        items.extend(body.get(collection_key, []))
        page_token = body.get("nextPageToken")
        if not page_token:
            return items


def list_accounts(session: AuthorizedSession) -> list[dict[str, Any]]:
    return _get_paginated(session, f"{ADSENSE_API_BASE}/accounts", "accounts")


def list_ad_clients(session: AuthorizedSession, account_name: str) -> list[dict[str, Any]]:
    return _get_paginated(session, f"{ADSENSE_API_BASE}/{account_name}/adclients", "adClients")


def list_ad_units(session: AuthorizedSession, ad_client_name: str) -> list[dict[str, Any]]:
    return _get_paginated(session, f"{ADSENSE_API_BASE}/{ad_client_name}/adunits", "adUnits")


def list_custom_channels(session: AuthorizedSession, ad_client_name: str) -> list[dict[str, Any]]:
    return _get_paginated(session, f"{ADSENSE_API_BASE}/{ad_client_name}/customchannels", "customChannels")


def list_url_channels(session: AuthorizedSession, ad_client_name: str) -> list[dict[str, Any]]:
    return _get_paginated(session, f"{ADSENSE_API_BASE}/{ad_client_name}/urlchannels", "urlChannels")


def list_sites(session: AuthorizedSession, account_name: str) -> list[dict[str, Any]]:
    return _get_paginated(session, f"{ADSENSE_API_BASE}/{account_name}/sites", "sites")


def list_policy_issues(session: AuthorizedSession, account_name: str) -> list[dict[str, Any]]:
    return _get_paginated(session, f"{ADSENSE_API_BASE}/{account_name}/policyIssues", "policyIssues")


def get_account(session, account_name):
    return _get(session, f"{ADSENSE_API_BASE}/{account_name}").json()


def list_alerts(session, account_name):
    return _get(session, f"{ADSENSE_API_BASE}/{account_name}/alerts").json().get("alerts", [])


def list_payments(session, account_name):
    return _get(session, f"{ADSENSE_API_BASE}/{account_name}/payments").json().get("payments", [])


def _error_reasons(response: requests.Response) -> set[str]:
    """Every error `reason` Google reports for this response, upper-cased.

    AdSense surfaces errors in two shapes that disagree on casing:
      * gRPC-transcoded quota/rate limits use `error.details[]` with an ErrorInfo
        entry whose `reason` is UPPER_SNAKE_CASE (e.g. RATE_LIMIT_EXCEEDED).
      * the legacy `error.errors[]` shape uses lowerCamelCase (e.g. rateLimitExceeded).
    Reading both and normalizing lets a single comparison cover either.
    """
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError, TypeError):
        return set()
    if not isinstance(error, dict):
        # `{"error": null}` / any non-object error carries no reason list.
        return set()

    reasons: set[str] = set()
    for detail in error.get("details", []) or []:
        if isinstance(detail, dict) and detail.get("@type") == "type.googleapis.com/google.rpc.ErrorInfo":
            if detail.get("reason"):
                reasons.add(str(detail["reason"]).upper())
    for err in error.get("errors", []) or []:
        if isinstance(err, dict) and err.get("reason"):
            reasons.add(str(err["reason"]).upper())
    return reasons


def _is_quota_error(response: requests.Response) -> bool:
    """Whether a failed response is a transient request-rate (QPS/QPM) error worth retrying.

    Google reports AdSense request-rate exhaustion as a 403 — as `error.errors[]`
    or as a gRPC-transcoded `error.details[]` ErrorInfo entry — and the separate,
    unpublished report-row quota as a genuine 429. A permission failure uses a
    different reason/domain, and a disabled API surfaces as 403 SERVICE_DISABLED;
    neither counts as a quota error.
    """
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    return bool(_error_reasons(response) & _QUOTA_ERROR_REASONS_UPPER)


def _is_daily_quota_error(response: requests.Response) -> bool:
    if response.status_code == 429:  # row quota / daily cap — retry at activity level
        return True
    if response.status_code != 403:
        return False
    return bool(_error_reasons(response) & _DAILY_QUOTA_REASONS_UPPER)


def _is_server_error(response: requests.Response) -> bool:
    """Whether a failed response is a transient Google-side 5xx worth retrying.

    A 5xx from AdSense's reports:generate is treated as transient and clears on its
    own, so retry inline like a quota error rather than failing the sync on the first
    blip.
    """
    return response.status_code >= 500


def _is_transient_refresh_error(error: RefreshError) -> bool:
    """Whether an OAuth token-refresh failure is a transient server-side blip worth retrying.

    `AuthorizedSession` refreshes the access token before the AdSense request, so a
    failing token endpoint raises `RefreshError` from `session.post` before any response
    object exists — the 5xx handling on the response never sees it. google-auth flags
    500/503/504/408/429 (and JSON `server_error`/`temporarily_unavailable`) as retryable,
    but omits 502 from its retryable status codes, so a Bad Gateway from the token
    endpoint surfaces as a `RefreshError(retryable=False)` carrying an HTML error page.
    Treat those as transient too. Permanent failures (`invalid_grant`, `invalid_scope`)
    stay non-transient so they bubble up to `get_non_retryable_errors`.
    """
    if getattr(error, "retryable", False):
        return True
    message = str(error)
    return "502" in message and "Server Error" in message


def _quota_backoff_seconds(response: requests.Response, attempt: int) -> float:
    """Seconds to wait before retrying a quota error: honor `Retry-After`, else exponential."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return QUOTA_BACKOFF_BASE_SECONDS * (2**attempt)


def _report_row_to_dict(row, headers, account_name) -> dict[str, Any]:
    result: dict[str, Any] = {"account": account_name}
    cells = row.get("cells", [])
    currency_code: str | None = None

    for index, header in enumerate(headers):
        column = NamingConvention.normalize_identifier(header["name"])
        cell = cells[index] if index < len(cells) else None
        raw_value = cell.get("value") if isinstance(cell, dict) else None
        cast = HEADER_TYPE_CASTS.get(header.get("type"), "str")

        if raw_value is None:
            result[column] = None
        elif cast == "int":
            result[column] = int(raw_value)
        elif cast == "float":
            result[column] = float(raw_value)
        else:
            result[column] = raw_value

        if header.get("type") == "METRIC_CURRENCY":
            # One shared column: every currency metric in a row is reported in the account's
            # currency, so per-metric siblings (estimated_earnings_currency_code,
            # cost_per_click_currency_code) just duplicate the same value.
            currency_code = currency_code or header.get("currencyCode")

    if currency_code is not None:
        result["currency_code"] = currency_code

    return result


def _query_reports_params(
    start_date: dt.date,
    end_date: dt.date,
    dimensions: list[str],
    metrics: list[str],
    reporting_time_zone: str | None = None,
) -> list[tuple[str, str]]:
    # No pagination on this endpoint — the caller is responsible for splitting the date
    # range if totalMatchedRows exceeds the rows actually returned, per the
    # adaptive-window strategy. orderBy=+DATE keeps rows in ascending date order so a
    # split retry can bisect the range predictably.
    params: list[tuple[str, str]] = [
        ("startDate.year", str(start_date.year)),
        ("startDate.month", str(start_date.month)),
        ("startDate.day", str(start_date.day)),
        ("endDate.year", str(end_date.year)),
        ("endDate.month", str(end_date.month)),
        ("endDate.day", str(end_date.day)),
        *[("dimensions", d) for d in dimensions],
        *[("metrics", m) for m in metrics],
        ("orderBy", "+DATE"),
    ]

    if reporting_time_zone:
        params.append(("reportingTimeZone", reporting_time_zone))

    return params


def _fetch_reports_window(
    session: AuthorizedSession,
    account_name: str,
    start_date: dt.date,
    end_date: dt.date,
    dimensions: list[str],
    metrics: list[str],
    reporting_time_zone: str | None = None,
) -> dict[str, Any]:
    """Fetch a single window as one request, with inline retry/backoff. Does not split;
    the caller is responsible for bisecting on truncation."""
    params = _query_reports_params(
        start_date=start_date,
        end_date=end_date,
        dimensions=dimensions,
        metrics=metrics,
        reporting_time_zone=reporting_time_zone,
    )
    url = f"{ADSENSE_API_BASE}/{account_name}/reports:generate"

    for attempt in range(QUOTA_MAX_RETRIES + 1):
        _throttle()
        try:
            response = session.get(url, params=params)
        except (requests.ConnectionError, requests.Timeout):
            # A dropped connection or read timeout is raised before any response, so the
            # quota/5xx handling below never sees it. The tracked adapter may retry GET
            # transport failures depending on its urllib3 Retry config; this handler is the
            # fallback once those retries are exhausted, and it's the only path for
            # non-adapter failures. Transient, so retry inline like a 5xx; once the inline
            # budget is spent, let it bubble so Temporal retries the activity (resuming from
            # the last saved date).
            if attempt == QUOTA_MAX_RETRIES:
                raise
            wait = QUOTA_BACKOFF_BASE_SECONDS * (2**attempt)
            logger.warning(
                "Google AdSense request connection/timeout error, backing off",
                account_name=account_name,
                attempt=attempt,
                wait_seconds=wait,
            )
            time.sleep(wait)
            continue
        except RefreshError as e:
            # A transient 5xx from Google's OAuth token endpoint (notably a 502, which google-auth
            # doesn't count as retryable) is raised here while AuthorizedSession refreshes the access
            # token. It clears on its own, so retry inline like a 5xx; permanent failures
            # (invalid_grant / invalid_scope) bubble up so get_non_retryable_errors can stop the sync.
            if not _is_transient_refresh_error(e) or attempt == QUOTA_MAX_RETRIES:
                raise
            wait = QUOTA_BACKOFF_BASE_SECONDS * (2**attempt)
            logger.warning(
                "Google AdSense token refresh transient error, backing off",
                account_name=account_name,
                attempt=attempt,
                wait_seconds=wait,
            )
            time.sleep(wait)
            continue
        except TransportError:
            # Raised by AuthorizedSession's internal token-refresh request when the underlying
            # HTTP call itself fails (connection reset, proxy error, DNS failure, timeout) before
            # any response exists — google-auth wraps `requests.RequestException` in this class
            # rather than raising it directly, so it never reaches the ConnectionError/Timeout
            # handling above. Always a network-layer failure, same transient class, so retry
            # inline like a 5xx rather than crashing the activity on the first blip.
            if attempt == QUOTA_MAX_RETRIES:
                raise
            wait = QUOTA_BACKOFF_BASE_SECONDS * (2**attempt)
            logger.warning(
                "Google AdSense token refresh transport error, backing off",
                account_name=account_name,
                attempt=attempt,
                wait_seconds=wait,
            )
            time.sleep(wait)
            continue

        if response.ok:
            try:
                return response.json()
            except requests.exceptions.ChunkedEncodingError:
                # The body streams via chunked transfer-encoding and can still be cut off
                # mid-read after a 200 with a good `response` object — a dropped connection
                # after headers rather than before, so it lands here instead of the
                # ConnectionError/Timeout handling above. Same transient class; retry inline,
                # then let Temporal retry the activity once the inline budget is spent.
                if attempt == QUOTA_MAX_RETRIES:
                    raise
                wait = QUOTA_BACKOFF_BASE_SECONDS * (2**attempt)
                logger.warning(
                    "Google AdSense response body truncated, backing off",
                    account_name=account_name,
                    attempt=attempt,
                    wait_seconds=wait,
                )
                time.sleep(wait)
                continue

        # Surface Google's real reason (e.g. usageLimits/quotaExceeded vs forbidden) —
        # raise_for_status() discards the body where that distinction lives.
        logger.warning(
            "Google AdSense reports.query failed",
            account_name=account_name,
            status_code=response.status_code,
            body=response.text,
        )

        if _is_daily_quota_error(response):
            raise GoogleAdSenseQuotaExceededError(
                f"AdSense daily quota for '{account_name}' exhausted; retrying at the activity level (retryable)"
            )
            # Quota (403 usageLimits / 429) and transient Google-side 5xx both clear on their own,
            # so retry inline with backoff. Permission / other client errors are fatal — let the
            # HTTPError bubble up so `get_non_retryable_errors` can match "403 Client Error" /
            # "401 Client Error".
        if not _is_quota_error(response) and not _is_server_error(response):
            response.raise_for_status()

        if attempt == QUOTA_MAX_RETRIES:
            if _is_server_error(response):
                # Still 5xx after the inline budget — surface the real HTTPError so Temporal
                # retries the activity (resuming from the last saved date).
                response.raise_for_status()
            raise GoogleAdSenseQuotaExceededError(
                f"AdSense reports quota for '{account_name}' still exhausted after {QUOTA_MAX_RETRIES} retries (retryable)"
            )

        wait = _quota_backoff_seconds(response, attempt)
        logger.warning(
            "Google AdSense request failed, backing off",
            account_name=account_name,
            status_code=response.status_code,
            attempt=attempt,
            wait_seconds=wait,
        )
        time.sleep(wait)

    raise GoogleAdSenseQuotaExceededError(f"AdSense reports quota for '{account_name}' exhausted (retryable)")


def _query_reports(
    session: AuthorizedSession,
    account_name: str,
    start_date: dt.date,
    end_date: dt.date,
    dimensions: list[str],
    metrics: list[str],
    table_name: str,
    reporting_time_zone: str | None = None,
) -> dict[str, Any]:
    """Adaptive-window fetch: requests the whole range in one call. If totalMatchedRows
    exceeds the rows actually returned, the request was truncated at the 100K row cap —
    split the window in half and retry each half. Stop at single days; if a single day
    still exceeds the cap, log it and keep the truncated rows rather than looping
    forever. A 2-year daily_stats backfill costs 1 request, not 730, in the common case
    where nothing needs splitting.
    """
    stack: list[tuple[dt.date, dt.date]] = [(start_date, end_date)]
    all_rows: list[dict[str, Any]] = []
    headers: list[dict[str, Any]] = []

    while stack:
        window_start, window_end = stack.pop()
        data = _fetch_reports_window(
            session,
            account_name,
            window_start,
            window_end,
            dimensions,
            metrics,
            reporting_time_zone=reporting_time_zone,
        )
        rows = data.get("rows") or []
        if not headers:
            headers = data.get("headers") or []
        total_matched = int(data.get("totalMatchedRows") or 0)

        if total_matched > len(rows) and window_start != window_end:
            midpoint = window_start + (window_end - window_start) // 2
            # Push right half first so the left half (earlier dates) pops and
            # processes first, keeping accumulation roughly ascending.
            stack.append((midpoint + dt.timedelta(days=1), window_end))
            stack.append((window_start, midpoint))
            continue

        if total_matched > len(rows):
            # Single day still exceeds the cap. Can't split further — log and keep
            # what came back rather than looping on the same window forever.
            logger.warning(
                "Google AdSense reports table exceeded row cap on a single day",
                account_name=account_name,
                table_name=table_name,
                date=window_start.isoformat(),
                total_matched_rows=total_matched,
                rows_returned=len(rows),
            )

        all_rows.extend(rows)

    return {"headers": headers, "rows": all_rows}


def _coerce_date(value: Any) -> dt.date | None:
    """Normalize a config-supplied date to dt.date.

    start_date comes from a SourceFieldInputConfigType.TEXT field, so production hands us
    "2026-04-29" — not a dt.date. Every comparison, subtraction, and .isoformat() in the
    window path assumes a date, so coerce once, here, at the boundary.
    """
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value).strip())


def _initial_start_date(
    today: dt.date,
    start_date: dt.date | str | None,
    history_days: int = DEFAULT_HISTORY_DAYS,
) -> dt.date:
    # start_date is the user-configurable SourceFieldInputConfig override; falls back to
    # the 2-year default when unset.
    configured_start = _coerce_date(start_date)
    return configured_start if configured_start is not None else today - dt.timedelta(days=history_days)


def _resolve_window(
    today: dt.date,
    db_incremental_field_last_value: Any,
    start_date: dt.date | str | None = None,
    end_lag_days: int = FRESHNESS_LAG_DAYS,
) -> tuple[dt.date, dt.date]:
    # No lookback arithmetic here. The pipeline already shifted
    # db_incremental_field_last_value back by the schema's incremental lookback
    # (default_incremental_lookback_seconds, see _reports_schema), so subtracting one again
    # would double the trailing window. db_incremental_field_last_value_before_lookback is
    # the un-shifted cursor, handed to the caller when it needs to tell re-read overlap
    # from new ground.
    end_date = today - dt.timedelta(days=end_lag_days)

    cursor = _coerce_date(db_incremental_field_last_value)
    if cursor is None:
        # Full refresh, or the first incremental run: the configured start date, else the
        # 2-year history floor.
        return _initial_start_date(today, start_date), end_date

    # start_date stays a floor so an incremental sync never reaches further back than the
    # configured earliest date.
    return max(_initial_start_date(today, start_date), cursor), end_date


def _entity_rows(
    config: GoogleAdSenseSourceConfig,
    resource_name: str,
    team_id: int,
) -> collections.abc.Iterator[list[dict[str, Any]]]:
    session = google_adsense_session(config.google_adsense_integration_id, team_id)
    account_name = config.account

    if resource_name == "account":
        rows = [get_account(session, account_name)]
    elif resource_name == "ad_client":
        rows = list_ad_clients(session, account_name)
    elif resource_name in ("ad_unit", "custom_channel", "url_channel"):
        ad_clients = list_ad_clients(session, account_name)
        fan_out = {
            "ad_unit": list_ad_units,
            "custom_channel": list_custom_channels,
            "url_channel": list_url_channels,
        }[resource_name]
        rows = [row for ad_client in ad_clients for row in fan_out(session, ad_client["name"])]
    elif resource_name == "site":
        rows = list_sites(session, account_name)
    elif resource_name == "alert":
        rows = list_alerts(session, account_name)
    elif resource_name == "policy_issue":
        rows = list_policy_issues(session, account_name)
    elif resource_name == "payment":
        rows = list_payments(session, account_name)
    else:
        raise ValueError(f"Unknown entity resource: {resource_name}")

    if rows:
        yield rows


def _entity_source(
    config: GoogleAdSenseSourceConfig,
    resource_name: str,
    team_id: int,
) -> SourceResponse:
    return SourceResponse(
        name=NamingConvention.normalize_identifier(resource_name),
        items=lambda: _entity_rows(config, resource_name, team_id),
        primary_keys=list(ENTITY_SCHEMAS[resource_name]["primary_key"]),
        # A snapshot of the current state, with no timestamp to order or partition on.
        # Google documents no ordering for either list endpoint, so no sort mode is declared.
        sort_mode=None,
    )


def google_adsense_source(
    config: GoogleAdSenseSourceConfig,
    resource_name: str,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[GoogleAdSenseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    db_incremental_field_last_value_before_lookback: Any = None,
) -> SourceResponse:
    if resource_name in ENTITY_SCHEMAS:
        return _entity_source(config, resource_name, team_id)

    schema = REPORTS_SCHEMAS[resource_name]

    dimensions = schema["dimensions"]
    metrics = schema["metrics"]
    primary_keys = list(schema["primary_key"])
    end_lag_days = schema.get("end_lag_days", FRESHNESS_LAG_DAYS)

    name = NamingConvention.normalize_identifier(resource_name)

    def get_rows() -> collections.abc.Iterator[list[dict[str, Any]]]:
        session = google_adsense_session(config.google_adsense_integration_id, team_id)
        today = _today(team_id, config.google_adsense_integration_id, session, config.account)

        # db_incremental_field_last_value is already the schema's lookback-shifted cursor;
        # ..._before_lookback is the same cursor as stored, i.e. the last day the table
        # already holds. Only the days past it are new ground.
        cursor = db_incremental_field_last_value if should_use_incremental_field else None
        cursor_before_lookback = (
            _coerce_date(db_incremental_field_last_value_before_lookback) if should_use_incremental_field else None
        )

        start_date, end_date = _resolve_window(
            today,
            cursor,
            start_date=config.start_date,
            end_lag_days=end_lag_days,
        )
        if cursor_before_lookback is None:
            # Full refresh, or the first incremental run: everything in the window is new.
            cursor_before_lookback = start_date

        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if isinstance(resume, GoogleAdSenseResumeConfig):
                start_date = max(start_date, dt.date.fromisoformat(resume.window_end))

        if start_date > end_date:
            return

        response = _query_reports(
            session=session,
            account_name=config.account,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
            metrics=metrics,
            table_name=name,
        )

        headers = response.get("headers", [])
        rows = response.get("rows", [])

        if rows:
            yield [_report_row_to_dict(row, headers, account_name=config.account) for row in rows]

        # Days up to cursor_before_lookback were re-read, not new ground. Optional: this is
        # the only consumer of the before-lookback value today; it becomes load-bearing if
        # you ever add a drain budget (see §3). Drop it if you'd rather not log.
        logger.info(
            "google_adsense.reports_window",
            resource=name,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            rows=len(rows),
            landed_new_ground=start_date > cursor_before_lookback,
        )

        # Save only after the batch has been yielded. If the consumer fails mid-batch,
        # the window is safely retried rather than skipped.
        resumable_source_manager.save_state(
            GoogleAdSenseResumeConfig(
                schema_name=name,
                window_start=start_date.isoformat(),
                window_end=end_date.isoformat(),
            )
        )

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="day",
        partition_keys=["date"],
        sort_mode="asc",
    )
