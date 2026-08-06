import re
import datetime as dt
import collections.abc
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

logger = structlog.get_logger(__name__)

# The JSON incarnation of the Bing Webmaster API. Every method is a GET under this path, the
# API key rides in the `apikey` query param, and results come back as an array under `"d"`.
# Docs: https://learn.microsoft.com/en-us/bingwebmaster/api-protocols
BING_API_BASE = "https://ssl.bing.com/webmaster/api.svc/json"

# Bing serializes timestamps as `/Date(1399100400000-0700)/`: epoch milliseconds (UTC) with an
# optional trailing timezone offset. The offset is informational — the leading integer is the
# instant — so we only need to pull that integer out.
_MS_DATE_RE = re.compile(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/")


class BingWebmasterToolsError(Exception):
    """A Bing Webmaster API call failed in a way no retry recovers (e.g. a JSON ApiFault).

    The raw response can echo the request URL, which carries the API key in a query param, so
    callers surface a generic message and never `str(e)` from the vendor body.
    """


def _parse_ms_date(value: Any) -> dt.date | None:
    """Parse a Bing `/Date(ms)/` timestamp into a calendar date, or None if unparseable.

    The stats tables are daily buckets stamped at midnight Pacific, which lands in the morning
    UTC of the same calendar day, so the UTC date of the instant is the intended day.
    """
    if not isinstance(value, str):
        return None
    match = _MS_DATE_RE.search(value)
    if match is None:
        return None
    return dt.datetime.fromtimestamp(int(match.group(1)) / 1000, tz=dt.UTC).date()


def _as_int(value: Any) -> int:
    """Coerce an API counter to int. Absent fields default to 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_site_url(raw: str) -> str:
    """Lowercase the scheme and host and drop a trailing slash, for tolerant comparison.

    Bing lists a property as e.g. `http://example.com` but its examples call the stats methods
    with a trailing slash, and hosts/schemes are case-insensitive. Normalizing both sides lets a
    user-entered value match the registered property without forcing them to match Bing's exact
    punctuation.
    """
    site = raw.strip()
    parsed = urlparse(site)
    if parsed.scheme.lower() in ("http", "https"):
        site = urlunparse(parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower()))
    return site.rstrip("/")


def bing_session(api_key: str) -> requests.Session:
    # The API key rides in the query string, so redact it from tracked-transport logs and samples.
    return make_tracked_session(redact_values=(api_key,))


def _request(session: requests.Session, method: str, api_key: str, params: dict[str, str]) -> list[dict[str, Any]]:
    query = urlencode({"apikey": api_key, **params})
    url = f"{BING_API_BASE}/{method}?{query}"
    response = session.get(url)
    # 401/403 for a bad key and transient 429/5xx are handled by the tracked session's retry and,
    # for the fatal ones, by `get_non_retryable_errors` matching the raised HTTPError text.
    response.raise_for_status()

    try:
        body = response.json()
    except ValueError:
        raise BingWebmasterToolsError(f"Bing Webmaster Tools returned a non-JSON response for {method}.")

    # Success is an array under `"d"`. A dict without it (or a null `d`) is an ApiFault; the body
    # can contain the request URL (and thus the key), so we log it (the tracked session redacts the
    # key) but never fold it into the raised message.
    if not isinstance(body, dict) or body.get("d") is None:
        logger.warning("Bing Webmaster Tools API fault", method=method, body=body)
        raise BingWebmasterToolsError(f"Bing Webmaster Tools rejected the request for {method}.")

    rows = body["d"]
    if not isinstance(rows, list):
        raise BingWebmasterToolsError(f"Bing Webmaster Tools returned an unexpected shape for {method}.")
    return rows


def list_user_sites(session: requests.Session, api_key: str) -> list[dict[str, Any]]:
    return _request(session, "GetUserSites", api_key, {})


def _traffic_row(row: dict[str, Any]) -> dict[str, Any]:
    # Pin each metric to a stable type. Bing serializes an exact-zero average position as a JSON
    # integer, so a day where every row is zero would yield an int64 column that a later day's
    # fractional value can't cast into — the same drift the Google Search Console source pins for.
    return {
        "Query": row.get("Query"),
        "Date": _parse_ms_date(row.get("Date")),
        "Clicks": _as_int(row.get("Clicks")),
        "Impressions": _as_int(row.get("Impressions")),
        "AvgClickPosition": _as_float(row.get("AvgClickPosition")),
        "AvgImpressionPosition": _as_float(row.get("AvgImpressionPosition")),
    }


def _rank_and_traffic_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "Date": _parse_ms_date(row.get("Date")),
        "Clicks": _as_int(row.get("Clicks")),
        "Impressions": _as_int(row.get("Impressions")),
    }


_CRAWL_COUNTERS = (
    "CrawledPages",
    "InIndex",
    "InLinks",
    "CrawlErrors",
    "Code2xx",
    "Code301",
    "Code302",
    "Code4xx",
    "Code5xx",
    "AllOtherCodes",
    "BlockedByRobotsTxt",
    "ContainsMalware",
)


def _crawl_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"Date": _parse_ms_date(row.get("Date"))}
    for counter in _CRAWL_COUNTERS:
        out[counter] = _as_int(row.get(counter))
    return out


_ROW_NORMALIZERS: dict[str, collections.abc.Callable[[dict[str, Any]], dict[str, Any]]] = {
    "query_stats": _traffic_row,
    "page_stats": _traffic_row,
    "rank_and_traffic_stats": _rank_and_traffic_row,
    "crawl_stats": _crawl_row,
}


def _sorted_by_date(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # `sort_mode="asc"` promises the pipeline that the incremental watermark advances with each
    # batch, so rows must actually arrive oldest-first. Bing documents no ordering, so sort here.
    return sorted(rows, key=lambda row: row.get("Date") or dt.date.min)


def bing_webmaster_tools_source(config: Any, resource_name: str, team_id: int) -> SourceResponse:
    if resource_name not in ENDPOINTS:
        raise ValueError(f"Unknown Bing Webmaster Tools schema: {resource_name}")

    endpoint = ENDPOINTS[resource_name]
    method = endpoint["method"]
    normalize = _ROW_NORMALIZERS[resource_name]
    site_url = config.site_url
    api_key = config.api_key

    def get_rows() -> collections.abc.Iterator[list[dict[str, Any]]]:
        session = bing_session(api_key)
        # Bing has no server-side date filter or pagination: one call returns the property's whole
        # retention window (~6 months). We re-fetch it in full every sync and let merge dedupe on
        # the primary key, which both upserts the recent days Bing keeps restating and accumulates
        # history past the point where old days fall out of the vendor's window.
        raw = _request(session, method, api_key, {"siteUrl": site_url})
        rows = _sorted_by_date([normalize(row) for row in raw])
        if rows:
            yield rows

    return SourceResponse(
        name=NamingConvention.normalize_identifier(resource_name),
        items=get_rows,
        primary_keys=list(endpoint["primary_key"]),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="day",
        partition_keys=["Date"],
        sort_mode="asc",
    )
