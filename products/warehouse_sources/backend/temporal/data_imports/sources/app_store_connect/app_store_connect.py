import io
import re
import csv
import gzip
import math
import time
import hashlib
import tempfile
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import IO, Any, Optional
from urllib.parse import urlsplit

import jwt
import requests
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.settings import (
    ANALYTICS_GRANULARITY,
    ANALYTICS_MAX_INSTANCES_PER_RUN,
    APP_STORE_CONNECT_ENDPOINTS,
    MAX_PAGE_SIZE,
    SALES_REPORT_END_OFFSET_DAYS,
    SALES_REPORT_LOOKBACK_DAYS,
    SALES_REPORT_MAX_DAYS_PER_RUN,
    AppStoreConnectEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BASE_URL = "https://api.appstoreconnect.apple.com"
API_HOST = "api.appstoreconnect.apple.com"

# Apple rejects a token whose `exp` is more than 20 minutes past `iat`, so mint just under the ceiling
# and re-mint while a couple of minutes still remain.
JWT_AUDIENCE = "appstoreconnect-v1"
JWT_LIFETIME_SECONDS = 1140
JWT_REFRESH_MARGIN_SECONDS = 120

REQUEST_TIMEOUT_SECONDS = 60
# Report bodies are whole files rather than a page of JSON.
REPORT_TIMEOUT_SECONDS = 300
CREDENTIALS_TIMEOUT_SECONDS = 15

# `/v1/salesReports` returns a gzipped TSV, not JSON, and only for this Accept type.
REPORT_ACCEPT = "application/a-gzip"

# Hard cap on pages walked for one collection (or one app's collection) so a pagination bug can't scan
# forever. At 200 rows a page that is 400k rows.
MAX_PAGES_PER_RESOURCE = 2000

# Analytics segment downloads are presigned object-store URLs on Apple's storage, not the API origin,
# and they expire about five minutes after the segments call. The Apple bearer token must never be
# sent to them, and the host allowlist keeps a tampered URL from pointing the download at an
# arbitrary or internal host.
ANALYTICS_SEGMENT_HOST_SUFFIXES = (".amazonaws.com", ".apple.com", ".mzstatic.com")

# In-memory cap while downloading one analytics segment; larger segments spool to disk so the
# checksum can be verified before any row is parsed, without holding whole files in memory.
ANALYTICS_SEGMENT_SPOOL_BYTES = 32 * 1024 * 1024

ANALYTICS_ROWS_PER_BATCH = 2000

_PEM_HEADER = "-----BEGIN PRIVATE KEY-----"
_PEM_FOOTER = "-----END PRIVATE KEY-----"
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


class AppStoreConnectAuthError(Exception):
    """The .p8 private key, key ID, or issuer ID can't produce a signed token."""


class AppStoreConnectUrlError(Exception):
    """A request or pagination URL points somewhere other than the App Store Connect API origin."""


class AppStoreConnectPermissionError(Exception):
    """A 403 from App Store Connect: the key's role can't perform this call. Non-retryable."""


# 403 on a report or resource read. The key's role can't read this data, so the fix is a role
# that can. `AppStoreConnectSource.get_non_retryable_errors` matches on this text to fail fast.
APP_STORE_CONNECT_READ_FORBIDDEN_ERROR = (
    "Your App Store Connect API key does not have permission to read this data. Give the key the "
    "Admin, Finance, or Sales role that can read it, then reconnect."
)

# 403 on `POST /v1/analyticsReportRequests`. Apple lets only an Admin key create an analytics
# report request, so a Finance or Sales key reads reports and still loses this create. Named
# separately so the message points at Admin rather than the read roles the key already holds.
APP_STORE_CONNECT_ANALYTICS_CREATE_FORBIDDEN_ERROR = (
    "Your App Store Connect API key cannot start analytics reports. Apple lets only an Admin key "
    "create an analytics report request. Give the key the Admin role, then reconnect."
)

# The app's ONGOING analytics report request stopped after a period of inactivity, and the key's
# role can't create the replacement Apple now needs.
APP_STORE_CONNECT_ANALYTICS_INACTIVE_ERROR = (
    "Your App Store Connect analytics report request stopped because of inactivity. Apple needs a "
    "new request, which only an Admin key can create. Give the key the Admin role, then reconnect."
)

# A sales or subscription report sync started without a vendor number. `/v1/salesReports` can't be
# read without one, so every retry fails identically until the user adds it in the source settings.
# `AppStoreConnectSource.get_non_retryable_errors` matches on this text to fail fast.
APP_STORE_CONNECT_MISSING_VENDOR_NUMBER_ERROR = (
    "Syncing App Store Connect sales reports needs your vendor number. "
    "Add it in the source settings, then run the sync again."
)


@frozen
class _AppleApiError:
    code: str | None
    title: str | None
    detail: str | None


def _parse_apple_error(response: requests.Response) -> _AppleApiError:
    """Pull the first JSON:API error out of an App Store Connect 4xx body.

    Apple returns ``{"errors": [{"code", "title", "detail", ...}]}``, but an edge or proxy can
    return non-JSON, so parse defensively and leave fields ``None`` when the body has no usable error.
    """
    try:
        body = response.json()
    except ValueError:
        return _AppleApiError(code=None, title=None, detail=None)
    errors = body.get("errors") if isinstance(body, dict) else None
    first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    return _AppleApiError(
        code=first.get("code") if isinstance(first.get("code"), str) else None,
        title=first.get("title") if isinstance(first.get("title"), str) else None,
        detail=first.get("detail") if isinstance(first.get("detail"), str) else None,
    )


def _apple_error_suffix(error: _AppleApiError, status_code: int) -> str:
    """Apple's own words appended to a raised message so support sees what Apple actually said."""
    parts = [part for part in (error.code, error.title, error.detail) if part]
    if parts:
        return f"Apple said: {'; '.join(parts)} (HTTP {status_code})"
    return f"HTTP {status_code}"


def _require_api_url(url: str) -> str:
    """Reject any URL that isn't ``https://api.appstoreconnect.apple.com`` on the default HTTPS port.

    ``links.next`` cursors from a response body and resume URLs loaded from persisted state are both
    attacker-influenceable: a tampered API response or a poisoned checkpoint could otherwise point the
    next request — which carries a freshly minted, replayable Apple bearer token — at an arbitrary host.
    Pinning every outbound request to Apple's origin makes a stray URL fail closed.
    """
    try:
        parts = urlsplit(url)
    except Exception as e:
        raise AppStoreConnectUrlError(f"Unparseable App Store Connect URL: {url!r}") from e

    if parts.scheme != "https" or parts.hostname != API_HOST or parts.port not in (None, 443):
        raise AppStoreConnectUrlError(f"Refusing to request a non-App Store Connect URL: {url!r}")
    return url


@dataclasses.dataclass
class AppStoreConnectResumeConfig:
    # Fan-out bookmark: the app currently being walked. A stable Apple id rather than a positional
    # index, so apps added or removed between a crash and the retry can't resume into the wrong app.
    app_id: str | None = None
    # Fully-formed `links.next` URL (carries Apple's opaque cursor) for the collection being walked.
    next_url: str | None = None
    # Report streams bookmark: the next report date to fetch, as `YYYY-MM-DD`.
    report_date: str | None = None
    # Analytics streams bookmark: the next instance processing date to fetch, as
    # `YYYY-MM-DD`. Dates are walked ascending across every app, so no app bookmark is
    # needed. Optional so states saved before this field existed still parse.
    processing_date: str | None = None


def _normalize_private_key(private_key: str) -> str:
    """Coerce a pasted App Store Connect .p8 key into PEM.

    Pastes arrive three ways: real PEM, PEM whose newlines were flattened into literal ``\\n``, or just
    the base64 body with the header and footer stripped off.
    """
    key = (private_key or "").strip().replace("\\n", "\n").replace("\r\n", "\n")
    if not key:
        raise AppStoreConnectAuthError("Add the contents of your App Store Connect .p8 private key file.")
    if "-----BEGIN" in key:
        return key

    body = "".join(key.split())
    lines = [body[index : index + 64] for index in range(0, len(body), 64)]
    return "\n".join([_PEM_HEADER, *lines, _PEM_FOOTER]) + "\n"


class AppStoreConnectTokenProvider:
    """Mints and caches the short-lived ES256 JWT every App Store Connect request carries."""

    def __init__(self, issuer_id: str, key_id: str, private_key: str) -> None:
        self._issuer_id = issuer_id
        self._key_id = key_id
        self._private_key = _normalize_private_key(private_key)
        self._token: str | None = None
        self._expires_at: float = 0.0

    def token(self, force_refresh: bool = False) -> str:
        now = time.time()
        if force_refresh or self._token is None or now >= self._expires_at - JWT_REFRESH_MARGIN_SECONDS:
            self._token = self._mint(int(now))
            self._expires_at = now + JWT_LIFETIME_SECONDS
        return self._token

    def _mint(self, issued_at: int) -> str:
        payload: dict[str, Any] = {
            "iss": self._issuer_id,
            "iat": issued_at,
            "exp": issued_at + JWT_LIFETIME_SECONDS,
            "aud": JWT_AUDIENCE,
        }
        try:
            return jwt.encode(payload, self._private_key, algorithm="ES256", headers={"kid": self._key_id})
        except Exception as e:
            raise AppStoreConnectAuthError(
                "Could not sign a token with that private key. Paste the whole contents of the .p8 file "
                "you downloaded from App Store Connect, including the BEGIN and END lines."
            ) from e


def _make_session(private_key: str, capture: bool = True) -> requests.Session:
    # The private key itself is never sent — only the signature it produces — but redact it so a future
    # change can't leak it into a captured sample. Redirects stay off so a 3xx can't quietly forward a
    # bearer-token-bearing request to another host; `_get` treats any redirect as a failure.
    # `capture=False` keeps a session's responses out of HTTP sample capture, for calls whose bodies
    # carry values the name-based scrubbers can't recognise (the presigned analytics segment URLs).
    return make_tracked_session(redact_values=(private_key,), allow_redirects=False, capture=capture)


def _make_segment_download_session(presigned_query: str) -> requests.Session:
    # The presigned query string is a short-lived credential: redact it so the request log
    # line can't carry a usable signature, and keep the bulk report body out of sample capture.
    return make_tracked_session(
        redact_values=(presigned_query,) if presigned_query else (),
        allow_redirects=False,
        capture=False,
    )


def _get(
    session: requests.Session,
    url: str,
    *,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    params: dict[str, Any] | None = None,
    accept: str = "application/json",
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    tolerate: tuple[int, ...] = (),
) -> requests.Response:
    """GET with a freshly-valid token. 429 and transient 5xx are already retried by the tracked adapter."""

    # Pin the target to Apple's origin before attaching a token — covers freshly built URLs, `links.next`
    # cursors, and resume URLs alike, since every request funnels through here.
    _require_api_url(url)

    def _send(token: str) -> requests.Response:
        return session.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {token}", "Accept": accept},
            timeout=timeout,
        )

    response = _send(token_provider.token())
    if response.status_code == 401:
        # Tokens live 20 minutes and a long sync outlives one. Forcing a single re-mint separates a
        # merely stale token from a genuinely bad key, which stays a 401 and fails non-retryably.
        response = _send(token_provider.token(force_refresh=True))

    if 300 <= response.status_code < 400:
        # Redirects are pinned off on the session, so a 3xx is Apple's origin (or something posing as it)
        # trying to forward the request elsewhere. Fail closed rather than chase it with a live token.
        logger.error(f"App Store Connect unexpected redirect: status={response.status_code}, url={url}")
        raise AppStoreConnectUrlError(f"Unexpected redirect from App Store Connect: {url!r}")

    if response.status_code in tolerate:
        return response

    if response.status_code == 403:
        # A read the key's role can't perform. Carry Apple's own error into the message and a
        # structured log instead of asserting a role the key may already hold.
        apple_error = _parse_apple_error(response)
        logger.error(
            "App Store Connect read forbidden",
            url=url,
            apple_code=apple_error.code,
            apple_title=apple_error.title,
            apple_detail=apple_error.detail,
        )
        raise AppStoreConnectPermissionError(
            f"{APP_STORE_CONNECT_READ_FORBIDDEN_ERROR} ({_apple_error_suffix(apple_error, 403)})"
        )

    if not response.ok:
        logger.error(
            f"App Store Connect API error: status={response.status_code}, body={response.text[:500]}, url={url}"
        )
        response.raise_for_status()

    return response


def _flatten_resource(resource: dict[str, Any]) -> dict[str, Any]:
    """Lift a JSON:API resource's ``attributes`` to the row root alongside its ``id`` and ``type``.

    ``relationships`` is dropped: it holds link envelopes rather than data, and the related rows are
    already available as their own tables.
    """
    attributes = resource.get("attributes")
    row: dict[str, Any] = dict(attributes) if isinstance(attributes, dict) else {}
    row["id"] = resource.get("id")
    row["type"] = resource.get("type")
    return row


class _ParseFailureCounter:
    """Counts typed-column values that failed to parse and were stored as null.

    Null-on-unparseable is the deliberate failure policy for typed ingest: a malformed cell must
    never fail the whole sync, and keeping the raw string instead would flip the column's Arrow
    type between batches, which degrades the whole column back to text. Failures are logged as one
    warning per column on its first occurrence (with a truncated sample) plus one aggregate summary
    per run, never one line per value, so a systematically wrong file stays visible without
    flooding the logs. The typed columns hold only dates, counts, and prices, so a sample value
    can't carry personal data.
    """

    def __init__(self, logger: FilteringBoundLogger, endpoint: str) -> None:
        self._logger = logger
        self._endpoint = endpoint
        self.counts: dict[str, int] = {}

    def record(self, column: str, value: Any) -> None:
        self.counts[column] = self.counts.get(column, 0) + 1
        if self.counts[column] == 1:
            self._logger.warning(
                f"App Store Connect: unparseable value stored as null. "
                f"endpoint={self._endpoint}, column={column}, value={str(value)[:40]!r}. "
                f"Further failures in this column are counted and summarized when the run ends."
            )

    def flush(self) -> None:
        if not self.counts:
            return
        total = sum(self.counts.values())
        self._logger.warning(
            f"App Store Connect: {total} unparseable value(s) stored as null this run. "
            f"endpoint={self._endpoint}, failures_by_column={self.counts}"
        )


# Name-driven typing for the delimited report families (sales/subscription reports and the
# analytics report streams), whose files are text with no type information. Columns are typed by
# NAME wherever they appear rather than per endpoint: Apple varies each report's column set by
# report type and version, and publishes Standard/Detailed variants of the analytics reports, so a
# name-driven mapping covers a column in every stream that carries it, including variants added
# later. Names not listed stay text; identifier-like numeric columns (apple_identifier,
# app_apple_id, subscription_apple_id, ...) deliberately stay text because they are join keys, not
# quantities, as do the Detailed-only attribution columns (campaign, page_title, source_info).
_REPORT_DATE_COLUMNS = frozenset(
    {
        # Sales and subscription-event reports carry month-first MM/DD/YYYY dates.
        "begin_date",
        "end_date",
        "event_date",
        "original_start_date",
        # Analytics reports carry ISO YYYY-MM-DD dates.
        "date",
        "app_download_date",
        "pre_order_start_date",
        "pre_order_end_date",
    }
)
_REPORT_INTEGER_COLUMNS = frozenset(
    {
        # Sales/subscription reports. Units can be negative: Apple books refunds as negative units.
        "units",
        "quantity",
        "subscribers",
        "consecutive_paid_periods",
        "days_before_canceling",
        "days_canceled",
        # Analytics reports.
        "sessions",
        "unique_devices",
        "counts",
        "unique_counts",
        "crashes",
        "pre_orders_placed",
        "pre_orders_canceled",
    }
)
_REPORT_FLOAT_COLUMNS = frozenset(
    {
        # Monetary columns are amounts in the row's own currency column (customer_currency,
        # currency_of_proceeds/proceeds_currency); the numeric type makes them filterable and
        # summable WITHIN one currency, never across currencies.
        "customer_price",
        "developer_proceeds",
        "total_session_duration",
    }
)

_REPORT_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")


def _parse_report_date(text: str) -> date | None:
    # Apple documents sales-report dates as month-first MM/DD/YYYY for every report type (layouts
    # are fixed per report version, not localized per territory); analytics report files carry ISO
    # YYYY-MM-DD. Both formats use strictly numeric strptime directives, which never consult the
    # process locale, and a day-first reading is never attempted: a value like 13/01/2026 fails to
    # parse rather than being silently guessed as January 13.
    for fmt in _REPORT_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_report_int(text: str) -> int | None:
    # Commas only ever appear as US-style thousands separators in Apple's reports; the decimal
    # separator is always a point.
    digits = text.replace(",", "")
    try:
        return int(digits)
    except ValueError:
        pass
    try:
        number = float(digits)
    except ValueError:
        return None
    # A count that arrives as a whole-valued float ("3.0") still lands as an integer. A fractional
    # or non-finite value nulls rather than silently truncating, and 2**53 bounds the conversion to
    # where float holds integers exactly.
    return int(number) if math.isfinite(number) and number.is_integer() and abs(number) <= 2**53 else None


def _parse_report_float(text: str) -> float | None:
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return None
    # float() accepts "nan"/"inf", which no report legitimately contains.
    return number if math.isfinite(number) else None


def _parse_iso_datetime(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _typed_report_value(column: str, value: Any, failures: _ParseFailureCounter) -> Any:
    """Parse one delimited-report cell into its typed value, or null when it can't be parsed."""
    if not isinstance(value, str):
        return value
    if column in _REPORT_DATE_COLUMNS:
        parse: Callable[[str], Any] = _parse_report_date
    elif column in _REPORT_INTEGER_COLUMNS:
        parse = _parse_report_int
    elif column in _REPORT_FLOAT_COLUMNS:
        parse = _parse_report_float
    else:
        return value

    text = value.strip()
    if not text:
        # Blank cells are routine (an empty price on a free row, an unset offer duration); they
        # are nulls, not parse failures.
        return None
    parsed = parse(text)
    if parsed is None:
        failures.record(column, value)
    return parsed


def _typed_json_api_row(row: dict[str, Any], failures: _ParseFailureCounter) -> dict[str, Any]:
    """Convert a JSON:API row's ISO 8601 date-time attributes to UTC datetimes, in place.

    Apple's JSON:API resources carry every timestamp in an attribute named `...Date` (createdDate,
    uploadedDate, expirationDate, earliestReleaseDate, lastModifiedDate), so the rule is
    suffix-driven rather than a per-endpoint column list and covers attributes added later. Values
    normalize to UTC because Apple emits varying local offsets and one column must stay in one
    zone. Only table rows come through here; the resources the sync reads internally
    (analyticsReportInstances and friends) keep their raw strings.
    """
    for key, value in row.items():
        if not key.endswith("Date") or not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            row[key] = None
            continue
        parsed = _parse_iso_datetime(text)
        if parsed is None:
            failures.record(key, value)
        row[key] = parsed
    return row


@dataclasses.dataclass(frozen=True, kw_only=True)
class _Page:
    """One JSON:API page. ``resources`` and ``included`` share a type, so construction is
    keyword-only to keep a caller from silently swapping them."""

    resources: list[dict[str, Any]]
    included: list[dict[str, Any]]
    next_url: str | None


def _iter_pages(
    session: requests.Session,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    url: str,
    params: dict[str, Any] | None,
) -> Iterator[_Page]:
    """Walk a JSON:API collection, yielding each page's ``data`` and ``included`` resources plus the
    next-page URL (``None`` at the end).

    ``params is None`` means ``url`` is already a fully-formed ``links.next`` — re-sending params there
    would duplicate the limit and cursor query args.
    """
    page_params: dict[str, Any] | None = {**params, "limit": MAX_PAGE_SIZE} if params is not None else None
    pages = 0

    while True:
        body = _get(session, url, token_provider=token_provider, logger=logger, params=page_params).json()
        data = body.get("data") if isinstance(body, dict) else None
        included = body.get("included") if isinstance(body, dict) else None

        links = body.get("links") if isinstance(body, dict) else None
        next_url = links.get("next") if isinstance(links, dict) else None

        pages += 1
        if pages >= MAX_PAGES_PER_RESOURCE and next_url:
            logger.warning(f"App Store Connect: page cap reached, truncating collection. url={url}, pages={pages}")
            next_url = None

        yield _Page(
            resources=[resource for resource in (data or []) if isinstance(resource, dict)],
            included=[resource for resource in (included or []) if isinstance(resource, dict)],
            next_url=next_url,
        )

        if not next_url:
            return

        url = next_url
        page_params = None


def _page_rows(
    config: AppStoreConnectEndpointConfig, page: _Page, failures: _ParseFailureCounter
) -> list[dict[str, Any]]:
    """Rows for one page: the flattened ``data`` resources, or, for endpoints configured to read a
    related resource off another collection's pages, the flattened ``included`` resources of that type.
    """
    if config.rows_from_included_type is None:
        return [_typed_json_api_row(_flatten_resource(resource), failures) for resource in page.resources]

    # JSON:API full linkage guarantees every included resource is referenced from a primary
    # resource's relationship linkage; that linkage is where each row's parent id comes from.
    parent_ids: dict[str, str] = {}
    for resource in page.resources:
        relationships = resource.get("relationships")
        if not isinstance(relationships, dict) or resource.get("id") is None:
            continue
        for relationship in relationships.values():
            linkage = relationship.get("data") if isinstance(relationship, dict) else None
            if (
                isinstance(linkage, dict)
                and linkage.get("type") == config.rows_from_included_type
                and linkage.get("id") is not None
            ):
                parent_ids[str(linkage["id"])] = str(resource["id"])

    rows: list[dict[str, Any]] = []
    for resource in page.included:
        if resource.get("type") != config.rows_from_included_type:
            continue
        row = _flatten_resource(resource)
        row[config.included_parent_column] = parent_ids.get(str(resource.get("id")))
        rows.append(_typed_json_api_row(row, failures))
    return rows


def _load_resume(
    manager: ResumableSourceManager[AppStoreConnectResumeConfig],
) -> AppStoreConnectResumeConfig | None:
    return manager.load_state() if manager.can_resume() else None


def _list_app_ids(
    session: requests.Session,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
) -> list[str]:
    app_ids: list[str] = []
    for page in _iter_pages(session, token_provider, logger, f"{BASE_URL}/v1/apps", {}):
        app_ids.extend(str(resource["id"]) for resource in page.resources if resource.get("id"))
    return app_ids


def _get_collection(
    session: requests.Session,
    config: AppStoreConnectEndpointConfig,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppStoreConnectResumeConfig],
    failures: _ParseFailureCounter,
) -> Iterator[list[dict[str, Any]]]:
    resume = _load_resume(manager)
    resumed_url = resume.next_url if resume is not None else None

    url = resumed_url or f"{BASE_URL}{config.path}"
    params: dict[str, Any] | None = None if resumed_url else dict(config.params)

    for page in _iter_pages(session, token_provider, logger, url, params):
        rows = _page_rows(config, page, failures)
        if rows:
            yield rows
        # Save AFTER yielding so a crash re-fetches the page we just emitted rather than skipping it;
        # merge dedupes the re-pulled rows on the primary key.
        if page.next_url:
            manager.save_state(AppStoreConnectResumeConfig(next_url=page.next_url))


def _get_app_fanout(
    session: requests.Session,
    config: AppStoreConnectEndpointConfig,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppStoreConnectResumeConfig],
    failures: _ParseFailureCounter,
) -> Iterator[list[dict[str, Any]]]:
    app_ids = _list_app_ids(session, token_provider, logger)
    resume = _load_resume(manager)

    start = 0
    resumed_url: str | None = None
    if resume is not None and resume.app_id:
        index = next((i for i, app_id in enumerate(app_ids) if app_id == resume.app_id), None)
        # A bookmarked app that no longer exists restarts the fan-out; merge dedupes the re-pulled rows.
        if index is not None:
            start = index
            resumed_url = resume.next_url

    for position in range(start, len(app_ids)):
        app_id = app_ids[position]
        if position == start and resumed_url:
            url: str = resumed_url
            params: dict[str, Any] | None = None
        else:
            url = f"{BASE_URL}{config.path.format(app_id=app_id)}"
            params = dict(config.params)

        for page in _iter_pages(session, token_provider, logger, url, params):
            rows = _page_rows(config, page, failures)
            if rows:
                for row in rows:
                    row["app_id"] = app_id
                yield rows

            if page.next_url:
                manager.save_state(AppStoreConnectResumeConfig(app_id=app_id, next_url=page.next_url))
            elif position + 1 < len(app_ids):
                manager.save_state(AppStoreConnectResumeConfig(app_id=app_ids[position + 1]))


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _normalize_report_column(name: str) -> str:
    """Turn an Apple report header (``Developer Proceeds``) into a column name (``developer_proceeds``)."""
    slug = _NON_ALNUM.sub("_", name.strip().lower()).strip("_")
    return slug or "column"


def _decompress_report(payload: bytes) -> str:
    try:
        raw = gzip.decompress(payload)
    except (OSError, EOFError):
        # urllib3 already unwraps a `Content-Encoding: gzip` body, so the payload can arrive as plain TSV.
        raw = payload
    return raw.decode("utf-8-sig", errors="replace")


def _parse_report(payload: bytes, report_date: date, failures: _ParseFailureCounter) -> list[dict[str, Any]]:
    reader = csv.reader(io.StringIO(_decompress_report(payload)), delimiter="\t")
    try:
        header = next(reader)
    except StopIteration:
        return []

    columns = [_normalize_report_column(column) for column in header]
    rows: list[dict[str, Any]] = []

    for values in reader:
        if not any(value.strip() for value in values):
            continue
        row: dict[str, Any] = {
            column: _typed_report_value(column, values[index] if index < len(values) else None, failures)
            for index, column in enumerate(columns)
        }
        row["report_date"] = report_date
        # 1-based position in the file. A published day's report is immutable, so (report_date, _line)
        # is a stable unique key and re-reading a day merges instead of duplicating.
        row["_line"] = len(rows) + 1
        rows.append(row)

    return rows


def _fetch_report(
    session: requests.Session,
    config: AppStoreConnectEndpointConfig,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    vendor_number: str,
    report_date: date,
    failures: _ParseFailureCounter,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {
        "filter[frequency]": config.report_frequency,
        "filter[reportDate]": report_date.isoformat(),
        "filter[reportType]": config.report_type,
        "filter[reportSubType]": config.report_sub_type,
        "filter[vendorNumber]": vendor_number,
    }
    if config.report_version:
        params["filter[version]"] = config.report_version

    response = _get(
        session,
        f"{BASE_URL}/v1/salesReports",
        token_provider=token_provider,
        logger=logger,
        params=params,
        accept=REPORT_ACCEPT,
        timeout=REPORT_TIMEOUT_SECONDS,
        tolerate=config.missing_report_status_codes,
    )
    if response.status_code in config.missing_report_status_codes:
        # Apple 404s any date with no activity at all — normal for quiet days and for dates before the
        # app shipped — so a missing day is not an error. Subscription-family report types 400 for the
        # same condition instead (see `missing_report_status_codes`).
        return []

    return _parse_report(response.content, report_date, failures)


def _get_sales_report(
    session: requests.Session,
    config: AppStoreConnectEndpointConfig,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppStoreConnectResumeConfig],
    failures: _ParseFailureCounter,
    vendor_number: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    if not vendor_number:
        raise ValueError(APP_STORE_CONNECT_MISSING_VENDOR_NUMBER_ERROR)

    today = datetime.now(UTC).date()
    end = today - timedelta(days=SALES_REPORT_END_OFFSET_DAYS)
    start = today - timedelta(days=SALES_REPORT_LOOKBACK_DAYS)

    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            # Start on the watermark day itself rather than the day after: the file for a published day
            # never changes, so re-reading it merges idempotently and a half-written day self-heals.
            start = max(start, min(watermark, end))

    resume = _load_resume(manager)
    if resume is not None and resume.report_date:
        resumed = _to_date(resume.report_date)
        if resumed is not None and start <= resumed <= end:
            start = resumed

    report_date = start
    days_fetched = 0
    while report_date <= end and days_fetched < SALES_REPORT_MAX_DAYS_PER_RUN:
        rows = _fetch_report(session, config, token_provider, logger, vendor_number, report_date, failures)
        if rows:
            yield rows

        days_fetched += 1
        report_date += timedelta(days=1)
        if report_date <= end:
            manager.save_state(AppStoreConnectResumeConfig(report_date=report_date.isoformat()))

    if report_date <= end:
        logger.info(
            f"App Store Connect: hit the per-run report day cap, resuming later. "
            f"endpoint={config.name}, next_report_date={report_date.isoformat()}"
        )


def _require_segment_url(url: str) -> str:
    """Allow only https URLs on Apple's storage hosts for analytics segment downloads."""
    try:
        parts = urlsplit(url)
    except Exception as e:
        raise AppStoreConnectUrlError(f"Unparseable analytics segment URL: {url!r}") from e

    hostname = parts.hostname or ""
    if parts.scheme != "https" or not hostname.endswith(ANALYTICS_SEGMENT_HOST_SUFFIXES):
        raise AppStoreConnectUrlError(f"Refusing to download an analytics segment from: {url!r}")
    return url


def _post_json(
    session: requests.Session,
    url: str,
    *,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    payload: dict[str, Any],
    tolerate: tuple[int, ...] = (),
) -> requests.Response:
    _require_api_url(url)

    def _send(token: str) -> requests.Response:
        return session.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    response = _send(token_provider.token())
    if response.status_code == 401:
        response = _send(token_provider.token(force_refresh=True))

    if 300 <= response.status_code < 400:
        logger.error(f"App Store Connect unexpected redirect: status={response.status_code}, url={url}")
        raise AppStoreConnectUrlError(f"Unexpected redirect from App Store Connect: {url!r}")

    if response.status_code in tolerate:
        return response

    if not response.ok:
        logger.error(
            f"App Store Connect API error: status={response.status_code}, body={response.text[:500]}, url={url}"
        )
        response.raise_for_status()

    return response


def _ensure_report_request(
    session: requests.Session,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    app_id: str,
) -> tuple[str | None, bool]:
    """Reuse the app's active ONGOING analytics report request, creating one only if none exists.

    Returns ``(request_id, created_now)``. Creating a request is the only call in this source that
    mutates the customer's App Store Connect account, so it has to be idempotent: an existing active
    request is always reused, and a request Apple stopped due to inactivity no longer generates
    reports, so it doesn't count as active. Apple rejects a duplicate create with a 409, which
    resolves by re-reading the list.
    """
    list_url = f"{BASE_URL}/v1/apps/{app_id}/analyticsReportRequests"

    def _active_request_id() -> tuple[str | None, bool]:
        """Returns ``(active_request_id, saw_stopped)`` — the active request to reuse, and whether an
        ONGOING request stopped due to inactivity was skipped, so the create 403 can name that cause."""
        body = _get(
            session,
            list_url,
            token_provider=token_provider,
            logger=logger,
            params={"filter[accessType]": "ONGOING", "limit": MAX_PAGE_SIZE},
        ).json()
        data = body.get("data") if isinstance(body, dict) else None
        saw_stopped = False
        for resource in data or []:
            if not isinstance(resource, dict) or not resource.get("id"):
                continue
            attributes = resource.get("attributes")
            if isinstance(attributes, dict) and attributes.get("stoppedDueToInactivity"):
                saw_stopped = True
                continue
            return str(resource["id"]), saw_stopped
        return None, saw_stopped

    existing, saw_stopped = _active_request_id()
    if existing:
        return existing, False

    payload = {
        "data": {
            "type": "analyticsReportRequests",
            "attributes": {"accessType": "ONGOING"},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
        }
    }
    response = _post_json(
        session,
        f"{BASE_URL}/v1/analyticsReportRequests",
        token_provider=token_provider,
        logger=logger,
        payload=payload,
        tolerate=(403, 409),
    )
    if response.status_code == 403:
        # Apple gates this create on Admin, but a Sales or Finance key reads reports fine, so a bare
        # read-role message would name a role the key already holds. Tell the operator the create
        # needs Admin, and say when the trigger was an inactivity-stopped request instead.
        apple_error = _parse_apple_error(response)
        logger.error(
            "App Store Connect analytics report request create forbidden",
            app_id=app_id,
            stopped_due_to_inactivity=saw_stopped,
            apple_code=apple_error.code,
            apple_title=apple_error.title,
            apple_detail=apple_error.detail,
        )
        message = (
            APP_STORE_CONNECT_ANALYTICS_INACTIVE_ERROR
            if saw_stopped
            else APP_STORE_CONNECT_ANALYTICS_CREATE_FORBIDDEN_ERROR
        )
        raise AppStoreConnectPermissionError(f"{message} ({_apple_error_suffix(apple_error, 403)})")
    if response.status_code == 409:
        # A concurrent sync (or a request the accessType filter hid) beat us to it.
        return _active_request_id()[0], False

    body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    request_id = data.get("id") if isinstance(data, dict) else None
    return (str(request_id) if request_id else None), True


def _normalize_report_name(name: str) -> str:
    # Apple's report names drift in case, spacing, and hyphenation ("Pre-Orders" vs "Pre-orders").
    # Match on alphanumerics only, so a cosmetic rename cannot silently blank a stream.
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _find_analytics_report(
    session: requests.Session,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    config: AppStoreConnectEndpointConfig,
    request_id: str,
) -> str | None:
    url = f"{BASE_URL}/v1/analyticsReportRequests/{request_id}/reports"
    report_ids: dict[str, str] = {}
    for page in _iter_pages(
        session, token_provider, logger, url, {"filter[category]": config.analytics_report_category}
    ):
        for resource in page.resources:
            row = _flatten_resource(resource)
            if row.get("name") and row.get("id"):
                report_ids[str(row["name"])] = str(row["id"])

    by_normalized = {_normalize_report_name(name): report_id for name, report_id in report_ids.items()}
    for name in config.analytics_report_names:
        report_id = by_normalized.get(_normalize_report_name(name))
        if report_id is not None:
            return report_id

    logger.warning(
        f"App Store Connect: no report named {config.analytics_report_names} under this request "
        f"(endpoint={config.name}, available={sorted(report_ids)}). The account may not be entitled "
        f"to this report, Apple may have renamed it, or the first reports may still be generating."
    )
    return None


def _analytics_instances(
    session: requests.Session,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    report_id: str,
    lower_bound: date | None,
) -> list[tuple[str, date]]:
    url = f"{BASE_URL}/v1/analyticsReports/{report_id}/instances"
    instances: list[tuple[str, date]] = []
    for page in _iter_pages(session, token_provider, logger, url, {"filter[granularity]": ANALYTICS_GRANULARITY}):
        for resource in page.resources:
            row = _flatten_resource(resource)
            processing_date = _to_date(row.get("processingDate"))
            if not row.get("id") or processing_date is None:
                continue
            # The lower bound is inclusive: an instance's rows can restate earlier data
            # dates, and re-reading the boundary merges idempotently on the primary key.
            if lower_bound is not None and processing_date < lower_bound:
                continue
            instances.append((str(row["id"]), processing_date))
    instances.sort(key=lambda instance: instance[1])
    return instances


def _analytics_segments(
    session: requests.Session,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    instance_id: str,
) -> list[dict[str, Any]]:
    url = f"{BASE_URL}/v1/analyticsReportInstances/{instance_id}/segments"
    segments: list[dict[str, Any]] = []
    for page in _iter_pages(session, token_provider, logger, url, {}):
        segments.extend(row for row in (_flatten_resource(resource) for resource in page.resources) if row.get("url"))
    # Row keys carry the line's position within the instance, so segment order has to be
    # deterministic across re-reads or the same key would name a different row each time.
    segments.sort(key=lambda segment: str(segment.get("id")))
    return segments


def _download_segment(logger: FilteringBoundLogger, segment: dict[str, Any]) -> IO[bytes]:
    """Download one segment to a spooled file, hashing as it streams.

    The URL is presigned, so no Authorization header is attached: sending the Apple bearer token to
    the storage host would hand it to a third party. The checksum's algorithm is undocumented (the
    value is shaped like an MD5), so a mismatch is logged rather than fatal; failing hard on a wrong
    algorithm guess would brick the table, and gzip's own CRC still rejects corrupted payloads at
    decompression time.
    """
    url = _require_segment_url(str(segment["url"]))
    spool = tempfile.SpooledTemporaryFile(max_size=ANALYTICS_SEGMENT_SPOOL_BYTES)
    # Download-integrity check against Apple's checksum, not a cryptographic use; corrupted
    # payloads are also rejected by the gzip CRC.
    digest = hashlib.md5(usedforsecurity=False)  # nosemgrep

    session = _make_segment_download_session(urlsplit(url).query)
    response = session.get(url, stream=True, timeout=REPORT_TIMEOUT_SECONDS)
    try:
        if not response.ok:
            logger.error(f"App Store Connect analytics segment download failed: status={response.status_code}")
            response.raise_for_status()
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            digest.update(chunk)
            spool.write(chunk)
    finally:
        response.close()

    expected = segment.get("checksum")
    if expected and digest.hexdigest() != expected:
        logger.warning(
            f"App Store Connect: analytics segment checksum mismatch "
            f"(expected={expected}, got={digest.hexdigest()}, sizeInBytes={segment.get('sizeInBytes')}). "
            f"Continuing; the gzip CRC rejects genuinely corrupt payloads."
        )

    spool.seek(0)
    return spool


def _open_segment_text(spool: IO[bytes]) -> IO[str]:
    # The transport can hand the payload over decompressed (a `Content-Encoding: gzip` body is
    # unwrapped by urllib3), so sniff the magic bytes instead of assuming.
    magic = spool.read(2)
    spool.seek(0)
    if magic == b"\x1f\x8b":
        return io.TextIOWrapper(gzip.GzipFile(fileobj=spool, mode="rb"), encoding="utf-8-sig", errors="replace")
    return io.TextIOWrapper(spool, encoding="utf-8-sig", errors="replace")


def _iter_segment_rows(
    text: IO[str], processing_date: date, line_start: int, failures: _ParseFailureCounter
) -> Iterator[dict[str, Any]]:
    header_line = text.readline()
    if not header_line.strip():
        return

    # Apple's segment objects are named `.csv.gz` but its docs describe the files only as
    # delimited text, so sniff the delimiter from the header instead of assuming one.
    delimiter = "\t" if "\t" in header_line else ","
    columns = [_normalize_report_column(column) for column in next(csv.reader([header_line], delimiter=delimiter))]
    line = line_start

    for values in csv.reader(text, delimiter=delimiter):
        if not any(value.strip() for value in values):
            continue
        row: dict[str, Any] = {
            column: _typed_report_value(column, values[index] if index < len(values) else None, failures)
            for index, column in enumerate(columns)
        }
        row["processing_date"] = processing_date
        # 1-based position within the instance, continuing across its segments. A published
        # instance is immutable, so (app_id, processing_date, _line) stays a stable unique key
        # and re-reading an instance merges instead of duplicating.
        line += 1
        row["_line"] = line
        yield row


def _get_analytics_report(
    session: requests.Session,
    segments_session: requests.Session,
    config: AppStoreConnectEndpointConfig,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppStoreConnectResumeConfig],
    failures: _ParseFailureCounter,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    app_ids = _list_app_ids(session, token_provider, logger)
    resume = _load_resume(manager)
    resumed_date = _to_date(resume.processing_date) if resume is not None else None
    watermark = _to_date(db_incremental_field_last_value) if should_use_incremental_field else None

    lower_bound: date | None = None
    for candidate in (watermark, resumed_date):
        if candidate is not None and (lower_bound is None or candidate > lower_bound):
            lower_bound = candidate

    # Discover every app's report and instances up front, then walk processing dates in
    # ascending order ACROSS apps. Yields are then globally date-ordered, so the pipeline's
    # per-batch watermark checkpoint can never advance past an app whose older instances are
    # still unfetched, and the walk can stop cleanly at the first gap or at the per-run cap:
    # the watermark stands at the last date reached, and because the lower bound is inclusive
    # the next run re-reads that boundary date in full and the merge dedupes it. Resume state
    # is job-scoped (it survives retries of the same job, never the next scheduled run), so
    # the watermark has to carry cross-run progress by itself.
    instances_by_date: dict[date, list[tuple[str, str]]] = {}
    for app_id in app_ids:
        request_id, created_now = _ensure_report_request(session, token_provider, logger, app_id)
        if created_now:
            logger.info(
                f"App Store Connect: created an ONGOING analytics report request for app {app_id}; "
                f"Apple generates the first reports in 1-2 days. endpoint={config.name}"
            )
            continue
        if request_id is None:
            continue

        report_id = _find_analytics_report(session, token_provider, logger, config, request_id)
        if report_id is None:
            # An unavailable report degrades this table for this app; other apps and tables
            # are unaffected.
            continue

        for instance_id, processing_date in _analytics_instances(
            session, token_provider, logger, report_id, lower_bound
        ):
            instances_by_date.setdefault(processing_date, []).append((app_id, instance_id))

    instances_fetched = 0
    for processing_date in sorted(instances_by_date):
        for app_id, instance_id in instances_by_date[processing_date]:
            if instances_fetched >= ANALYTICS_MAX_INSTANCES_PER_RUN:
                # An incremental sync continues from the watermark next run. A full refresh
                # has no watermark to continue from, so a cap-hit there means a truncated
                # table until the backlog fits in one run.
                logger.warning(
                    f"App Store Connect: hit the per-run analytics instance cap at "
                    f"{processing_date.isoformat()}; later dates are left for the next "
                    f"incremental run. endpoint={config.name}"
                )
                manager.save_state(AppStoreConnectResumeConfig(processing_date=processing_date.isoformat()))
                return

            segments = _analytics_segments(segments_session, token_provider, logger, instance_id)
            if not segments:
                # The instance is listed but its files aren't ready. Stop the whole walk at
                # this date so no newer date is emitted past the gap: the watermark then
                # stays at or below this date, and the next run re-reads it once the files
                # exist.
                logger.info(
                    f"App Store Connect: analytics instance has no segments yet, stopping the "
                    f"walk at this date. endpoint={config.name}, app_id={app_id}, "
                    f"processing_date={processing_date.isoformat()}"
                )
                manager.save_state(AppStoreConnectResumeConfig(processing_date=processing_date.isoformat()))
                return

            line = 0
            batch: list[dict[str, Any]] = []
            for segment in segments:
                spool = _download_segment(logger, segment)
                try:
                    with _open_segment_text(spool) as text:
                        for row in _iter_segment_rows(text, processing_date, line, failures):
                            row["app_id"] = app_id
                            line = row["_line"]
                            batch.append(row)
                            if len(batch) >= ANALYTICS_ROWS_PER_BATCH:
                                yield batch
                                batch = []
                finally:
                    spool.close()
            if batch:
                yield batch

            instances_fetched += 1

        # The date is complete for every app, so a retried attempt of this job can start at
        # the next one. Saved AFTER the date's rows are yielded, so a crash re-reads the
        # date rather than skipping it; the merge dedupes the re-read.
        manager.save_state(
            AppStoreConnectResumeConfig(processing_date=(processing_date + timedelta(days=1)).isoformat())
        )


def check_credentials(issuer_id: str, key_id: str, private_key: str) -> tuple[int | None, str | None]:
    """Probe ``/v1/apps`` with a minted token.

    Returns ``(http_status, message)``. The status is ``None`` when the request never left the process
    (a key we can't sign with, or a network failure), in which case ``message`` explains why when we know.
    """
    try:
        token_provider = AppStoreConnectTokenProvider(issuer_id, key_id, private_key)
        token = token_provider.token()
    except AppStoreConnectAuthError as e:
        return None, str(e)

    try:
        response = _make_session(private_key).get(
            f"{BASE_URL}/v1/apps",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=CREDENTIALS_TIMEOUT_SECONDS,
        )
        return response.status_code, None
    except Exception:
        return None, None


def get_rows(
    issuer_id: str,
    key_id: str,
    private_key: str,
    vendor_number: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppStoreConnectResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APP_STORE_CONNECT_ENDPOINTS[endpoint]
    session = _make_session(private_key)
    token_provider = AppStoreConnectTokenProvider(issuer_id, key_id, private_key)
    failures = _ParseFailureCounter(logger, endpoint)

    try:
        if config.kind == "collection":
            yield from _get_collection(session, config, token_provider, logger, resumable_source_manager, failures)
        elif config.kind == "app_fanout":
            yield from _get_app_fanout(session, config, token_provider, logger, resumable_source_manager, failures)
        elif config.kind == "analytics_report":
            yield from _get_analytics_report(
                session,
                # Segment listings ride a capture-disabled session: their bodies carry presigned
                # URLs whose query strings are short-lived credentials the name-based scrubbers
                # can't recognise.
                _make_session(private_key, capture=False),
                config,
                token_provider,
                logger,
                resumable_source_manager,
                failures,
                should_use_incremental_field,
                db_incremental_field_last_value,
            )
        else:  # "sales_report"
            yield from _get_sales_report(
                session,
                config,
                token_provider,
                logger,
                resumable_source_manager,
                failures,
                vendor_number,
                should_use_incremental_field,
                db_incremental_field_last_value,
            )
    finally:
        # The unparseable-value summary rides the generator's teardown so it also surfaces for a
        # run that fails or is abandoned mid-walk.
        failures.flush()

    # Walked to completion, so drop the checkpoint — leaving it would let a later attempt on this job
    # resume mid-stream instead of restarting cleanly.
    resumable_source_manager.clear_state()


def app_store_connect_source(
    issuer_id: str,
    key_id: str,
    private_key: str,
    vendor_number: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppStoreConnectResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = APP_STORE_CONNECT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            issuer_id=issuer_id,
            key_id=key_id,
            private_key=private_key,
            vendor_number=vendor_number,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Report streams walk dates oldest-first (analytics streams date-major across apps, so
        # per-batch watermark checkpoints stay safe despite the fan-out), and collections are
        # full refreshes merged on a unique key, so asc fits everything.
        sort_mode="asc",
    )
