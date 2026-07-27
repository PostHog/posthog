import io
import re
import csv
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.settings import APPSFLYER_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

APPSFLYER_BASE_URL = "https://hq1.appsflyer.com"
# Aggregate pull requests cap the date range at ~1000 days.
MAX_WINDOW_DAYS = 999
# AppsFlyer doesn't finalize data until ~48h after the UTC day; re-fetch the
# trailing days each incremental run (merge dedupes on the dimension key).
LOOKBACK_DAYS = 2
REQUEST_TIMEOUT_SECONDS = 300
MAX_RETRY_ATTEMPTS = 5
# Yield rows in chunks so huge reports don't build one giant list.
CHUNK_SIZE = 5000


class AppsFlyerRetryableError(Exception):
    pass


class AppsFlyerCredentialsError(Exception):
    """A credential check failed for a reason we can explain to the user (bad token, bad app id)."""

    pass


def _get_session(api_token: str) -> requests.Session:
    # the v5 docs are a bit ambiguous about whether the return format defaults to CSV
    # or JSON, so we explicitly request CSV for safety.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}", "Accept": "text/csv"},
        redact_values=(api_token,),
    )


def _validate_app_id(app_id: str) -> str:
    app_id = app_id.strip()
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", app_id):
        raise ValueError(f"Invalid AppsFlyer app id: {app_id}")
    return app_id


def _normalize_header(header: str) -> str:
    """CSV headers like 'Media Source (pid)' become stable snake_case columns."""
    return re.sub(r"[^0-9a-zA-Z]+", "_", header).strip("_").lower()


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_csv_rows(text: str, logger: FilteringBoundLogger | None = None) -> Iterator[dict[str, Any]]:
    reader = csv.reader(io.StringIO(text))
    headers: list[str] | None = None
    for row in reader:
        if headers is None:
            headers = [_normalize_header(header) for header in row]
            continue
        if not any(cell.strip() for cell in row):
            continue
        # zip would silently truncate a short row, leaving primary-key columns absent and
        # corrupting dedupe — drop the malformed row instead so the failure is explicit.
        if len(row) != len(headers):
            if logger is not None:
                logger.warning(
                    "AppsFlyer CSV row length mismatch; skipping row",
                    expected=len(headers),
                    got=len(row),
                )
            continue
        yield dict(zip(headers, row))


def validate_credentials(api_token: str, app_id: str) -> bool:
    """Confirm the token and app id are valid with a one-day report probe.

    Returns ``True`` when the probe succeeds. Raises ``AppsFlyerCredentialsError`` with a
    user-facing message when AppsFlyer rejects the token or app id (the status code tells the
    two apart) or returns any other unexpected status, ``AppsFlyerRetryableError`` on
    rate-limit / 5xx responses, and lets transport errors propagate so the caller can tell a
    transient failure apart from a bad credential. Never returns ``False`` — a non-200 always
    raises so the failure is never silently conflated with a bad credential.
    """
    try:
        app = _validate_app_id(app_id)
    except ValueError:
        raise AppsFlyerCredentialsError(
            "The AppsFlyer app id looks invalid. Use your app's identifier from the dashboard "
            "(e.g. 'id123456789' for iOS or the package name for Android)."
        ) from None
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    response = _get_session(api_token).get(
        f"{APPSFLYER_BASE_URL}/api/agg-data/export/app/{quote(app)}/daily_report/v5"
        f"?{urlencode({'from': today, 'to': today})}",
        timeout=30,
    )
    if response.status_code == 429 or response.status_code >= 500:
        raise AppsFlyerRetryableError(f"AppsFlyer API error (retryable): status={response.status_code}")
    if response.status_code == 200:
        return True
    # 401 is an auth failure (bad token); 403/404 mean the token is fine but the app id or
    # subscription is wrong — surface which one so the user isn't left guessing.
    if response.status_code == 401:
        raise AppsFlyerCredentialsError(
            "AppsFlyer rejected the API token. Check that you pasted a valid API token (V2) from "
            "your account's Security center → AppsFlyer API tokens."
        )
    if response.status_code == 403:
        raise AppsFlyerCredentialsError(
            "AppsFlyer denied access. Check that your account's subscription includes the aggregate "
            "Pull API and that the app id is correct."
        )
    if response.status_code == 404:
        raise AppsFlyerCredentialsError("AppsFlyer couldn't find an app with that app id. Please check the app id.")
    # Any other status is unexpected (e.g. a 400 from a malformed request) — surface the real
    # code rather than blaming the token or app id, which sends users debugging the wrong thing.
    raise AppsFlyerCredentialsError(
        f"AppsFlyer returned an unexpected response (HTTP {response.status_code}) while validating credentials. "
        "If your app id and API token (V2) look correct, please try again shortly or contact support."
    )


def get_rows(
    api_token: str,
    app_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APPSFLYER_ENDPOINTS[endpoint]
    session = _get_session(api_token)
    app = _validate_app_id(app_id)

    today = datetime.now(UTC).date()
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        start = _to_date(db_incremental_field_last_value) - timedelta(days=LOOKBACK_DAYS)
    else:
        start = today - timedelta(days=MAX_WINDOW_DAYS)
    start = min(max(start, today - timedelta(days=MAX_WINDOW_DAYS)), today)

    @retry(
        retry=retry_if_exception_type((AppsFlyerRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def fetch_report() -> str:
        params = {"from": start.strftime("%Y-%m-%d"), "to": today.strftime("%Y-%m-%d")}
        url = f"{APPSFLYER_BASE_URL}/api/agg-data/export/app/{quote(app)}/{config.report}/v5?{urlencode(params)}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise AppsFlyerRetryableError(f"AppsFlyer API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"AppsFlyer API error: status={response.status_code}, body={response.text[:500]}, url={url}")
            response.raise_for_status()

        return response.text

    chunk: list[dict[str, Any]] = []
    for row in _parse_csv_rows(fetch_report(), logger):
        chunk.append(row)
        if len(chunk) >= CHUNK_SIZE:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def appsflyer_source(
    api_token: str,
    app_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = APPSFLYER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            app_id=app_id,
            endpoint=endpoint,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["date"],
        sort_mode="asc",
        # Dimension keys can collide (e.g. blank campaign values).
        has_duplicate_primary_keys=True,
    )
