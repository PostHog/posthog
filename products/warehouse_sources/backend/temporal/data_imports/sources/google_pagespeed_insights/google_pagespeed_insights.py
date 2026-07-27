import re
import ipaddress
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.google_pagespeed_insights.settings import (
    PAGESPEED_ENDPOINTS,
    PageSpeedEndpointConfig,
)

# The PageSpeed Insights v5 API is a single GET endpoint that runs an on-demand Lighthouse analysis of
# a supplied URL and returns a large nested JSON document. Auth is a Google Cloud API key on the `key`
# query param. There is no pagination and no server-side change cursor, so every table is full-refresh
# over the configured URL list (append is supported so users can accumulate a score time series).
PAGESPEED_BASE_URL = "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed"

# A Lighthouse run takes several seconds; give each request generous headroom before treating it as
# a timeout worth retrying.
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 5

# Credential validation runs synchronously on a web worker during source setup, so bound it more
# tightly than a background sync: a single attempt with a shorter timeout. A valid key still runs a
# full analysis before returning 200, so keep enough headroom for that while capping the worker hold.
VALIDATION_TIMEOUT_SECONDS = 60

# Disable adapter-level (urllib3) retries on the tracked session so the Tenacity policy on `_fetch`
# is the only retry layer. Otherwise the two layers compound — up to `MAX_RETRY_ATTEMPTS` Tenacity
# attempts each doing several urllib3 retries fans out to ~20 slow Lighthouse requests per URL, which
# a user could weaponise with repeatedly-timing-out URLs to tie up import workers.
_NO_ADAPTER_RETRIES = Retry(total=0)

# Each URL costs one full (slow) Lighthouse run per enabled table on every sync, so cap the config to
# bound worker time and outbound fan-out — a malformed or abusive config can't tie up the pipeline.
MAX_URLS = 50

# Lighthouse categories requested on every call. `category` is a repeatable query param that enriches
# the response with per-category scores. PWA is intentionally omitted: it was removed from Lighthouse
# 12 (which PageSpeed Insights now runs) and requesting it can 400. This could not be curl-verified
# without an API key, so the set is deliberately the four stable, widely-supported categories.
CATEGORIES = ["PERFORMANCE", "ACCESSIBILITY", "BEST_PRACTICES", "SEO"]


class PageSpeedRetryableError(Exception):
    pass


# Hostname suffixes that only ever resolve inside a private network / to the loopback interface.
_PRIVATE_HOST_SUFFIXES = (".localhost", ".local", ".internal")


def _is_private_host(host: str) -> bool:
    """True for hosts that name a private, loopback, link-local, or otherwise non-public address.

    The runPagespeed fetch is executed by Google's servers (not PostHog's egress), so a private or
    internal URL is unreachable there rather than a server-side request forgery against our network.
    This rejection is defense-in-depth: it fails such URLs early with a clear message and keeps the
    connector from being pointed at internal-looking hosts.
    """
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(_PRIVATE_HOST_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


def parse_urls(raw: str | None) -> list[str]:
    """Parse the user's free-text ``urls`` field into a de-duplicated list of URLs.

    Each non-empty line is one URL. Raises ``ValueError`` with an actionable message on malformed
    input (missing scheme/host, too many URLs) so the user can fix the config rather than getting a
    silently empty sync. Duplicates are dropped (order preserved) so the same URL can't seed two rows
    with the same primary key within a single sync.
    """
    if not raw:
        raise ValueError("At least one URL is required.")

    urls: list[str] = []
    seen: set[str] = set()
    for line_number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue

        parsed = urlparse(stripped)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Line {line_number} ({stripped!r}) must be a full URL starting with http:// or https://.")

        if parsed.hostname is None or _is_private_host(parsed.hostname):
            raise ValueError(
                f"Line {line_number} ({stripped!r}) points at a private, local, or non-public address, "
                "which cannot be analyzed. Enter a publicly reachable URL."
            )

        if stripped in seen:
            continue
        seen.add(stripped)
        urls.append(stripped)

        if len(urls) > MAX_URLS:
            raise ValueError(f"Too many URLs: at most {MAX_URLS} are allowed per source.")

    if not urls:
        raise ValueError("At least one URL is required.")

    return urls


def _build_url(target_url: str, strategy: str, api_key: str) -> str:
    # `category` is repeatable, so build an ordered list of (key, value) pairs — urlencode emits one
    # `category=` param per entry, which is how the API wants multiple categories expressed.
    params: list[tuple[str, str]] = [
        ("url", target_url),
        ("strategy", strategy),
        ("key", api_key),
        *[("category", category) for category in CATEGORIES],
    ]
    return f"{PAGESPEED_BASE_URL}?{urlencode(params)}"


# The API key rides the `key` query param, so it ends up in `response.url`, which `raise_for_status()`
# embeds in its message. Redact it so the key never reaches stored errors / logs. Match only the `key`
# query param, not any field that merely contains "key".
_KEY_RE = re.compile(r"([?&]key=)[^&\s]+", re.IGNORECASE)


def _redact_key(text: str) -> str:
    return _KEY_RE.sub(r"\1REDACTED", text)


# `ChunkedEncodingError` and `ContentDecodingError` are siblings of `ConnectionError` under
# `RequestException`, not subclasses, so they must be listed explicitly: a connection broken
# mid-response (server hung up before the body was fully streamed) or a body that fails to decode is
# transient and safe to retry on the large PageSpeed payloads, not a reason to fail the whole sync.
@retry(
    retry=retry_if_exception_type(
        (
            PageSpeedRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ContentDecodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    api_key: str,
    strategy: str,
    target_url: str,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    url = _build_url(target_url, strategy, api_key)
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        # Connection / SSL / timeout errors embed the full request URL (including `key=...`) in their
        # message. `latest_error` stores `str(error)` after retries are exhausted, so re-raise the same
        # exception type with the key redacted — preserving the type keeps retry classification intact.
        raise type(exc)(_redact_key(str(exc))) from None

    # 429 (rate/quota limit) and transient 5xx are retryable; back off and try again. A persistent
    # per-URL analysis failure (e.g. a page that never loads) also surfaces as 5xx and will fail the
    # sync loudly after retries — better than silently dropping a URL the user asked to track.
    if response.status_code == 429 or response.status_code >= 500:
        raise PageSpeedRetryableError(f"PageSpeed Insights API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"PageSpeed Insights API error: status={response.status_code}, body={_redact_key(response.text)}")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # Re-raise with the `key` redacted so the API key never reaches stored errors / logs, keeping
            # the `... for url: https://pagespeedonline.googleapis.com` prefix intact for non-retryable matching.
            raise requests.HTTPError(_redact_key(str(exc)), response=exc.response) from None

    return response.json()


def _analysis_timestamp_to_iso(value: Any) -> str | None:
    """Normalize the API's ``analysisUTCTimestamp`` (RFC 3339, e.g. ``2024-01-15T12:34:56.789Z``) to ISO 8601 UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _normalize_row(config: PageSpeedEndpointConfig, response: dict[str, Any], target_url: str) -> dict[str, Any] | None:
    """Turn one API response into a flat row, stamping it with the requested URL, strategy, and timestamp.

    We inject the *requested* URL (not the echoed ``id``, which is the final resolved URL and can drift
    with redirects between syncs) so the ``[requested_url, analysis_timestamp]`` primary key stays
    stable. The raw ``analysisUTCTimestamp`` is preserved; ``analysis_timestamp`` is the derived,
    parseable copy used for partitioning and as the append cursor. Returns ``None`` when the timestamp
    is present but unparseable, so a null key never flows into the merge.
    """
    row = dict(response)
    row["requested_url"] = target_url
    row["strategy"] = config.strategy

    # `analysis_timestamp` derives from this field and is part of the primary key, so index directly: a
    # missing field is a structural API change that should fail loudly with a `KeyError` rather than
    # silently dropping every row. A present-but-malformed value still parses to `None` and is skipped.
    analysis_timestamp = _analysis_timestamp_to_iso(response["analysisUTCTimestamp"])
    if analysis_timestamp is None:
        return None
    row["analysis_timestamp"] = analysis_timestamp
    return row


def validate_credentials(api_key: str, urls_raw: str | None) -> tuple[bool, str | None]:
    """Probe the runPagespeed endpoint with the first configured URL.

    Google validates the API key before running Lighthouse, so an invalid/missing key returns 400
    (``API key not valid``) and a project without the API enabled returns 403 (``PERMISSION_DENIED``)
    quickly. A valid key runs the full analysis and returns 200, which can take several seconds.
    """
    try:
        urls = parse_urls(urls_raw)
    except ValueError as exc:
        return False, str(exc)

    url = _build_url(urls[0], "DESKTOP", api_key)
    try:
        response = make_tracked_session(retry=_NO_ADAPTER_RETRIES, redact_values=(api_key,)).get(
            url, timeout=VALIDATION_TIMEOUT_SECONDS
        )
    except Exception:
        return False, "Could not reach the Google PageSpeed Insights API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (400, 403):
        return False, (
            "Invalid API key, or the PageSpeed Insights API is not enabled for your Google Cloud project. "
            "Check the key and enable the PageSpeed Insights API, then reconnect."
        )

    return False, f"The PageSpeed Insights API returned an unexpected status code: {response.status_code}"


def get_rows(
    api_key: str,
    endpoint: str,
    urls: list[str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = PAGESPEED_ENDPOINTS[endpoint]
    # One session reused across every URL so urllib3 keeps the connection alive instead of re-handshaking.
    # Adapter-level retries are disabled so Tenacity on `_fetch` is the only retry layer (see
    # `_NO_ADAPTER_RETRIES`). `redact_values` masks the API key wherever the tracked transport logs or
    # samples the request URL.
    session = make_tracked_session(retry=_NO_ADAPTER_RETRIES, redact_values=(api_key,))

    for target_url in urls:
        response = _fetch(session, api_key, config.strategy, target_url, logger)
        row = _normalize_row(config, response, target_url)
        if row is not None:
            yield [row]


def google_pagespeed_insights_source(
    api_key: str,
    endpoint: str,
    urls_raw: str | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = PAGESPEED_ENDPOINTS[endpoint]
    urls = parse_urls(urls_raw)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, urls=urls, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[config.partition_key],
        # One row per URL, each stamped with an analysis timestamp of ~now; rows arrive in config order.
        sort_mode="asc",
        # PageSpeed responses are large, deeply-nested JSON documents (~0.5-1 MiB each, larger for
        # complex pages). We emit one row per URL, so keep the per-chunk byte budget below a single
        # report: the batcher then flushes after roughly every report instead of accumulating the whole
        # URL list into one oversized Arrow/Delta write that could OOM or time out the worker. The
        # buffered footprint stays ~one report regardless of how many URLs are configured.
        chunk_size_bytes=1 * 1024 * 1024,
    )
