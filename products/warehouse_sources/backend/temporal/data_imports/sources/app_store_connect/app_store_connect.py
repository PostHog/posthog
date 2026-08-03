import io
import re
import csv
import gzip
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlsplit

import jwt
import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.settings import (
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

_PEM_HEADER = "-----BEGIN PRIVATE KEY-----"
_PEM_FOOTER = "-----END PRIVATE KEY-----"
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


class AppStoreConnectAuthError(Exception):
    """The .p8 private key, key ID, or issuer ID can't produce a signed token."""


class AppStoreConnectUrlError(Exception):
    """A request or pagination URL points somewhere other than the App Store Connect API origin."""


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


def _make_session(private_key: str) -> requests.Session:
    # The private key itself is never sent — only the signature it produces — but redact it so a future
    # change can't leak it into a captured sample. Redirects stay off so a 3xx can't quietly forward a
    # bearer-token-bearing request to another host; `_get` treats any redirect as a failure.
    return make_tracked_session(redact_values=(private_key,), allow_redirects=False)


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


def _iter_pages(
    session: requests.Session,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    url: str,
    params: dict[str, Any] | None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Walk a JSON:API collection, yielding each page's rows plus the next-page URL (``None`` at the end).

    ``params is None`` means ``url`` is already a fully-formed ``links.next`` — re-sending params there
    would duplicate the limit and cursor query args.
    """
    page_params: dict[str, Any] | None = {**params, "limit": MAX_PAGE_SIZE} if params is not None else None
    pages = 0

    while True:
        body = _get(session, url, token_provider=token_provider, logger=logger, params=page_params).json()
        data = body.get("data") if isinstance(body, dict) else None
        rows = [_flatten_resource(resource) for resource in (data or []) if isinstance(resource, dict)]

        links = body.get("links") if isinstance(body, dict) else None
        next_url = links.get("next") if isinstance(links, dict) else None

        pages += 1
        if pages >= MAX_PAGES_PER_RESOURCE and next_url:
            logger.warning(f"App Store Connect: page cap reached, truncating collection. url={url}, pages={pages}")
            next_url = None

        yield rows, next_url

        if not next_url:
            return

        url = next_url
        page_params = None


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
    for rows, _ in _iter_pages(session, token_provider, logger, f"{BASE_URL}/v1/apps", {}):
        app_ids.extend(str(row["id"]) for row in rows if row.get("id"))
    return app_ids


def _get_collection(
    session: requests.Session,
    config: AppStoreConnectEndpointConfig,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppStoreConnectResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = _load_resume(manager)
    resumed_url = resume.next_url if resume is not None else None

    url = resumed_url or f"{BASE_URL}{config.path}"
    params: dict[str, Any] | None = None if resumed_url else dict(config.params)

    for rows, next_url in _iter_pages(session, token_provider, logger, url, params):
        if rows:
            yield rows
        # Save AFTER yielding so a crash re-fetches the page we just emitted rather than skipping it;
        # merge dedupes the re-pulled rows on the primary key.
        if next_url:
            manager.save_state(AppStoreConnectResumeConfig(next_url=next_url))


def _get_app_fanout(
    session: requests.Session,
    config: AppStoreConnectEndpointConfig,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppStoreConnectResumeConfig],
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

        for rows, next_url in _iter_pages(session, token_provider, logger, url, params):
            if rows:
                for row in rows:
                    row["app_id"] = app_id
                yield rows

            if next_url:
                manager.save_state(AppStoreConnectResumeConfig(app_id=app_id, next_url=next_url))
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


def _parse_report(payload: bytes, report_date: date) -> list[dict[str, Any]]:
    reader = csv.reader(io.StringIO(_decompress_report(payload)), delimiter="\t")
    try:
        header = next(reader)
    except StopIteration:
        return []

    columns = [_normalize_report_column(column) for column in header]
    report_date_str = report_date.isoformat()
    rows: list[dict[str, Any]] = []

    for values in reader:
        if not any(value.strip() for value in values):
            continue
        row: dict[str, Any] = {
            column: (values[index] if index < len(values) else None) for index, column in enumerate(columns)
        }
        row["report_date"] = report_date_str
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

    return _parse_report(response.content, report_date)


def _get_sales_report(
    session: requests.Session,
    config: AppStoreConnectEndpointConfig,
    token_provider: AppStoreConnectTokenProvider,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppStoreConnectResumeConfig],
    vendor_number: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    if not vendor_number:
        raise ValueError(
            "Syncing App Store Connect sales reports needs your vendor number. "
            "Add it in the source settings, then run the sync again."
        )

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
        rows = _fetch_report(session, config, token_provider, logger, vendor_number, report_date)
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

    if config.kind == "collection":
        yield from _get_collection(session, config, token_provider, logger, resumable_source_manager)
    elif config.kind == "app_fanout":
        yield from _get_app_fanout(session, config, token_provider, logger, resumable_source_manager)
    else:  # "sales_report"
        yield from _get_sales_report(
            session,
            config,
            token_provider,
            logger,
            resumable_source_manager,
            vendor_number,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

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
        # Report streams walk dates oldest-first. Collections are full refreshes merged on a unique key,
        # so their page order doesn't affect the result either way.
        sort_mode="asc",
    )
