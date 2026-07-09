import re
import json
import datetime as dt
from collections.abc import Generator
from typing import Any, Optional

import requests
import structlog
from linkedin_api.clients.restli.client import RestliClient
from linkedin_api.common.errors import ResponseFormattingError
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from .schemas import (
    LINKEDIN_ADS_ENDPOINTS,
    LINKEDIN_ADS_PIVOTS,
    RESOURCE_SCHEMAS,
    LinkedinAdsPivot,
    LinkedinAdsResource,
)

logger = structlog.get_logger(__name__)

LINKEDIN_SPONSORED_URN_PREFIX = "urn:li:sponsored"
MAX_PAGE_SIZE = 1000
CREATIVES_PAGE_SIZE = 100  # creatives backend returns transient 500s on heavier requests
API_VERSION = "202508"

# `q=analytics` silently truncates a response at 15k elements. With DAILY granularity an element
# is one (day × active pivot value), so a window of N days over an account with P active pivot
# values returns ~N*P elements. Rather than a fixed weekly window (which makes ~52 calls/year for
# a 1-campaign account just like a 1000-campaign one), we start wide and shrink the window only
# when a response comes back truncated. Small accounts then sync a long range in a single call,
# which is what keeps us under LinkedIn's per-member daily call budget. The window size is carried
# forward across chunks so we discover the right size once instead of per chunk.
ANALYTICS_RESPONSE_CAP = 15000
ANALYTICS_INITIAL_CHUNK_DAYS = 365
ANALYTICS_MIN_CHUNK_DAYS = 1
# Below this fill level a window has enough headroom to widen for the next chunk, so a single dense
# spike that forced a shrink doesn't keep the window small across an otherwise sparse date range.
ANALYTICS_GROW_THRESHOLD = ANALYTICS_RESPONSE_CAP // 4

# Upper bound on how long we'll honour a Retry-After header before giving up, so a hostile or
# misconfigured value can't hang the activity past its heartbeat.
MAX_RETRY_AFTER_SECONDS = 60.0

# LinkedIn 429 throttle bodies name the window that was exceeded (SECOND / MINUTE / DAY). A DAY
# throttle is the per-member/app daily call budget and only resets at midnight UTC, so it must not
# be retried within the run.
_DAY_THROTTLE_PATTERN = re.compile(r"\bDAY\b")


class LinkedinAdsRetryableError(Exception):
    """Transient LinkedIn API error (5xx / short-window 429) that should be retried.

    `retry_after` carries the parsed Retry-After header (seconds) when LinkedIn provides one,
    so the retry wait can honour it instead of the default exponential backoff.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LinkedinAdsDailyRateLimitError(Exception):
    """LinkedIn per-day rate limit reached (429 with a DAY throttle window).

    Not retried within the run: the member/app daily call budget only resets at midnight UTC, so
    retrying just burns the remaining budget. We fail fast and let the next scheduled sync resume.
    """


class LinkedinAdsApiError(Exception):
    """A non-retryable LinkedIn API response. `api_status_code` lets callers branch on the failure
    (a 401/403 is a customer-side credential problem) without parsing the message.

    Deliberately not named `status_code`: drf-exceptions-hog reads that attribute off any escaping
    exception and would render LinkedIn's status as PostHog's HTTP response status.
    """

    def __init__(self, message: str, api_status_code: int) -> None:
        super().__init__(message)
        self.api_status_code = api_status_code


def _parse_retry_after(response: Any) -> float | None:
    """Pull a numeric Retry-After (seconds) off the underlying requests.Response, if present.
    LinkedIn sends integer seconds; HTTP-date forms and negative/garbage values are ignored
    (treated as absent), so a malformed header falls back to exponential backoff rather than a
    zero/negative sleep that would either hammer the API or crash tenacity's `time.sleep`."""
    headers = getattr(getattr(response, "response", None), "headers", None)
    if not headers:
        return None
    raw = headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _is_daily_throttle(body: str | None) -> bool:
    return bool(body and _DAY_THROTTLE_PATTERN.search(body))


_exponential_wait = wait_exponential_jitter(initial=1, max=30)


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honour a Retry-After (capped) when the failing call surfaced one, else fall back to
    exponential jitter for transient transport / 5xx errors."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        return min(float(retry_after), MAX_RETRY_AFTER_SECONDS)
    return _exponential_wait(retry_state)


class LinkedinAdsClient:
    """LinkedIn Marketing API client."""

    def __init__(self, access_token: str):
        if not access_token:
            raise ValueError("Access token required")
        self.access_token = access_token
        self.client = RestliClient()
        self.api_version = API_VERSION

    def get_accounts(self) -> list[dict[str, Any]]:
        """Every ad account the authorized member can access.

        `q=search` pages like the other finders (cursor pagination from LinkedIn-Version 202401
        onwards) and defaults to a page size of ~10, so a member with more accounts than that would
        otherwise get a silently truncated list. Accounts are few enough to collect eagerly.
        """
        accounts: list[dict[str, Any]] = []
        for elements, _ in self._make_paginated_request(
            endpoint=LinkedinAdsResource.Accounts,
            path=f"/{LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Accounts]}",
        ):
            accounts.extend(elements)
        return accounts

    def get_campaigns(
        self, account_id: str, starting_page_token: Optional[str] = None
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]]]:
        """Get campaigns with pagination, yielding each page with its nextPageToken."""
        account_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Accounts]
        campaigns_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Campaigns]
        yield from self._make_paginated_request(
            endpoint=LinkedinAdsResource.Campaigns,
            path=f"/{account_endpoint}/{account_id}/{campaigns_endpoint}",
            starting_page_token=starting_page_token,
        )

    def get_campaign_groups(
        self, account_id: str, starting_page_token: Optional[str] = None
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]]]:
        """Get campaign groups with pagination, yielding each page with its nextPageToken."""
        account_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Accounts]
        groups_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.CampaignGroups]
        yield from self._make_paginated_request(
            endpoint=LinkedinAdsResource.CampaignGroups,
            path=f"/{account_endpoint}/{account_id}/{groups_endpoint}",
            starting_page_token=starting_page_token,
        )

    def get_creatives(
        self, account_id: str, starting_page_token: Optional[str] = None
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]]]:
        """Get creatives with pagination. Uses `q=criteria` and reduced page size
        (the creatives backend 500s on heavier requests)."""
        account_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Accounts]
        creatives_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Creatives]
        yield from self._make_paginated_request(
            endpoint=LinkedinAdsResource.Creatives,
            path=f"/{account_endpoint}/{account_id}/{creatives_endpoint}",
            starting_page_token=starting_page_token,
            finder="criteria",
            page_size=CREATIVES_PAGE_SIZE,
        )

    def get_analytics(
        self,
        account_id: str,
        pivot: LinkedinAdsPivot = LinkedinAdsPivot.CAMPAIGN,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Generator[tuple[list[dict[str, Any]], None]]:
        """Fetch analytics in adaptive date-range chunks sized to stay under the 15k-element
        response cap. The window starts wide and shrinks (halving) only when a response comes
        back truncated, then carries the learned size forward. A truncated response is silently
        capped by LinkedIn — we can't tell which rows were dropped — so we discard it and re-fetch
        the same start with a smaller window rather than yielding partial data. Only a single-day
        window that still caps is surfaced (with a warning), since it can't be split further."""
        resource_by_pivot = {
            LinkedinAdsPivot.CAMPAIGN: LinkedinAdsResource.CampaignStats,
            LinkedinAdsPivot.CAMPAIGN_GROUP: LinkedinAdsResource.CampaignGroupStats,
            LinkedinAdsPivot.CREATIVE: LinkedinAdsResource.CreativeStats,
        }
        resource = resource_by_pivot.get(pivot, LinkedinAdsResource.CampaignStats)
        fields = ",".join(self._get_fields_for_resource(resource))
        accounts = [f"{LINKEDIN_SPONSORED_URN_PREFIX}Account:{account_id}"]

        def _build_params(chunk_start: Optional[str], chunk_end: Optional[str]) -> dict[str, Any]:
            params: dict[str, Any] = {
                "q": "analytics",
                "pivot": pivot.value,
                "timeGranularity": "DAILY",
                "accounts": accounts,
                "fields": fields,
            }
            if chunk_start and chunk_end:
                params["dateRange"] = self._format_date_range(chunk_start, chunk_end)
            return params

        if not (date_start and date_end):
            yield (
                self._make_request(endpoint=resource, finder="analytics", extra_params=_build_params(None, None)),
                None,
            )
            return

        chunk_days = ANALYTICS_INITIAL_CHUNK_DAYS
        chunk_start = dt.date.fromisoformat(date_start)
        end_date = dt.date.fromisoformat(date_end)
        while chunk_start <= end_date:
            chunk_end = min(chunk_start + dt.timedelta(days=chunk_days - 1), end_date)
            elements = self._make_request(
                endpoint=resource,
                finder="analytics",
                extra_params=_build_params(chunk_start.isoformat(), chunk_end.isoformat()),
            )
            capped = len(elements) >= ANALYTICS_RESPONSE_CAP
            window_days = (chunk_end - chunk_start).days + 1

            # Truncated response and the window spans more than a day: halve it (by its real span,
            # so a window already clamped by end_date converges fast) and re-fetch the same start.
            if capped and window_days > ANALYTICS_MIN_CHUNK_DAYS:
                chunk_days = max(ANALYTICS_MIN_CHUNK_DAYS, window_days // 2)
                continue

            if capped:
                logger.warning(
                    "linkedin_ads.analytics_chunk_capped",
                    pivot=pivot.value,
                    chunk_start=chunk_start.isoformat(),
                    chunk_end=chunk_end.isoformat(),
                    received=len(elements),
                )

            yield elements, None
            chunk_start = chunk_end + dt.timedelta(days=1)

            # Plenty of headroom left: widen the next window so a sparse range doesn't keep paying
            # for a window we shrank to fit an earlier dense spike.
            if not capped and len(elements) < ANALYTICS_GROW_THRESHOLD and chunk_days < ANALYTICS_INITIAL_CHUNK_DAYS:
                chunk_days = min(ANALYTICS_INITIAL_CHUNK_DAYS, chunk_days * 2)

    def get_data_by_resource(
        self,
        resource: LinkedinAdsResource,
        account_id: str,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        starting_page_token: Optional[str] = None,
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]]]:
        """Get data by resource, yielding each page and its nextPageToken (if any).

        `starting_page_token` applies to the paginated entity endpoints (campaigns,
        campaign_groups, creatives) and is ignored for single-shot endpoints
        (accounts, analytics — analytics paginates by date-range chunking instead).
        """
        if resource == LinkedinAdsResource.Accounts:
            yield self.get_accounts(), None
        elif resource == LinkedinAdsResource.Campaigns:
            yield from self.get_campaigns(account_id, starting_page_token=starting_page_token)
        elif resource == LinkedinAdsResource.CampaignGroups:
            yield from self.get_campaign_groups(account_id, starting_page_token=starting_page_token)
        elif resource == LinkedinAdsResource.Creatives:
            yield from self.get_creatives(account_id, starting_page_token=starting_page_token)
        elif resource in LINKEDIN_ADS_PIVOTS:
            yield from self.get_analytics(account_id, LINKEDIN_ADS_PIVOTS[resource], date_start, date_end)
        else:
            raise ValueError(f"Unsupported resource: {resource}")

    def _get_fields_for_resource(self, resource: LinkedinAdsResource) -> list[str]:
        """Get field names for a resource from the schema definition."""
        if resource not in RESOURCE_SCHEMAS:
            raise ValueError(f"No schema defined for resource: {resource}")
        return RESOURCE_SCHEMAS[resource]["field_names"]

    @retry(
        retry=retry_if_exception_type((LinkedinAdsRetryableError, requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(5),
        wait=_retry_wait,
        reraise=True,
    )
    def _call_finder(self, resource_path: str, finder: str, params: dict[str, Any]) -> Any:
        """Call the Restli finder with bounded retries on transient transport and 5xx/429 errors.

        LinkedIn's edge occasionally drops TLS connections mid-handshake (SSLEOFError) or
        returns 504s; those surface here as `requests.ConnectionError` / `requests.Timeout`
        from the underlying requests.Session, or as a non-2xx response we convert to
        `LinkedinAdsRetryableError`. Non-retryable 4xx responses still raise immediately.

        429s are split by throttle window: a DAY throttle is the per-member/app daily call budget
        (resets only at midnight UTC) and raises a non-retryable `LinkedinAdsDailyRateLimitError`
        so we fail fast instead of burning the remaining budget on doomed retries. Short-window
        429s stay retryable and honour the Retry-After header when present.
        """
        try:
            response = self.client.finder(
                resource_path=resource_path,
                finder_name=finder,
                access_token=self.access_token,
                query_params=params,
                version_string=self.api_version,
            )
        except ResponseFormattingError as e:
            # The Restli client parses the body as JSON before returning, so a non-JSON response
            # (an empty payload or an HTML error page from a 5xx gateway/proxy) raises here as a
            # wrapped JSONDecodeError rather than a status code we can branch on below. These are
            # transient edge responses — retry them like the 5xx path instead of failing the sync.
            raise LinkedinAdsRetryableError(f"LinkedIn API returned a malformed (non-JSON) response: {e}") from e

        if response.status_code == 429:
            body = response.response.text
            if _is_daily_throttle(body):
                raise LinkedinAdsDailyRateLimitError(f"LinkedIn daily rate limit reached (429): {body}")
            raise LinkedinAdsRetryableError(
                f"LinkedIn API error (retryable, 429): {body}",
                retry_after=_parse_retry_after(response),
            )
        if response.status_code >= 500:
            raise LinkedinAdsRetryableError(
                f"LinkedIn API error (retryable, {response.status_code}): {response.response.text}"
            )
        if response.status_code != 200:
            raise LinkedinAdsApiError(
                f"LinkedIn API error ({response.status_code}): {response.response.text}", response.status_code
            )

        return response

    def _make_request(
        self, endpoint: LinkedinAdsResource, finder: str, extra_params: dict | None = None, path: str | None = None
    ) -> list[dict[str, Any]]:
        fields = self._get_fields_for_resource(endpoint)
        params = {"fields": ",".join(fields)}
        if extra_params:
            params.update(extra_params)

        resource_path = path or f"/{LINKEDIN_ADS_ENDPOINTS[endpoint]}"

        response = self._call_finder(resource_path=resource_path, finder=finder, params=params)

        return response.elements

    def _make_paginated_request(
        self,
        endpoint: LinkedinAdsResource,
        path: str,
        starting_page_token: Optional[str] = None,
        finder: str = "search",
        page_size: int = MAX_PAGE_SIZE,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]]]:
        """Yield each page as `(elements, next_page_token)` (None on the last page).
        Callers persist `next_page_token` to resume without re-fetching."""
        page_token = starting_page_token

        while True:
            fields = self._get_fields_for_resource(endpoint)
            params: dict[str, Any] = {"fields": ",".join(fields), "pageSize": page_size}
            if extra_params:
                params.update(extra_params)
            if page_token:
                params["pageToken"] = page_token

            response = self._call_finder(resource_path=path, finder=finder, params=params)

            if not response.elements:
                break

            # A malformed/empty envelope is treated as "no more pages" rather than crashing the sync.
            try:
                metadata = json.loads(response.response.text).get("metadata", {})
            except (TypeError, ValueError):
                metadata = {}
            next_page_token = metadata.get("nextPageToken")

            yield response.elements, next_page_token

            if not next_page_token:
                break

            page_token = next_page_token

    def _format_date_range(self, date_start: str, date_end: str) -> dict:
        """Format date range for LinkedIn API as structured object."""

        def format_date(date_str):
            year = int(date_str[:4])
            month = int(date_str[5:7])
            day = int(date_str[8:10])
            return {"year": year, "month": month, "day": day}

        return {"start": format_date(date_start), "end": format_date(date_end)}
