import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.settings import ADJUST_REPORTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

ADJUST_API_HOST = "automate.adjust.com"
BASE_URL = f"https://{ADJUST_API_HOST}/reports-service"
REPORT_URL = f"{BASE_URL}/report"

# Reports are pulled one date window at a time so a long backfill streams instead of asking Adjust
# for years of rows in a single response. The window is also the resume unit.
WINDOW_DAYS = 30
# First sync backfill depth. Adjust does not retain report data indefinitely, so anything older
# than this is unlikely to be available anyway.
MAX_HISTORY_DAYS = 730
# Adjust keeps revising recent days (late attributions, re-attributions), so an incremental run
# re-reads a trailing window; merge dedupes on the dimension key.
LOOKBACK_DAYS = 3
REQUEST_TIMEOUT_SECONDS = 300
# The Report Service API documents a `pagination` field but not its mechanism, so the page loop is
# driven purely by a next link when one is present. The cap stops a malformed/looping link from
# scanning forever.
MAX_PAGES_PER_WINDOW = 200
# Adjust app tokens are short alphanumeric identifiers; reject anything else before it reaches a
# query string.
_APP_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class AdjustRetryableError(Exception):
    """Transient upstream failure (429 / 5xx) that survived the tracked session's own retries."""

    pass


class AdjustCredentialsError(Exception):
    """A credential check failed for a reason we can explain to the user (bad token, bad app token)."""

    pass


@dataclasses.dataclass
class AdjustResumeConfig:
    # ISO date (YYYY-MM-DD) of the next date window to request. Lets a multi-window backfill pick up
    # where it stopped after a heartbeat timeout instead of re-walking the whole history.
    next_start_date: str | None = None


def _today() -> date:
    return datetime.now(UTC).date()


def _get_session(api_token: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        redact_values=(api_token,),
        # The Bearer token rides in every request's default headers, so pin the session off
        # redirects — an upstream redirect must not carry the credential to another host.
        allow_redirects=False,
    )


def parse_app_tokens(app_tokens: str | None) -> list[str]:
    """Split the optional comma-separated app token filter, rejecting anything malformed.

    Raises ``AdjustCredentialsError`` rather than silently dropping a bad entry — a typo'd token
    would otherwise quietly narrow (or widen) the report to the wrong set of apps.
    """
    if not app_tokens:
        return []
    tokens = [token.strip() for token in app_tokens.split(",")]
    tokens = [token for token in tokens if token]
    for token in tokens:
        if not _APP_TOKEN_RE.fullmatch(token):
            raise AdjustCredentialsError(
                f"'{token}' does not look like an Adjust app token. App tokens are the short "
                "alphanumeric identifiers shown under your app's settings in the Adjust dashboard."
            )
    return tokens


def build_report_params(
    report: str,
    start: date,
    end: date,
    app_tokens: list[str],
) -> dict[str, str]:
    config = ADJUST_REPORTS[report]
    params = {
        "dimensions": ",".join(config.dimensions),
        "metrics": ",".join(config.metrics),
        "date_period": f"{start.isoformat()}:{end.isoformat()}",
        # Ascending by day so the rows arrive in the order `sort_mode="asc"` promises and the
        # incremental watermark only ever moves forward.
        "sort": "day",
    }
    if app_tokens:
        params["app_token__in"] = ",".join(app_tokens)
    return params


def _error_message(response: requests.Response) -> str:
    """Best-effort human-readable detail from an Adjust error body."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or error.get("detail")
    else:
        detail = error
    detail = detail or body.get("message") or body.get("detail")
    return f" — {detail}" if isinstance(detail, str) and detail else ""


def _request(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise AdjustRetryableError(f"Adjust API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Adjust API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        # The API token rides in the Authorization header, so the URL is safe to embed — it lets
        # `get_non_retryable_errors()` match on the stable host prefix.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {url}{_error_message(response)}",
            response=response,
        )

    body = response.json()
    if not isinstance(body, dict):
        raise ValueError(f"Adjust returned an unexpected report payload of type {type(body).__name__}")
    return body


def extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the report rows out of a Report Service response.

    Adjust returns them under `rows`; tolerate a `data` list too, since the CSV/pivot variants of
    the same endpoint have historically wrapped rows differently.
    """
    for key in ("rows", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def next_page_url(payload: dict[str, Any]) -> str | None:
    """Return the absolute next-page URL, if the response advertises one.

    The `pagination` field is present but undocumented, so only an explicit link is followed —
    anything else terminates the page loop rather than guessing an offset scheme. The link is
    pinned to HTTPS on the Adjust API host: `_request` fetches it with the session whose default
    headers carry the customer's Bearer token, so a tampered upstream `next` must not be able to
    point the credentialed request at an attacker-controlled or internal host.
    """
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict):
        return None
    candidate = pagination.get("next") or pagination.get("next_url")
    if not isinstance(candidate, str) or not candidate:
        return None
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.hostname != ADJUST_API_HOST:
        return None
    return candidate


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19].replace("Z", "")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def resolve_start_date(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    today: date,
) -> date:
    earliest = today - timedelta(days=MAX_HISTORY_DAYS)
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            return min(max(watermark - timedelta(days=LOOKBACK_DAYS), earliest), today)
    return earliest


def date_windows(start: date, end: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Split [start, end] into consecutive inclusive windows of at most `window_days` days."""
    if start > end:
        return []
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=window_days - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def validate_credentials(api_token: str, app_tokens: str | None = None) -> bool:
    """Confirm the API token (and any app token filter) works with a one-day report probe.

    Returns ``True`` on success. Raises ``AdjustCredentialsError`` with a user-facing message when
    Adjust rejects the token, the app tokens, or the request, ``AdjustRetryableError`` on
    rate-limit / 5xx responses, and lets transport errors propagate so a transient failure isn't
    mislabelled as a bad credential. Never returns ``False``.
    """
    tokens = parse_app_tokens(app_tokens)
    today = _today()
    params = {
        "dimensions": "day",
        "metrics": "installs",
        "date_period": f"{today.isoformat()}:{today.isoformat()}",
    }
    if tokens:
        params["app_token__in"] = ",".join(tokens)

    response = _get_session(api_token).get(f"{REPORT_URL}?{urlencode(params)}", timeout=30)

    if response.status_code == 429 or response.status_code >= 500:
        raise AdjustRetryableError(f"Adjust API error (retryable): status={response.status_code}")
    if response.status_code == 200:
        return True
    if response.status_code == 401:
        raise AdjustCredentialsError(
            "Adjust rejected the API token. Check that you pasted a valid Adjust API token from "
            "your account settings in the Adjust dashboard."
        )
    if response.status_code == 403:
        raise AdjustCredentialsError(
            "Adjust denied access. Check that your user has reporting access to the apps you want "
            "to import and that your account includes the Report Service API."
        )
    if response.status_code in (400, 404, 422):
        raise AdjustCredentialsError(
            f"Adjust rejected the report request (HTTP {response.status_code})"
            f"{_error_message(response)}. If you set app tokens, check they belong to this account."
        )
    raise AdjustCredentialsError(
        f"Adjust returned an unexpected response (HTTP {response.status_code}) while validating "
        "credentials. If your API token looks correct, please try again shortly."
    )


def get_rows(
    api_token: str,
    app_tokens: str | None,
    report: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdjustResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    if report not in ADJUST_REPORTS:
        raise ValueError(f"Unknown Adjust report: {report}")

    tokens = parse_app_tokens(app_tokens)
    session = _get_session(api_token)
    today = _today()
    start = resolve_start_date(should_use_incremental_field, db_incremental_field_last_value, today)
    windows = date_windows(start, today)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_start_date:
        windows = [window for window in windows if window[0].isoformat() >= resume.next_start_date]
        logger.debug(f"Adjust: resuming {report} from {resume.next_start_date}")

    # The tracked session already retries 429 + transient 5xx honoring `Retry-After`, so there is
    # deliberately no second retry layer here — anything that reaches us has already been retried,
    # and the Temporal activity retries the job.
    for index, (window_start, window_end) in enumerate(windows):
        url = f"{REPORT_URL}?{urlencode(build_report_params(report, window_start, window_end, tokens))}"
        for page in range(MAX_PAGES_PER_WINDOW):
            payload = _request(session, url, logger)
            rows = extract_rows(payload)
            if rows:
                yield rows

            next_url = next_page_url(payload)
            if next_url is None:
                break
            if page + 1 == MAX_PAGES_PER_WINDOW:
                logger.warning(
                    "Adjust page cap reached; truncating window",
                    report=report,
                    date_period=f"{window_start.isoformat()}:{window_end.isoformat()}",
                    pages=MAX_PAGES_PER_WINDOW,
                )
                break
            url = next_url

        # Save AFTER yielding the window so a crash re-yields it rather than skipping it (merge
        # dedupes on the dimension key).
        if index + 1 < len(windows):
            resumable_source_manager.save_state(AdjustResumeConfig(next_start_date=windows[index + 1][0].isoformat()))


def adjust_source(
    api_token: str,
    app_tokens: str | None,
    report: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdjustResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = ADJUST_REPORTS[report]

    return SourceResponse(
        name=report,
        items=lambda: get_rows(
            api_token=api_token,
            app_tokens=app_tokens,
            report=report,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["day"],
        sort_mode="asc",
        # Aggregated dimension keys can collide when a dimension value comes back blank (e.g.
        # organic traffic with no campaign) — an expected trait of report data, not a data-quality
        # problem the user can fix. Don't set has_duplicate_primary_keys: that flag tells
        # validate_incremental_sync to block incremental syncing altogether, which would make
        # `day` (the only incremental field this source offers) permanently unusable. The merge's
        # own per-batch dedup (keep-last-per-key) already resolves the collision safely.
    )
