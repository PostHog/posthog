import re
import datetime as dt
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.settings import (
    BASE_URL,
    ENDPOINT_CONFIGS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT_SECONDS = 60

# Credential validation runs synchronously on a web worker during source setup, so bound it more
# tightly than a background sync request.
VALIDATION_TIMEOUT_SECONDS = 30


class BingWebmasterToolsError(Exception):
    """API-level failure carrying the ApiFault ``Message`` (e.g. InvalidApiKey, NotAuthorized).

    The fault message is part of the exception text so ``get_non_retryable_errors`` can match on
    it. Faults not in that map (e.g. throttling) stay retryable at the activity level.
    """


# The API key rides the `apikey` query param, so it ends up in the request URL that
# `raise_for_status()` embeds in its message. Redact it so the key never reaches stored errors.
_APIKEY_RE = re.compile(r"([?&]apikey=)[^&\s]+", re.IGNORECASE)

# WCF JSON date, e.g. `/Date(1316156400000-0700)/`: milliseconds since the Unix epoch (UTC),
# optionally followed by the local UTC offset the value was recorded in.
_WCF_DATE_RE = re.compile(r"^/Date\((-?\d+)(?:([+-])(\d{2})(\d{2}))?\)/$")


def _redact_api_key(text: str) -> str:
    return _APIKEY_RE.sub(r"\1REDACTED", text)


def parse_wcf_date(value: Any) -> dt.date | None:
    """Parse a WCF JSON date into the calendar date the API meant.

    The milliseconds are the UTC epoch instant of local midnight, so the embedded offset must be
    applied before truncating to a date; dropping it would shift dates recorded in timezones east
    of UTC onto the previous day. Returns None for anything unparseable.
    """
    if not isinstance(value, str):
        return None
    match = _WCF_DATE_RE.match(value.strip())
    if match is None:
        return None
    moment = dt.datetime.fromtimestamp(int(match.group(1)) / 1000, tz=dt.UTC)
    if match.group(2) is not None:
        sign = 1 if match.group(2) == "+" else -1
        moment += sign * dt.timedelta(hours=int(match.group(3)), minutes=int(match.group(4)))
    return moment.date()


def _api_fault_message(response: requests.Response) -> str | None:
    """Extract the ApiFault ``Message`` (e.g. "InvalidApiKey") from an error body, if present."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    for candidate in (body, body.get("d")):
        if isinstance(candidate, dict):
            message = candidate.get("Message")
            if isinstance(message, str) and message:
                return message
    return None


def _request(
    session: requests.Session,
    api_key: str,
    method: str,
    params: dict[str, str] | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    try:
        response = session.get(
            f"{BASE_URL}/{method}",
            params={"apikey": api_key, **(params or {})},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        # Connection and timeout errors embed the full request URL (including `apikey`) in their
        # message, and `str(error)` ends up in logs and the schema's stored error. Re-raise the
        # same type with the key redacted; preserving the type keeps retry classification intact.
        raise type(exc)(_redact_api_key(str(exc))) from None

    if not response.ok:
        fault = _api_fault_message(response)
        if fault is not None:
            raise BingWebmasterToolsError(
                f"Bing Webmaster Tools {method} failed with status {response.status_code}: {fault}"
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # Keep the `... for url: https://ssl.bing.com` shape intact for non-retryable matching,
            # with the key redacted out of the embedded URL.
            raise requests.HTTPError(_redact_api_key(str(exc)), response=exc.response) from None

    try:
        payload = response.json()
    except ValueError:
        raise BingWebmasterToolsError(f"Bing Webmaster Tools {method} returned a non-JSON response")

    # Successful responses wrap the result list in WCF's `d` envelope: `{"d": [...]}`.
    data = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise BingWebmasterToolsError(f"Bing Webmaster Tools {method} returned an unexpected response shape")
    return [item for item in data if isinstance(item, dict)]


def _site_key(url: str) -> str:
    """Comparison key for site URLs: hosts are case-insensitive and Bing usually lists sites with a
    trailing slash, so compare lowercased and without one."""
    return url.strip().rstrip("/").lower()


def suggest_verified_site(filter_url: str, verified: list[str]) -> str | None:
    """The verified site a bare-hostname filter entry most likely meant, else None.

    Bing lists every site with a scheme (e.g. ``https://example.com/``), so an entry that omits the
    scheme (``example.com``) matches nothing on the scheme-sensitive site key even when that host is
    verified. When the entry is a bare hostname, point at the verified site sharing that host so the
    "not verified" error can name the exact value to paste instead of dead-ending."""
    stripped = filter_url.strip()
    if not stripped or "://" in stripped:
        return None
    host = stripped.strip("/").lower()
    if not host:
        return None
    for url in verified:
        if urlparse(url).netloc.lower() == host:
            return url
    return None


def parse_site_urls(raw: str | None) -> list[str]:
    """Parse the optional site filter field: one URL per line, blanks skipped, duplicates dropped."""
    if not raw:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        key = _site_key(stripped)
        if key in seen:
            continue
        seen.add(key)
        urls.append(stripped)
    return urls


def select_site_urls(sites: list[dict[str, Any]], site_url_filters: list[str]) -> list[str]:
    """Pick the verified site URLs to sync, honoring the user's optional filter list.

    Stats calls against unverified sites fail, so only verified sites are eligible. A filter entry
    matching no verified site raises: a silent skip would read as "synced fine, zero rows" for a
    site the user explicitly asked for.
    """
    verified = [url for site in sites if site.get("IsVerified") and (url := site.get("Url"))]
    if not site_url_filters:
        return verified

    by_key = {_site_key(url): url for url in verified}
    selected: list[str] = []
    missing: list[str] = []
    for filter_url in site_url_filters:
        matched = by_key.get(_site_key(filter_url))
        if matched is None:
            missing.append(filter_url)
        else:
            selected.append(matched)
    if missing:
        suggestions = {
            entry: match for entry in missing if (match := suggest_verified_site(entry, verified)) is not None
        }
        hint = ""
        if suggestions:
            pairs = "; ".join(f"'{entered}' is verified as '{match}'" for entered, match in suggestions.items())
            hint = f"Bing lists sites with their full URL, so {pairs}. "
        raise ValueError(
            f"These site URLs are not verified sites on the connected account: {', '.join(missing)}. "
            f"{hint}"
            "Enter each site exactly as Bing Webmaster Tools lists it, or clear the field to sync "
            "every verified site."
        )
    return selected


def _site_row(site: dict[str, Any]) -> dict[str, Any]:
    # AuthenticationCode and DnsVerificationCode are site-ownership verification tokens with no
    # analytics value, so they stay out of the warehouse.
    return {"url": site.get("Url"), "is_verified": bool(site.get("IsVerified", False))}


def _stats_row(item: dict[str, Any], site_url: str) -> dict[str, Any] | None:
    """Turn one API stats object into a row: snake_case keys, parsed date, stamped site URL.

    Keys are normalized with the same convention the pipeline applies to column names, so the
    declared primary/partition keys match the yielded rows exactly. `date` is part of every stats
    table's primary key, so it is indexed directly: a missing field is a structural API change that
    should fail loudly, while a present-but-malformed value skips the row so a null key never flows
    into the merge.
    """
    row = {NamingConvention.normalize_identifier(key): value for key, value in item.items() if key != "__type"}
    date = parse_wcf_date(row["date"])
    if date is None:
        return None
    row["date"] = date
    row["site_url"] = site_url
    return row


def get_rows(
    api_key: str,
    endpoint: str,
    site_urls_raw: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = ENDPOINT_CONFIGS[endpoint]
    # One session reused across every call so urllib3 keeps the connection alive. `redact_values`
    # masks the API key wherever the tracked transport logs or samples the request URL.
    session = make_tracked_session(redact_values=(api_key,))
    sites = _request(session, api_key, "GetUserSites")

    if not config.per_site:
        rows = [_site_row(site) for site in sites if site.get("Url")]
        if rows:
            yield rows
        return

    for site_url in select_site_urls(sites, parse_site_urls(site_urls_raw)):
        items = _request(session, api_key, config.method, {"siteUrl": site_url})
        rows = []
        dropped = 0
        for item in items:
            row = _stats_row(item, site_url)
            if row is None:
                dropped += 1
            else:
                rows.append(row)
        if dropped:
            logger.warning(
                "Dropped Bing Webmaster Tools rows with unparseable dates",
                endpoint=endpoint,
                site_url=site_url,
                dropped=dropped,
            )
        if rows:
            yield rows


def validate_credentials(api_key: str, site_urls_raw: str | None) -> tuple[bool, str | None]:
    """Probe GetUserSites: one cheap call that authenticates the key and returns the site list,
    which also lets the optional site filter be checked against what the account can actually see."""
    session = make_tracked_session(redact_values=(api_key,))
    try:
        sites = _request(session, api_key, "GetUserSites", timeout=VALIDATION_TIMEOUT_SECONDS)
    except BingWebmasterToolsError as exc:
        message = str(exc)
        if "InvalidApiKey" in message or "UserNotFound" in message:
            return False, (
                "Bing Webmaster Tools rejected the API key. Generate a new key under Settings > "
                "API access in Bing Webmaster Tools and try again."
            )
        return False, f"Could not validate the Bing Webmaster Tools connection: {message}"
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (400, 401, 403):
            return False, (
                "Bing Webmaster Tools rejected the API key. Generate a new key under Settings > "
                "API access in Bing Webmaster Tools and try again."
            )
        return False, "The Bing Webmaster Tools API returned an error. Try again in a few minutes."
    except requests.RequestException:
        return False, "Could not reach the Bing Webmaster Tools API. Please try again."

    try:
        selected = select_site_urls(sites, parse_site_urls(site_urls_raw))
    except ValueError as exc:
        return False, str(exc)

    if not selected:
        return False, (
            "The connected account has no verified sites in Bing Webmaster Tools. Verify a site first, then reconnect."
        )
    return True, None


def bing_webmaster_tools_source(
    api_key: str,
    endpoint: str,
    site_urls_raw: str | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = ENDPOINT_CONFIGS[endpoint]

    if not config.per_site:
        return SourceResponse(
            name=endpoint,
            items=lambda: get_rows(api_key=api_key, endpoint=endpoint, site_urls_raw=site_urls_raw, logger=logger),
            primary_keys=list(config.primary_keys),
            # A snapshot of the current account state, with no timestamp to order or partition on.
            sort_mode=None,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, site_urls_raw=site_urls_raw, logger=logger),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["date"],
        # Bing documents no ordering for these responses, and the multi-site fan-out interleaves
        # date ranges across batches anyway, so no per-batch watermark checkpointing is claimed.
        # The source never consumes the watermark: every sync refetches the full retained window
        # and relies on merge dedupe.
        sort_mode=None,
    )
