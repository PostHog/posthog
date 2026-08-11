import json
import time
import typing
import datetime as dt
import collections.abc
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.db import OperationalError, close_old_connections

import structlog
from requests import Response
from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError as RequestsConnectionError,
    JSONDecodeError as RequestsJSONDecodeError,
    ReadTimeout,
)

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration, MetaAdsIntegration

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metaads import (
    MetaAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.schemas import RESOURCE_SCHEMAS
from products.warehouse_sources.backend.types import IncrementalFieldType

logger = structlog.get_logger(__name__)

# Graph API versions this source can sync against, as opaque vendor labels copied verbatim
# from Meta's changelog — never parsed or ordered. The resolved source pin is threaded into
# every request URL's `{API_VERSION}` segment by `meta_ads_source`.
# https://developers.facebook.com/docs/graph-api/changelog
META_ADS_API_VERSION_V25 = "v25.0"
META_ADS_API_VERSION_V26 = "v26.0"

# Meta Ads API only supports data from the last 3 years. Meta's insights endpoints
# reject a `time_range` whose start is beyond ~37 months from today with error code
# 3018 ("The start date of the time range cannot be beyond 37 months from the current
# date"); 3 * 365 days stays comfortably inside that window.
META_ADS_MAX_HISTORY_DAYS = 3 * 365
DEFAULT_SYNC_LOOKBACK_DAYS = 90


def _earliest_supported_since(today: dt.date) -> dt.date:
    """Earliest ``since`` date Meta will accept for an insights ``time_range``.

    Meta rejects insights queries whose start is beyond ~37 months from today with
    error code 3018. We clamp to ``META_ADS_MAX_HISTORY_DAYS`` (kept safely under that
    limit) so a `since` derived from an aged incremental cursor — or from a dormant
    account whose latest activity sits near the boundary — never trips it.
    """
    return today - dt.timedelta(days=META_ADS_MAX_HISTORY_DAYS)


@dataclass
class MetaAdsResumeConfig:
    """Resume state for a Meta Ads sync.

    Two shapes are encoded here:

    - Simple pagination (non-stats endpoints, no time range): only ``next_url``
      is set. It is a ``paging.next`` URL returned by the Graph API with its
      ``access_token`` query param stripped (see ``_strip_access_token``); the
      token is re-attached from the integration config at request time on
      resume.
    - Time-range pagination (stats endpoints): ``end_date`` acts as the
      discriminator. ``chunk_since`` and ``chunk_size_days`` describe where to
      restart the outer chunk loop. ``chunk_next_url`` is set when the crash
      happened mid-chunk — on resume we fetch that URL directly, skipping the
      initial chunk request. When the chunk was complete at save time,
      ``chunk_next_url`` is None and we issue a fresh initial request for
      ``chunk_since``. ``chunk_limit`` is set when an in-flight timeout caused
      the per-page limit to be reduced; the smaller limit then persists across
      resumes so we don't re-trip the same timeout. Saved URLs have
      ``access_token`` stripped.
    """

    next_url: str | None = None
    end_date: str | None = None
    chunk_since: str | None = None
    chunk_size_days: int | None = None
    chunk_next_url: str | None = None
    chunk_limit: int | None = None


def _strip_access_token(url: str) -> str:
    """Remove the ``access_token`` query parameter from a URL.

    Meta's ``paging.next`` URLs embed the caller's access token as a query
    param. We never want that token at rest in Redis or in logs — we re-attach
    a fresh one from the integration config at request time.
    """
    parts = urlsplit(url)
    if not parts.query:
        return url
    filtered = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "access_token"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment))


def _fetch_paging_url(url: str, access_token: str) -> Response:
    """Fetch a Meta ``paging.next``-style URL with a freshly injected access token.

    Saved URLs have ``access_token`` stripped; we pass it via ``params`` at
    request time so the token never persists in Redis or debug logs.
    """
    return _get_with_transient_retry(lambda: make_tracked_session().get(url, params={"access_token": access_token}))


def _clean_account_id(s: str | None) -> str | None:
    """Clean account IDs from Meta Ads.
    Account IDs should have 'act_' prefix for API calls.
    """
    if not s:
        return s

    s = s.strip()
    if not s.startswith("act_"):
        s = f"act_{s}"
    return s


def _backoff_sleep(attempt: int) -> None:
    """Sleep before the next retry: linear growth capped at 30s (2s, 4s, 6s, ...)."""
    time.sleep(min(2 * attempt, 30))


_MAX_INTEGRATION_FETCH_ATTEMPTS = 4


def _fetch_integration_row(integration_id: int, team_id: int) -> Integration:
    """Fetch the OAuth ``Integration`` row, retrying a transient DB failure with backoff.

    Temporal activities run in a long-lived worker outside Django's request cycle, so a pooled
    Postgres connection can be closed server-side while it sits idle, or the connection pooler can
    reject the query with a wait timeout when the pool is saturated. Both surface as a transient
    ``OperationalError`` (e.g. ``the connection is closed``, ``query_wait_timeout``) and both clear
    once a healthy connection is used. ``close_old_connections()`` evicts connections already known
    to be stale (and, after a failed query marks one unusable, drops it), so each attempt runs on a
    fresh connection; the short backoff also gives a saturated pool time to drain rather than
    retrying straight back into the same wait timeout. This read is idempotent, so it is safe to
    repeat. ``Integration.DoesNotExist`` is left to propagate.
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


class MetaAdsTokenRefreshError(Exception):
    """Meta refused to refresh the integration's access token — only re-authorization fixes it."""


def get_integration_by_id(integration_id: int, team_id: int) -> Integration:
    """Get a Meta Ads integration by row id, with a freshly refreshed access token."""
    integration = _fetch_integration_row(integration_id, team_id)
    meta_ads_integration = MetaAdsIntegration(integration)
    meta_ads_integration.refresh_access_token()

    if meta_ads_integration.integration.errors == ERROR_TOKEN_REFRESH_FAILED:
        raise MetaAdsTokenRefreshError(
            "Failed to refresh token for Meta Ads integration. Please re-authorize the integration."
        )

    return meta_ads_integration.integration


def get_integration(config: MetaAdsSourceConfig, team_id: int) -> Integration:
    return get_integration_by_id(config.meta_ads_integration_id, team_id)


@dataclass
class MetaAdsSchema:
    name: str
    primary_keys: list[str]
    field_names: list[str]
    url: str
    extra_params: dict
    # Endpoints with no stable datetime column (e.g. AdCreative) leave these unset and sync
    # unpartitioned, as do the one-row and lookup tables where partitioning buys nothing.
    partition_keys: list[str] | None = None
    partition_mode: PartitionMode | None = None
    partition_format: PartitionFormat | None = None
    is_stats: bool = False
    # The Graph API returns the node itself rather than a paged `data` list (`GET /act_<id>`).
    single_object: bool = False


# Note: can make this static but keeping schemas.py to match other schema files for now
def get_schemas() -> dict[str, MetaAdsSchema]:
    """Obtain Meta Ads schemas using predefined field definitions."""
    schemas: dict[str, MetaAdsSchema] = {}

    for resource_name, schema_def in RESOURCE_SCHEMAS.items():
        schema = MetaAdsSchema(
            name=resource_name,
            primary_keys=schema_def["primary_keys"],
            field_names=schema_def["field_names"].copy(),
            url=schema_def["url"],
            extra_params=schema_def["extra_params"],
            partition_keys=schema_def.get("partition_keys"),
            partition_mode=schema_def.get("partition_mode"),
            partition_format=schema_def.get("partition_format"),
            is_stats=schema_def.get("is_stats", False),
            single_object=schema_def.get("single_object", False),
        )

        schemas[resource_name] = schema

    return schemas


# Error subcodes indicating the request timed out due to too much data
# https://developers.facebook.com/docs/marketing-api/insights/error-codes
META_TIMEOUT_ERROR_SUBCODES = {1504018, 1504038}

# Subcode 1504044 ("Unknown Error Occurred") is documented alongside the timeouts
# above, with the same remedy: ask for less data. It arrives as `code: 2` with
# `message: "Service temporarily unavailable"`, so without this set it reads as a
# momentary blip and only ever gets retried unchanged. Kept separate from the
# timeouts because it really can be one, and is worth a few unchanged retries
# before we start shrinking.
# https://developers.facebook.com/docs/marketing-api/insights/error-codes
META_HEAVY_QUERY_ERROR_SUBCODES = {1504044}

# Chunk sizes for adaptive time-range pagination (in days)
# Start with 30-day chunks, fall back to smaller chunks on timeout
TIME_RANGE_CHUNK_SIZES = [30, 7, 1]

# Per-page row limits for adaptive pagination. When the Graph API times out
# mid-chunk (i.e. on a paging.next cursor request, after we've already yielded
# rows from the chunk), shrinking the chunk's date range would force us to
# re-issue earlier pages and re-emit rows we've already produced. So we prefer
# to shrink the per-page ``limit`` and retry the same cursor URL, which Meta
# accepts as a query param on cursor URLs. Only once this ladder bottoms out
# does the chunk ladder take over, because a re-emit costs less than a dead sync
# and every stats table keys on its breakdown columns, so the rows upsert.
PAGE_LIMIT_FALLBACK_SIZES = [500, 100, 50]

# Meta's Graph API intermittently returns HTTP 200 with a truncated/partial JSON
# body — a server-side serialization hiccup under load — so ``response.json()``
# raises ``requests.exceptions.JSONDecodeError``. The body is fully received but
# unparseable, so the only recovery is to re-issue the same request; a couple of
# immediate retries almost always returns a complete body. If it stays malformed
# we let the error propagate (it remains retryable, so Temporal re-runs the
# activity from saved resume state) rather than silently dropping the page.
MALFORMED_JSON_MAX_ATTEMPTS = 3


def _override_limit(url: str, limit: int) -> str:
    """Return ``url`` with its ``limit`` query parameter overridden.

    Meta's ``paging.next`` URLs encode the limit that produced the cursor; if
    we want a smaller batch on the retry, we have to rewrite the URL.
    """
    parts = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "limit"]
    pairs.append(("limit", str(limit)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def _next_smaller_limit(current: int) -> int | None:
    """Return the next smaller value in ``PAGE_LIMIT_FALLBACK_SIZES``.

    Returns ``None`` if ``current`` is already at or below the smallest rung —
    in that case the caller should treat the timeout as terminal.
    """
    if current in PAGE_LIMIT_FALLBACK_SIZES:
        idx = PAGE_LIMIT_FALLBACK_SIZES.index(current)
        if idx >= len(PAGE_LIMIT_FALLBACK_SIZES) - 1:
            return None
        return PAGE_LIMIT_FALLBACK_SIZES[idx + 1]
    smaller = [s for s in PAGE_LIMIT_FALLBACK_SIZES if s < current]
    return max(smaller) if smaller else None


def _next_smaller_chunk_size(current: int) -> int | None:
    """Return the next smaller value in ``TIME_RANGE_CHUNK_SIZES``.

    Returns ``None`` if ``current`` is already at or below the smallest rung. A
    resumed sync can carry a chunk size that predates the current ladder, so an
    off-ladder value steps to the largest rung below it rather than giving up.
    """
    if current in TIME_RANGE_CHUNK_SIZES:
        idx = TIME_RANGE_CHUNK_SIZES.index(current)
        if idx >= len(TIME_RANGE_CHUNK_SIZES) - 1:
            return None
        return TIME_RANGE_CHUNK_SIZES[idx + 1]
    smaller = [s for s in TIME_RANGE_CHUNK_SIZES if s < current]
    return max(smaller) if smaller else None


def _is_timeout_error(response: Response) -> bool:
    """Check if the response is a Meta API timeout error that can be resolved with smaller date ranges.

    Deliberately narrower than ``_should_shrink_request``: these subcodes are
    unambiguous, so ``_get_with_transient_retry`` hands them straight to the
    shrink ladders instead of spending retries on a request Meta has already
    told us is too big.
    """
    try:
        error = response.json().get("error", {})

        if error.get("error_subcode") in META_TIMEOUT_ERROR_SUBCODES:
            return True

        # This check is a bit fragile, but the Meta API has been observed to return a 500 response like this:
        # {"error":{"code":1,"message":"Please reduce the amount of data you're asking for, then retry your request"}}
        message = str(error.get("message") or "").lower()
        return error.get("code") == 1 and "reduce the amount of data" in message
    except (ValueError, KeyError, AttributeError):
        return False


def _should_shrink_request(response: Response) -> bool:
    """Return True for failures a smaller date range or page size can resolve.

    Covers the unambiguous timeouts plus the heavy-query subcodes, which reach
    here only after ``_get_with_transient_retry`` has spent its unchanged
    retries on them without the error clearing. A failure that survives those is
    not the momentary blip Meta's error body claims.
    """
    if _is_timeout_error(response):
        return True
    return _meta_error_body(response).get("error_subcode") in META_HEAVY_QUERY_ERROR_SUBCODES


# Meta's error-code reference documents code 1 ("API Unknown" — an unexplained backend hiccup
# that usually clears in 1-2 retries) and code 2 ("API Service" — temporary downtime/overload) as
# retry-recommended: https://developers.facebook.com/docs/graph-api/guides/error-handling. Meta
# also flags some of these transient via ``error.is_transient``, but that flag isn't set
# consistently — code 2 "Service temporarily unavailable" has been observed with
# ``is_transient: false`` — so the documented codes are trusted over the flag. The request itself
# is fine, so a couple of immediate retries with a short backoff usually clears it — keeping a
# self-recovering blip from failing the whole activity (and surfacing as error-tracking noise)
# while still letting it propagate, and Temporal retry from saved resume state, if it persists.
META_TRANSIENT_ERROR_MAX_ATTEMPTS = 4
META_TRANSIENT_ERROR_CODES = {1, 2}


def _is_transient_error(response: Response) -> bool:
    """Return True for Meta errors that are momentary backend blips worth retrying immediately.

    Distinct from the too-much-data timeout (``_is_timeout_error``), which has its own
    limit-shrinking recovery; a transient error is retried with the request unchanged.
    """
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        # A 5xx with no parseable body (occasionally a completely empty response) carries no
        # error code to classify by, but a bare server-side failure is itself the signature of
        # a momentary blip — unlike a 4xx, which more likely reflects a bad request of ours.
        return response.status_code >= 500
    return error.get("is_transient") is True or error.get("code") in META_TRANSIENT_ERROR_CODES


# Meta's connection occasionally resets mid-response — `requests` raises these while decoding the
# body, after urllib3's own connection-level retries have already returned headers, so there's no
# `Response` object yet to inspect for `_is_transient_error`. Re-issuing the same request is safe:
# nothing was yielded from the failed one yet.
NETWORK_TRANSIENT_ERRORS = (ChunkedEncodingError, RequestsConnectionError, ReadTimeout)


def _get_with_transient_retry(issue: collections.abc.Callable[[], Response]) -> Response:
    """Issue a request, absorbing transient network failures and Meta's transient server errors.

    Re-issuing the same request is safe: a transiently-failed request yielded no rows. Too-much-data
    timeouts are left for the caller's limit-shrinking path. If a failure persists past the bound, the
    last response (or exception) propagates as usual, so the caller raises it, staying retryable upstream.
    """
    attempt = 1
    while True:
        try:
            response = issue()
        except NETWORK_TRANSIENT_ERRORS:
            if attempt >= META_TRANSIENT_ERROR_MAX_ATTEMPTS:
                raise
            _backoff_sleep(attempt)
            attempt += 1
            continue

        if (
            attempt >= META_TRANSIENT_ERROR_MAX_ATTEMPTS
            or response.status_code == 200
            or not _is_transient_error(response)
            or _is_timeout_error(response)
        ):
            return response

        _backoff_sleep(attempt)
        attempt += 1


def _get_initial_request(url: str, params: dict) -> Response:
    """Issue a first (non-cursor) Graph API request, absorbing Meta's transient server errors."""
    return _get_with_transient_retry(lambda: make_tracked_session().get(url, params=params))


# Meta error codes that indicate a permanent auth or permission problem — the
# only fix is for the user to re-authorize the integration, so retrying the job
# is pointless. We key off the numeric ``code`` rather than the error ``type``:
# Meta returns ``type: "OAuthException"`` for transient service errors too (e.g.
# code 2, "Service temporarily unavailable"), so the type alone is not reliable.
#   190 — access token expired/invalid/revoked, checkpoint required, password
#         changed, etc. (the dominant variant for this source).
#   102 — invalid or expired session.
#   10 and 200-299 — permission denied.
# https://developers.facebook.com/docs/graph-api/guides/error-handling
META_AUTH_ERROR_CODES = {102, 190}
META_PERMISSION_ERROR_CODES = {10, *range(200, 300)}

# Meta also raises generic code 100 ("Invalid parameter") with this exact message when the
# token's own account can no longer be resolved, e.g. the connected Facebook account was
# deactivated or lost the app's granted access. Matched on message text rather than on code
# 100 alone, since that code also covers genuine malformed-request bugs on our side, which
# must keep surfacing as real errors rather than being reclassified as auth failures.
META_UNSUPPORTED_GET_REQUEST_MESSAGE = "unsupported get request"

# Meta throttling codes. The request was rejected for its volume, not for being malformed, so the
# call is fine and the only fix is waiting — never a bug on our side.
#   4 — application request limit reached (our app, across all users).
#   17 — user request limit reached.
#   32 — page request limit reached.
#   613 — custom-level rate limit reached.
# https://developers.facebook.com/docs/graph-api/overview/rate-limiting
META_RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613}

META_AUTH_ERROR_MESSAGE = (
    "Meta Ads access token is invalid, expired, or lacks the required permissions. Please re-authorize the integration."
)

META_RATE_LIMIT_ERROR_MESSAGE = (
    "Meta is rate limiting requests for this connection. Please wait a few minutes and try again."
)

# Matched by `MetaAdsSource.get_non_retryable_errors`, so it has to stay in sync
# with the key there.
SHRINK_EXHAUSTED_ERROR_MESSAGE = "Meta could not return this data even at the smallest request size"


def _meta_error_body(response: Response) -> dict:
    """The ``error`` object of a Meta error response, or an empty dict if it carries none."""
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        return {}
    return error if isinstance(error, dict) else {}


def _meta_error_code(response: Response) -> int | None:
    """The numeric ``error.code`` of a Meta error body, or None if it carries no parseable one."""
    code = _meta_error_body(response).get("code")
    return code if isinstance(code, int) else None


def _is_permanent_auth_error(response: Response) -> bool:
    """Return True for Meta errors that only re-authorization can fix.

    Covers expired/invalid/revoked access tokens, invalidated sessions, and
    permission denials. These are terminal: retrying the sync keeps failing
    until the user reconnects the integration.
    """
    code = _meta_error_code(response)
    if code in META_AUTH_ERROR_CODES or code in META_PERMISSION_ERROR_CODES:
        return True
    message = str(_meta_error_body(response).get("message") or "").lower()
    return code == 100 and META_UNSUPPORTED_GET_REQUEST_MESSAGE in message


def _is_rate_limit_error(response: Response) -> bool:
    """Return True for Meta errors that mean "too many requests", which only waiting fixes."""
    return _meta_error_code(response) in META_RATE_LIMIT_ERROR_CODES


def _raise_meta_api_error(response: Response) -> typing.NoReturn:
    """Raise a descriptive exception for a non-200 Meta API response.

    Permanent auth/permission failures raise a clean, user-actionable message
    that ``MetaAdsSource.get_non_retryable_errors`` matches on, so the job fails
    fast instead of burning retries. Throttling (see ``_is_rate_limit_error``) and
    a momentary backend blip (see ``_is_transient_error``) that has already
    exhausted its in-process retries are both tagged so
    ``MetaAdsSource.get_retryable_errors`` can keep the self-recovering failure out
    of error tracking once Temporal retries the activity, excluding anything the
    shrink ladders can still act on, which ends at ``_raise_shrink_exhausted_error``
    instead. The raw response is appended for debugging.
    Everything else raises the raw response and stays retryable.
    """
    if _is_permanent_auth_error(response):
        raise Exception(f"{META_AUTH_ERROR_MESSAGE} (Meta API response: {response.status_code} - {response.text})")
    if _is_rate_limit_error(response):
        raise Exception(
            f"{META_RATE_LIMIT_ERROR_MESSAGE} (Meta API response: {response.status_code} - {response.text})"
        )
    if _is_transient_error(response) and not _should_shrink_request(response):
        raise Exception(f"Meta API request failed (retryable): {response.status_code} - {response.text}")
    raise Exception(f"Meta API request failed: {response.status_code} - {response.text}")


def _raise_shrink_exhausted_error(response: Response) -> typing.NoReturn:
    """Raise once both shrink ladders have bottomed out and Meta still refuses.

    Terminal on purpose: the date range is down to a single day and the page
    size to its smallest rung, so the next Temporal retry would re-issue exactly
    the request that just failed. ``MetaAdsSource.get_non_retryable_errors``
    matches on the message, so the job stops and tells the user what to change
    rather than retrying against the schedule forever.
    """
    raise Exception(f"{SHRINK_EXHAUSTED_ERROR_MESSAGE} (Meta API response: {response.status_code} - {response.text})")


class MetaAdsAuthError(Exception):
    """Meta rejected the credentials or the permissions they carry (see `_is_permanent_auth_error`)."""


class MetaAdsRateLimitError(Exception):
    """Meta throttled the request (see `_is_rate_limit_error`) — retrying later is the only fix."""


# No `business{name}`: reading it needs the `business_management` scope, which the Meta OAuth
# consent doesn't request (`ads_read` only), and Meta 400s the whole request when it's asked for.
AD_ACCOUNT_FIELDS = "account_id,name,account_status"
AD_ACCOUNT_PAGE_LIMIT = 100
# This listing runs in the web request path, not a Temporal worker, so a cursor that never resolves
# would pin a worker. Bound it rather than trusting Meta to end the chain.
MAX_AD_ACCOUNT_PAGES = 100
# Per-request timeout for the listing path. Without it a hung Meta connection pins the web worker
# for the life of the request, since these calls run inline in `oauth_accounts`, not in a worker.
AD_ACCOUNT_LISTING_TIMEOUT_SECONDS = 10


def _raise_for_meta_error(response: Response) -> None:
    """Map a non-200 Meta listing response to the actionable error the picker surfaces. Called for every
    page, including the one fetched just before the page cap, so an auth or rate-limit failure on the
    final fetch isn't swallowed and mislabeled as "too many pages"."""
    if response.status_code != 200:
        if _is_permanent_auth_error(response):
            raise MetaAdsAuthError(META_AUTH_ERROR_MESSAGE)
        if _is_rate_limit_error(response):
            raise MetaAdsRateLimitError(META_RATE_LIMIT_ERROR_MESSAGE)
        _raise_meta_api_error(response)


def list_ad_accounts(integration: Integration) -> list[dict]:
    """Every ad account the connected Meta user can access."""
    access_token = integration.sensitive_config["access_token"]
    # `redact_values` masks the access token wherever it lands in telemetry — Meta takes it as a query
    # param here and echoes it back inside each `paging.next` URL, so without this the credential would
    # be recorded in the logged/sampled request URLs.
    session = make_tracked_session(redact_values=(access_token,))
    accounts: list[dict] = []
    response = session.get(
        f"https://graph.facebook.com/{MetaAdsIntegration.api_version}/me/adaccounts",
        params={"fields": AD_ACCOUNT_FIELDS, "limit": AD_ACCOUNT_PAGE_LIMIT, "access_token": access_token},
        timeout=AD_ACCOUNT_LISTING_TIMEOUT_SECONDS,
    )

    for _ in range(MAX_AD_ACCOUNT_PAGES):
        _raise_for_meta_error(response)

        body = response.json()
        page = body.get("data") or []
        accounts.extend(page)

        next_url = (body.get("paging") or {}).get("next")
        # Meta keeps handing out a `next` cursor past the final page, which then returns no data.
        if not next_url or not page:
            return accounts

        response = session.get(
            _strip_access_token(next_url),
            params={"access_token": access_token},
            timeout=AD_ACCOUNT_LISTING_TIMEOUT_SECONDS,
        )

    # The response fetched on the final loop iteration is never re-checked by the loop, so surface a real
    # auth/rate-limit failure there rather than masking it with the "too many pages" error below.
    _raise_for_meta_error(response)
    # Hitting the cap means Meta kept returning a fresh, non-empty `next` cursor past the bound. Returning
    # `accounts` here would present a truncated (and possibly duplicated) list as the complete set, so the
    # picker would silently hide accounts. Fail closed with an actionable message instead.
    raise IntegrationAccountListingError("Meta returned too many pages while listing ad accounts. Please try again.")


def _iter_simple_pagination(
    initial_url: str,
    params: dict,
    resume_config: MetaAdsResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[MetaAdsResumeConfig],
) -> collections.abc.Generator[list[dict]]:
    """Iterate a non-time-range Graph API request via ``paging.next`` URLs.

    On resume, the saved ``next_url`` is re-issued with a fresh ``access_token``
    injected at request time, so the initial request is skipped.

    Like the stats path, this adapts to Meta's "reduce the amount of data" 500s
    by shrinking the per-page ``limit`` (``PAGE_LIMIT_FALLBACK_SIZES``) and
    retrying the same request. Entity endpoints (campaigns/adsets/ads) carry
    heavy fields like ``targeting`` and ``creative``, so a default-sized page
    can be too large for Meta to serve; without this fallback the whole sync
    fails on those accounts. Retrying the same URL at a smaller limit never
    re-emits already-yielded rows — the initial request has yielded nothing
    yet, and a cursor points at the start of the next (not-yet-yielded) page.
    """
    access_token = params["access_token"]
    current_limit = PAGE_LIMIT_FALLBACK_SIZES[0]

    # None while on the initial request; set to the active ``paging.next``
    # cursor once we start following pages. Used to retry-at-smaller-limit.
    cursor_url: str | None = None
    if resume_config is not None and resume_config.next_url and resume_config.end_date is None:
        cursor_url = resume_config.next_url

    def _issue() -> Response:
        # Only rewrite the request once the limit has actually been shrunk, so
        # healthy syncs keep their original request shape (saved cursor URLs and
        # the caller's params already encode the default limit).
        if cursor_url is not None:
            url = (
                _override_limit(cursor_url, current_limit)
                if current_limit != PAGE_LIMIT_FALLBACK_SIZES[0]
                else cursor_url
            )
            return _fetch_paging_url(url, access_token)
        if current_limit != PAGE_LIMIT_FALLBACK_SIZES[0]:
            return _get_initial_request(initial_url, {**params, "limit": current_limit})
        return _get_initial_request(initial_url, params)

    response = _issue()
    malformed_json_attempts = 0

    while True:
        if response.status_code != 200:
            # Too-much-data: shrink the page limit and retry the same request.
            # Re-issuing the same URL/cursor at a smaller limit is safe — no
            # already-yielded rows are re-emitted.
            if _should_shrink_request(response):
                smaller = _next_smaller_limit(current_limit)
                if smaller is not None:
                    current_limit = smaller
                    response = _issue()
                    continue
                _raise_shrink_exhausted_error(response)
            _raise_meta_api_error(response)

        try:
            response_payload = response.json()
        except RequestsJSONDecodeError:
            # Truncated 200 body — re-issue the same request. Re-fetching is safe
            # (the initial request has yielded nothing yet, and a cursor points at
            # the start of the next not-yet-yielded page). ``response.json()`` raises
            # requests' own JSONDecodeError, which subclasses simplejson's (not the
            # stdlib json's) when simplejson is installed — catching the stdlib type
            # would miss it entirely.
            malformed_json_attempts += 1
            if malformed_json_attempts >= MALFORMED_JSON_MAX_ATTEMPTS:
                raise
            response = _issue()
            continue
        malformed_json_attempts = 0

        yield response_payload.get("data", [])

        next_url = response_payload.get("paging", {}).get("next")
        if not next_url:
            return

        # Saved state points at the NEXT page. On resume we re-fetch from there;
        # the already-yielded page is not re-emitted (primary keys would dedupe it anyway).
        # Strip access_token from the URL before using it so we don't end up with a
        # duplicated `access_token` query param (requests merges `params=...` into the URL).
        cursor_url = _strip_access_token(next_url)
        resumable_source_manager.save_state(MetaAdsResumeConfig(next_url=cursor_url))
        response = _issue()


def _iter_time_range_pagination(
    url: str,
    params: dict,
    time_range: dict,
    resume_config: MetaAdsResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[MetaAdsResumeConfig],
) -> collections.abc.Generator[list[dict]]:
    """Iterate an insights-style request by chunked date ranges.

    The outer loop walks adaptive date chunks (30/7/1 days). The inner loop
    follows ``paging.next`` within each chunk. There are two adaptive-fallback
    dimensions:

    - **Chunk size** (``TIME_RANGE_CHUNK_SIZES``): shrunk when the *initial*
      chunk request times out, before any rows are yielded, and as the last
      resort for a *cursor* timeout once the page limit bottoms out.
    - **Page limit** (``PAGE_LIMIT_FALLBACK_SIZES``): the first lever for a
      *cursor* request that times out after we already yielded earlier pages
      from this chunk. Overriding the ``limit`` on the same cursor URL leaves
      those pages alone, so we exhaust this ladder before restarting the chunk
      at a smaller size and re-yielding them.

    Resume state captures both levels: ``chunk_since`` + ``chunk_size_days``
    for the outer loop, ``chunk_next_url`` when the crash happened mid-chunk,
    and ``chunk_limit`` so a reduced limit persists across resumes.
    """
    access_token = params["access_token"]
    start_date = dt.datetime.strptime(time_range["since"], "%Y-%m-%d")
    end_date = dt.datetime.strptime(time_range["until"], "%Y-%m-%d")

    chunk_size_days = TIME_RANGE_CHUNK_SIZES[0]
    current_limit = PAGE_LIMIT_FALLBACK_SIZES[0]
    current_start = start_date
    pending_next_url: str | None = None

    if resume_config is not None and resume_config.end_date is not None and resume_config.chunk_since is not None:
        current_start = dt.datetime.strptime(resume_config.chunk_since, "%Y-%m-%d")
        chunk_size_days = resume_config.chunk_size_days or TIME_RANGE_CHUNK_SIZES[0]
        pending_next_url = resume_config.chunk_next_url
        if resume_config.chunk_limit:
            current_limit = resume_config.chunk_limit

    end_date_iso = end_date.strftime("%Y-%m-%d")

    def _save(since: dt.datetime, size_days: int, next_url_in_chunk: str | None) -> None:
        # Saved URLs have the access_token stripped so the token never sits
        # at rest in Redis or appears in debug logs.
        sanitised = _strip_access_token(next_url_in_chunk) if next_url_in_chunk else None
        resumable_source_manager.save_state(
            MetaAdsResumeConfig(
                end_date=end_date_iso,
                chunk_since=since.strftime("%Y-%m-%d"),
                chunk_size_days=size_days,
                chunk_next_url=sanitised,
                # Persist only when we've shrunk below the default — keeps
                # the saved state minimal for healthy syncs.
                chunk_limit=current_limit if current_limit != PAGE_LIMIT_FALLBACK_SIZES[0] else None,
            )
        )

    while current_start <= end_date:
        current_end = min(current_start + dt.timedelta(days=chunk_size_days - 1), end_date)
        # The most recent cursor URL we tried (without a limit override applied),
        # used to retry-with-smaller-limit if a mid-chunk request times out.
        last_paging_url: str | None = None
        # Params of the initial chunk request, kept so a truncated 200 body can be
        # re-fetched. Only set on the non-resume path; unused once we're on a cursor.
        chunk_params: dict | None = None
        # Set when the page-limit ladder bottoms out mid-chunk and a smaller chunk
        # takes over, so the outer loop restarts this chunk instead of advancing.
        restart_chunk = False

        if pending_next_url:
            # Mid-chunk resume: re-attach a fresh access_token at request time
            # and apply the (possibly previously-shrunk) limit.
            last_paging_url = pending_next_url
            response = _fetch_paging_url(_override_limit(pending_next_url, current_limit), access_token)
            pending_next_url = None
        else:
            chunk_time_range = {
                "since": current_start.strftime("%Y-%m-%d"),
                "until": current_end.strftime("%Y-%m-%d"),
            }

            chunk_params = {**params, "limit": current_limit, "time_range": json.dumps(chunk_time_range)}
            response = _get_initial_request(url, chunk_params)

            if response.status_code != 200:
                # Fallback only happens on the initial chunk request (before any data is yielded).
                if _should_shrink_request(response):
                    smaller_chunk = _next_smaller_chunk_size(chunk_size_days)
                    if smaller_chunk is not None:
                        chunk_size_days = smaller_chunk
                        continue
                    # The date range is already a single day, so the page size
                    # is the only dimension left. Re-issuing the same chunk at a
                    # smaller limit is safe: nothing has been yielded yet.
                    smaller_limit = _next_smaller_limit(current_limit)
                    if smaller_limit is not None:
                        current_limit = smaller_limit
                        continue
                    _raise_shrink_exhausted_error(response)
                _raise_meta_api_error(response)

        malformed_json_attempts = 0
        while True:
            if response.status_code != 200:
                # Mid-chunk timeout: retry the same cursor URL with a smaller
                # ``limit``. Re-issuing earlier pages (i.e. shrinking the
                # chunk) is not safe here — we've already yielded them.
                if _should_shrink_request(response) and last_paging_url is not None:
                    smaller = _next_smaller_limit(current_limit)
                    if smaller is not None:
                        current_limit = smaller
                        retry_url = _override_limit(last_paging_url, current_limit)
                        response = _fetch_paging_url(retry_url, access_token)
                        continue
                    # The page limit cannot go lower, so narrow the window instead and
                    # restart this chunk from its first day. Meta prices an insights
                    # request on the window and the breakdown, not on the page size, so
                    # a chunk this heavy keeps timing out at every limit. Re-yielding
                    # the chunk's earlier pages costs a merge that the primary key
                    # already dedupes, which beats failing the whole sync.
                    smaller_chunk = _next_smaller_chunk_size(chunk_size_days)
                    if smaller_chunk is not None:
                        chunk_size_days = smaller_chunk
                        # Drop the saved cursor. It encodes the wider window, so a
                        # resume has to re-enter this chunk at the new size.
                        _save(current_start, chunk_size_days, None)
                        restart_chunk = True
                        break
                    _raise_shrink_exhausted_error(response)
                _raise_meta_api_error(response)

            try:
                response_payload = response.json()
            except RequestsJSONDecodeError:
                # Truncated 200 body — re-issue whichever request produced it. A
                # cursor points at the start of the not-yet-yielded page and the
                # initial chunk request has yielded nothing, so no rows are re-emitted.
                malformed_json_attempts += 1
                if malformed_json_attempts >= MALFORMED_JSON_MAX_ATTEMPTS:
                    raise
                if last_paging_url is not None:
                    response = _fetch_paging_url(_override_limit(last_paging_url, current_limit), access_token)
                elif chunk_params is not None:
                    response = _get_initial_request(url, chunk_params)
                else:
                    # Unreachable: on the non-resume path chunk_params is always
                    # set, and on the resume path last_paging_url is always set.
                    raise RuntimeError("Cannot retry truncated JSON: no cursor and no initial chunk params")
                continue
            malformed_json_attempts = 0

            yield response_payload.get("data", [])

            next_url = response_payload.get("paging", {}).get("next")
            if not next_url:
                break

            # Strip the token once and use the same URL for both save and fetch,
            # otherwise `requests.get(url_with_token, params={access_token: ...})`
            # would send two `access_token` query params.
            stripped_next_url = _strip_access_token(next_url)
            _save(current_start, chunk_size_days, stripped_next_url)
            last_paging_url = stripped_next_url
            response = _fetch_paging_url(_override_limit(stripped_next_url, current_limit), access_token)

        if restart_chunk:
            continue

        current_start = current_end + dt.timedelta(days=1)
        # Always save the chunk-boundary state, even when we've advanced past
        # end_date. This clears any stale mid-chunk next_url from the previous
        # iteration (so a resume doesn't redo already-completed pagination)
        # and guarantees a crash right after the final chunk finds the loop
        # already satisfied on restart.
        _save(current_start, chunk_size_days, None)


def _fetch_single_object(url: str, params: dict, access_token: str) -> collections.abc.Generator[list[dict]]:
    """Read a Graph API node that returns the object itself instead of a paged ``data`` list.

    No pagination, no resume state and no shrink ladder: the response is a single row, so
    there is nothing to page through and nothing a smaller request could fix.
    """
    response = _get_initial_request(url, {**params, "access_token": access_token})
    if response.status_code != 200:
        _raise_meta_api_error(response)
    yield [response.json()]


def _make_paginated_api_request(
    url: str,
    params: dict,
    access_token: str,
    time_range: dict | None,
    resumable_source_manager: ResumableSourceManager[MetaAdsResumeConfig],
) -> collections.abc.Generator[list[dict]]:
    """Make paginated requests to the Meta Graph API.
    This function handles two types of pagination:
    1. Standard pagination: Uses Meta's paging.next URLs to fetch all pages of results
    2. Time-range pagination: Breaks large date ranges into chunks, with adaptive fallback
       to smaller chunks (30-day -> 7-day -> 1-day) if the API times out
    """
    params = {**params, "access_token": access_token}
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if time_range is None:
        yield from _iter_simple_pagination(url, params, resume_config, resumable_source_manager)
    else:
        yield from _iter_time_range_pagination(url, params, time_range, resume_config, resumable_source_manager)


def _attribution_params(config: MetaAdsSourceConfig) -> dict[str, str]:
    """Attribution settings to add to an Insights request, only when the source configures them.

    Omitted entirely when unset, so existing connections keep Meta's default attribution and
    produce byte-for-byte the same request as before. When set, they let a user reconcile
    PostHog's spend and conversion numbers with what Ads Manager shows.

    - ``action_attribution_windows``: a comma-separated list in config (e.g. ``7d_click,1d_view``),
      sent JSON-encoded the way Meta's Graph API accepts a list parameter.
    - ``use_unified_attribution_setting``: a string flag (``"true"``/``"false"``) sent verbatim;
      any other value (including the "use Meta's default" empty option) leaves it unset.
    """
    params: dict[str, str] = {}

    windows_raw = getattr(config, "action_attribution_windows", None)
    if windows_raw:
        windows = [window.strip() for window in windows_raw.split(",") if window.strip()]
        if windows:
            params["action_attribution_windows"] = json.dumps(windows)

    use_unified = getattr(config, "use_unified_attribution_setting", None)
    if use_unified in ("true", "false"):
        params["use_unified_attribution_setting"] = use_unified

    return params


def meta_ads_source(
    resource_name: str,
    config: MetaAdsSourceConfig,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[MetaAdsResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """A data warehouse Meta Ads source. ``api_version`` is the source instance's resolved pin."""
    name = NamingConvention.normalize_identifier(resource_name)
    schema = get_schemas()[resource_name]

    sync_lookback_days = getattr(config, "sync_lookback_days", None)
    if sync_lookback_days is None or sync_lookback_days < 1:
        sync_lookback_days = DEFAULT_SYNC_LOOKBACK_DAYS
    sync_lookback_days = min(sync_lookback_days, META_ADS_MAX_HISTORY_DAYS)

    def get_rows():
        integration = get_integration(config, team_id)
        access_token = integration.access_token

        if access_token is None:
            raise ValueError("Access token is required for Meta Ads integration")

        # Determine date range for incremental sync
        today = dt.date.today()
        # Never request data older than Meta will serve, otherwise it returns a hard
        # 400 (code 3018) and the whole sync fails instead of importing the supported
        # window. Data beyond this point is unavailable from Meta regardless.
        earliest_since = _earliest_supported_since(today)
        time_range = None

        if should_use_incremental_field:
            if incremental_field is None or incremental_field_type is None:
                raise ValueError("incremental_field and incremental_field_type can't be None")

            if db_incremental_field_last_value is None:
                last_value: dt.date = today - dt.timedelta(days=sync_lookback_days)
            else:
                last_value = db_incremental_field_last_value

            since = last_value.date() if isinstance(last_value, dt.datetime) else last_value
            since = max(since, earliest_since)
            time_range = {
                "since": since.strftime("%Y-%m-%d"),
                # Meta Ads API is day based so only import if the day is complete
                "until": today.strftime("%Y-%m-%d"),
            }
        elif schema.is_stats:
            since = max(today - dt.timedelta(days=sync_lookback_days), earliest_since)
            time_range = {
                "since": since.strftime("%Y-%m-%d"),
                "until": today.strftime("%Y-%m-%d"),
            }

        formatted_url = schema.url.format(API_VERSION=api_version, account_id=_clean_account_id(config.account_id))

        if schema.single_object:
            yield from _fetch_single_object(formatted_url, {"fields": ",".join(schema.field_names)}, access_token)
            return

        params = {
            "fields": ",".join(schema.field_names),
            "limit": PAGE_LIMIT_FALLBACK_SIZES[0],
            **schema.extra_params,
        }
        # Attribution settings apply only to Insights (stats) tables; entity endpoints (campaigns,
        # ads, ...) don't take them and Meta would reject the extra params.
        if schema.is_stats:
            params.update(_attribution_params(config))

        yield from _make_paginated_api_request(
            formatted_url, params, access_token, time_range, resumable_source_manager
        )

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=schema.primary_keys,
        partition_mode=schema.partition_mode,
        partition_format=schema.partition_format,
        partition_keys=schema.partition_keys,
    )
