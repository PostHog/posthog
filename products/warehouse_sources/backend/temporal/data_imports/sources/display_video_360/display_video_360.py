import io
import csv
import json
import time
import datetime as dt
import itertools
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

from django.conf import settings

import requests
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as OAuthCredentials
from structlog.types import FilteringBoundLogger

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_adapter,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import scrub_url
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360.settings import (
    BID_MANAGER_API_VERSION,
    DISPLAY_VIDEO_360_ENDPOINTS,
    REPORT_COLUMN_NAMES,
    REPORT_LOOKBACK_DAYS,
    REPORT_WINDOW_DAYS,
    DisplayVideo360EndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.displayvideo360 import (
    DisplayVideo360AuthTypeConfig,
    DisplayVideo360SourceConfig,
)

DISPLAY_VIDEO_HOST = "https://displayvideo.googleapis.com"
BID_MANAGER_HOST = "https://doubleclickbidmanager.googleapis.com"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Entity data and reporting live behind two separate Google APIs, each with its own scope. Both
# must be enabled on the Cloud project the credentials belong to.
DISPLAY_VIDEO_SCOPES = (
    "https://www.googleapis.com/auth/display-video",
    "https://www.googleapis.com/auth/doubleclickbidmanager",
)

REQUEST_TIMEOUT_SECONDS = 120
# Bid Manager reports are generated asynchronously; a small report is usually ready within a
# minute, a wide one takes several. Poll for up to ~10 minutes, then hand back to Temporal.
REPORT_POLL_INTERVAL_SECONDS = 10.0
REPORT_POLL_MAX_ATTEMPTS = 60
# POSTs are not retried by the tracked transport (urllib3 only retries idempotent methods), so the
# report-job calls get their own small bounded retry for 429/5xx.
POST_MAX_ATTEMPTS = 4
POST_BACKOFF_BASE_SECONDS = 2.0

# The whole report CSV is buffered, parsed, and sorted in memory, so a run-away report could
# exhaust the import worker. Cap the download and fail loudly rather than OOM the worker.
REPORT_DOWNLOAD_CHUNK_BYTES = 1 << 20
REPORT_MAX_DOWNLOAD_BYTES = 512 * (1 << 20)


class DisplayVideo360CredentialsError(Exception):
    """The configured credentials are unusable — no request was made."""


class DisplayVideo360ReportError(Exception):
    """Bid Manager rejected or failed the report job."""


class DisplayVideo360ReportTimeoutError(Exception):
    """The report job was still running when the inline poll budget ran out.

    Deliberately not listed in `get_non_retryable_errors` so Temporal retries the activity; the
    resumable state restarts from the date window that was in flight.
    """


@dataclasses.dataclass
class DisplayVideo360ResumeConfig:
    # Entity fan-out: the advertiser whose page walk was in flight.
    advertiser_id: str | None = None
    # Entity endpoints: the next `pageToken` to request.
    page_token: str | None = None
    # Report streams: ISO date the next report window should start at.
    report_start_date: str | None = None


def _auth(config: DisplayVideo360SourceConfig) -> DisplayVideo360AuthTypeConfig:
    # The generated field is required, but a config row stored before the field existed would
    # deserialize it as absent, so fail with a message instead of an AttributeError.
    auth: DisplayVideo360AuthTypeConfig | None = config.auth_type
    if auth is None:
        raise DisplayVideo360CredentialsError(
            "No Display & Video 360 credentials configured. Add a service account key or OAuth client details."
        )
    return auth


def redact_values(config: DisplayVideo360SourceConfig, integration: Integration | None = None) -> tuple[str, ...]:
    """Credential strings to mask in logged URLs and captured HTTP samples."""
    auth: DisplayVideo360AuthTypeConfig | None = config.auth_type
    candidates = [auth.service_account_key if auth is not None else None]
    if integration is not None:
        candidates.extend([integration.access_token, integration.refresh_token])
    return tuple(value for value in candidates if value)


def parse_service_account_key(raw: str | None) -> dict[str, Any]:
    if not raw or not raw.strip():
        raise DisplayVideo360CredentialsError("The service account key is empty. Paste the full JSON key file.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise DisplayVideo360CredentialsError(f"The service account key is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise DisplayVideo360CredentialsError("The service account key must be a JSON object.")
    missing = [key for key in ("client_email", "private_key") if not parsed.get(key)]
    if missing:
        raise DisplayVideo360CredentialsError(
            f"The service account key is missing required fields: {', '.join(missing)}."
        )
    # `from_service_account_info` honors the key's `token_uri`, POSTing a signed JWT there when the
    # session first refreshes. A tampered key could point that at an internal or attacker host, so
    # pin the exchange to Google's endpoint before any credential is built or request is made.
    token_uri = parsed.get("token_uri")
    if token_uri and token_uri != GOOGLE_TOKEN_URI:
        raise DisplayVideo360CredentialsError(
            f"The service account key has an unexpected token_uri; only {GOOGLE_TOKEN_URI} is allowed."
        )
    parsed["token_uri"] = GOOGLE_TOKEN_URI
    return parsed


def _credentials(config: DisplayVideo360SourceConfig, integration: Integration | None = None) -> Credentials:
    auth = _auth(config)

    if auth.selection == "service_account":
        info = parse_service_account_key(auth.service_account_key)
        try:
            return service_account.Credentials.from_service_account_info(info, scopes=list(DISPLAY_VIDEO_SCOPES))
        except (ValueError, GoogleAuthError) as e:
            raise DisplayVideo360CredentialsError(f"The service account key could not be loaded: {e}") from e

    if integration is None or not integration.refresh_token:
        raise DisplayVideo360CredentialsError(
            "No Google account is connected. Connect an account with access to Display & Video 360."
        )

    return OAuthCredentials(
        token=None,
        refresh_token=integration.refresh_token,
        client_id=settings.DISPLAY_VIDEO_360_APP_CLIENT_ID,
        client_secret=settings.DISPLAY_VIDEO_360_APP_CLIENT_SECRET,
        token_uri=GOOGLE_TOKEN_URI,
        # No `scopes=` on purpose: with a refresh-token grant google-auth forwards the requested
        # scopes to Google's token endpoint, which rejects anything that isn't an exact subset of
        # the original consent ("invalid_scope"). Omitting it refreshes with the granted scopes,
        # and a genuinely missing scope surfaces as a 403 we map to an actionable message.
    )


def display_video_360_session(
    config: DisplayVideo360SourceConfig, integration: Integration | None = None
) -> AuthorizedSession:
    """An authenticated session for both Google APIs, riding the tracked transport."""
    session = AuthorizedSession(_credentials(config, integration))
    adapter = make_tracked_adapter(redact_values=redact_values(config, integration))
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def report_download_session() -> requests.Session:
    """Unauthenticated session for the report download.

    Bid Manager hands back a pre-signed Cloud Storage URL. Sending our bearer token there would
    leak the credential to a host that has no need for it, so the download runs credential-free.
    """
    return make_tracked_session()


def parse_advertiser_ids(raw: str | None) -> list[str]:
    """Split the optional advertiser-id list into a deterministically ordered list.

    The order is the fan-out order, and the resume state bookmarks an advertiser id, so it has to
    be stable across runs — numeric ids sort numerically, anything else lexicographically.
    """
    if not raw:
        return []
    candidates = {part.strip() for part in raw.replace("\n", ",").replace(";", ",").split(",") if part.strip()}
    return sorted(candidates, key=lambda value: (0, int(value), "") if value.isdigit() else (1, 0, value))


def format_update_time(value: Any) -> str:
    """Render an incremental cursor value as the RFC 3339 string DV360 filters expect."""
    if isinstance(value, dt.datetime):
        moment = value
    elif isinstance(value, dt.date):
        moment = dt.datetime.combine(value, dt.time.min)
    else:
        return str(value)
    moment = moment.replace(tzinfo=dt.UTC) if moment.tzinfo is None else moment.astimezone(dt.UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _entity_url(api_version: str, path: str, params: dict[str, Any]) -> str:
    url = f"{DISPLAY_VIDEO_HOST}/{api_version}{path}"
    return f"{url}?{urlencode(params)}" if params else url


def _raise_for_status(response: requests.Response, logger: FilteringBoundLogger) -> None:
    if response.ok:
        return
    # `response.url` can be a pre-signed report download URL carrying replayable signing params;
    # scrub it before it reaches the log line (the tracked transport scrubs its own telemetry).
    logger.error(
        f"Display & Video 360 API error: status={response.status_code}, "
        f"url={scrub_url(response.url or '')}, body={response.text}"
    )
    response.raise_for_status()


def _get_json(session: AuthorizedSession, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    _raise_for_status(response, logger)
    body = response.json()
    return body if isinstance(body, dict) else {}


def _post_json(
    session: AuthorizedSession, url: str, body: dict[str, Any], logger: FilteringBoundLogger
) -> dict[str, Any]:
    for attempt in range(POST_MAX_ATTEMPTS):
        response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == POST_MAX_ATTEMPTS - 1:
                _raise_for_status(response, logger)
            wait = POST_BACKOFF_BASE_SECONDS * (2**attempt)
            logger.warning(
                f"Display & Video 360 report request failed (status={response.status_code}), retrying in {wait}s"
            )
            time.sleep(wait)
            continue
        _raise_for_status(response, logger)
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {}
    raise DisplayVideo360ReportError(f"Display & Video 360 request to {url} kept failing")


def _iter_entity_pages(
    session: AuthorizedSession,
    api_version: str,
    path: str,
    data_key: str,
    params: dict[str, Any],
    page_token: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    token = page_token
    while True:
        query = dict(params)
        if token:
            query["pageToken"] = token
        body = _get_json(session, _entity_url(api_version, path, query), logger)
        items = body.get(data_key) or []
        next_token = body.get("nextPageToken") or None
        yield ([item for item in items if isinstance(item, dict)], next_token)
        if not next_token:
            return
        token = next_token


def _entity_params(
    endpoint: DisplayVideo360EndpointConfig, partner_id: str, update_time_cutoff: str | None
) -> dict[str, Any]:
    params: dict[str, Any] = {"pageSize": endpoint.page_size}
    if endpoint.kind == "advertisers":
        params["partnerId"] = partner_id
    if endpoint.supports_incremental:
        params["orderBy"] = "updateTime"
        if update_time_cutoff:
            # `>=` (not `>`) so a run that stopped mid-timestamp re-reads that instant; merge
            # dedupes on the primary key.
            params["filter"] = f'updateTime>="{update_time_cutoff}"'
    return params


def list_advertiser_ids(
    session: AuthorizedSession,
    api_version: str,
    partner_id: str,
    logger: FilteringBoundLogger,
) -> list[str]:
    ids: list[str] = []
    params = {"pageSize": DISPLAY_VIDEO_360_ENDPOINTS["advertisers"].page_size, "partnerId": partner_id}
    for items, _ in _iter_entity_pages(session, api_version, "/advertisers", "advertisers", params, None, logger):
        ids.extend(str(item["advertiserId"]) for item in items if item.get("advertiserId") is not None)
    return sorted(set(ids), key=lambda value: (0, int(value), "") if value.isdigit() else (1, 0, value))


def resolve_advertiser_ids(
    session: AuthorizedSession,
    api_version: str,
    config: DisplayVideo360SourceConfig,
    logger: FilteringBoundLogger,
) -> list[str]:
    """The advertisers to fan out over, always confined to the configured partner.

    `advertisers/{id}/...` is addressed by advertiser alone, so a configured ID that belongs to
    another partner the credential can also reach would be read even though the connection is
    pinned to `partner_id`. Configured IDs are therefore checked against the partner's own
    advertisers before any child request is made.
    """
    partner_advertiser_ids = list_advertiser_ids(session, api_version, config.partner_id, logger)
    configured = parse_advertiser_ids(config.advertiser_ids)
    if not configured:
        return partner_advertiser_ids

    allowed = set(partner_advertiser_ids)
    outside_partner = [advertiser_id for advertiser_id in configured if advertiser_id not in allowed]
    if outside_partner:
        raise DisplayVideo360CredentialsError(
            f"Advertiser IDs not under Display & Video 360 partner {config.partner_id}: "
            f"{', '.join(outside_partner)}. Remove them, or change the partner ID."
        )
    return configured


def normalize_report_column(label: str) -> str:
    """Turn a Bid Manager CSV header label into a stable snake_case column name."""
    key = " ".join(label.strip().lower().split())
    mapped = REPORT_COLUMN_NAMES.get(key)
    if mapped is not None:
        return mapped
    slug = "".join(char if char.isalnum() else "_" for char in key)
    collapsed = "_".join(part for part in slug.split("_") if part)
    return collapsed or "column"


def parse_report_date(value: str) -> dt.date | None:
    """Parse a report date cell. Bid Manager renders dates as `2026/01/15` or `2026-01-15`."""
    normalized = value.strip().replace("/", "-")
    try:
        return dt.date.fromisoformat(normalized)
    except ValueError:
        return None


def _coerce_report_value(column: str, raw: str) -> Any:
    value = raw.strip()
    # Bid Manager writes "-" for a measure that doesn't apply to the row.
    if value in ("", "-"):
        return None
    if column == "date":
        return parse_report_date(value)
    if column.endswith("_id"):
        return value
    try:
        # Every measure is stored as a float, including counts: mixing int and float for the same
        # column across report windows would make the Delta schema drift mid-backfill.
        return float(value.replace(",", ""))
    except ValueError:
        return value


def parse_report_csv(text: str) -> list[dict[str, Any]]:
    """Parse a Bid Manager CSV report body into rows, dropping the trailing metadata footer.

    Bid Manager appends a blank line followed by report metadata (title, date range, generation
    time) after the data rows, so the first blank row terminates the data section.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []

    columns = [normalize_report_column(label) for label in header]
    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        if not raw_row or not any(cell.strip() for cell in raw_row):
            break
        rows.append(
            {
                column: _coerce_report_value(column, raw_row[index]) if index < len(raw_row) else None
                for index, column in enumerate(columns)
            }
        )
    return rows


def _google_date(value: dt.date) -> dict[str, int]:
    return {"year": value.year, "month": value.month, "day": value.day}


def build_report_query_body(
    endpoint: DisplayVideo360EndpointConfig,
    title: str,
    start: dt.date,
    end: dt.date,
    partner_id: str,
    advertiser_ids: list[str],
) -> dict[str, Any]:
    filters: list[dict[str, str]] = [{"type": "FILTER_PARTNER", "value": partner_id}]
    filters.extend({"type": "FILTER_ADVERTISER", "value": advertiser_id} for advertiser_id in advertiser_ids)
    return {
        "metadata": {"title": title, "dataRange": report_data_range(start, end), "format": "CSV"},
        "params": {
            "type": "STANDARD",
            "groupBys": list(endpoint.report_group_bys),
            "metrics": list(endpoint.report_metrics),
            "filters": filters,
        },
        "schedule": {"frequency": "ONE_TIME"},
    }


def report_data_range(start: dt.date, end: dt.date) -> dict[str, Any]:
    return {
        "range": "CUSTOM_DATES",
        "customStartDate": _google_date(start),
        "customEndDate": _google_date(end),
    }


def _poll_report(
    session: AuthorizedSession,
    query_id: str,
    report_id: str,
    logger: FilteringBoundLogger,
) -> str | None:
    url = f"{BID_MANAGER_HOST}/{BID_MANAGER_API_VERSION}/queries/{query_id}/reports/{report_id}"
    for attempt in range(REPORT_POLL_MAX_ATTEMPTS):
        body = _get_json(session, url, logger)
        metadata = body.get("metadata") or {}
        state = (metadata.get("status") or {}).get("state")
        if state == "DONE":
            path = metadata.get("googleCloudStoragePath")
            return path if isinstance(path, str) and path else None
        if state == "FAILED":
            raise DisplayVideo360ReportError(
                f"Display & Video 360 report {report_id} failed. Check the report parameters and account access."
            )
        logger.debug(f"Display & Video 360 report {report_id} state={state}, attempt={attempt}")
        time.sleep(REPORT_POLL_INTERVAL_SECONDS)
    raise DisplayVideo360ReportTimeoutError(
        f"Display & Video 360 report {report_id} was still running after "
        f"{REPORT_POLL_MAX_ATTEMPTS} polls; the sync will resume from this window."
    )


def download_report_rows(download: requests.Session, path: str, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    parsed = urlparse(path)
    if parsed.scheme != "https":
        # The download URL comes back inside the API response; only ever follow an https URL so a
        # tampered response can't redirect the fetch at something local.
        raise DisplayVideo360ReportError(f"Display & Video 360 returned an unexpected report path: {path!r}")
    with download.get(path, timeout=REQUEST_TIMEOUT_SECONDS, stream=True) as response:
        _raise_for_status(response, logger)
        buffer = io.BytesIO()
        total = 0
        for chunk in response.iter_content(chunk_size=REPORT_DOWNLOAD_CHUNK_BYTES):
            if not chunk:
                continue
            total += len(chunk)
            if total > REPORT_MAX_DOWNLOAD_BYTES:
                raise DisplayVideo360ReportError(
                    f"Display & Video 360 report exceeded the "
                    f"{REPORT_MAX_DOWNLOAD_BYTES // (1 << 20)} MiB download limit."
                )
            buffer.write(chunk)
    return parse_report_csv(buffer.getvalue().decode("utf-8", errors="replace"))


def _delete_query(session: AuthorizedSession, query_id: str, logger: FilteringBoundLogger) -> None:
    """Drop the one-time query we created. Best effort — leaving it behind only adds clutter."""
    try:
        session.delete(
            f"{BID_MANAGER_HOST}/{BID_MANAGER_API_VERSION}/queries/{query_id}", timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        logger.warning(f"Could not delete Display & Video 360 query {query_id}: {e}")


def run_report(
    session: AuthorizedSession,
    download: requests.Session,
    endpoint: DisplayVideo360EndpointConfig,
    start: dt.date,
    end: dt.date,
    partner_id: str,
    advertiser_ids: list[str],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """Create → run → poll → download one Bid Manager report window."""
    title = f"PostHog {endpoint.name} {start.isoformat()} to {end.isoformat()}"
    body = build_report_query_body(endpoint, title, start, end, partner_id, advertiser_ids)
    query = _post_json(session, f"{BID_MANAGER_HOST}/{BID_MANAGER_API_VERSION}/queries", body, logger)
    query_id = query.get("queryId")
    if not query_id:
        raise DisplayVideo360ReportError("Display & Video 360 did not return a query id for the report request.")

    try:
        report = _post_json(
            session,
            f"{BID_MANAGER_HOST}/{BID_MANAGER_API_VERSION}/queries/{query_id}:run?synchronous=false",
            {"dataRange": report_data_range(start, end)},
            logger,
        )
        report_id = (report.get("key") or {}).get("reportId")
        if not report_id:
            raise DisplayVideo360ReportError(f"Display & Video 360 did not return a report id for query {query_id}.")

        path = _poll_report(session, str(query_id), str(report_id), logger)
        if path is None:
            # A finished report with no storage path means the window matched no rows.
            return []
        return download_report_rows(download, path, logger)
    finally:
        _delete_query(session, str(query_id), logger)


def report_windows(
    start: dt.date, end: dt.date, window_days: int = REPORT_WINDOW_DAYS
) -> list[tuple[dt.date, dt.date]]:
    if start > end:
        return []
    windows: list[tuple[dt.date, dt.date]] = []
    current = start
    while current <= end:
        window_end = min(current + dt.timedelta(days=window_days - 1), end)
        windows.append((current, window_end))
        current = window_end + dt.timedelta(days=1)
    return windows


def resolve_report_start_date(
    today: dt.date,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dt.date:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return today - dt.timedelta(days=REPORT_LOOKBACK_DAYS)
    if isinstance(db_incremental_field_last_value, dt.datetime):
        last = db_incremental_field_last_value.date()
    elif isinstance(db_incremental_field_last_value, dt.date):
        last = db_incremental_field_last_value
    else:
        parsed = parse_report_date(str(db_incremental_field_last_value)[:10])
        if parsed is None:
            return today - dt.timedelta(days=REPORT_LOOKBACK_DAYS)
        last = parsed
    # Re-read the watermark day itself: DV360 restates the most recent days, and merge dedupes.
    return min(last, today)


def _report_row_batches(rows: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    """Yield the window's rows grouped by date, oldest first.

    The pipeline advances the incremental watermark after each flushed batch, so batches have to
    arrive date-ordered; a report body is not ordered by Bid Manager.
    """
    ordered = sorted(rows, key=lambda row: (row.get("date") is None, row.get("date") or dt.date.min))
    for _, group in itertools.groupby(ordered, key=lambda row: row.get("date")):
        yield list(group)


def _iter_report_rows(
    session: AuthorizedSession,
    endpoint: DisplayVideo360EndpointConfig,
    config: DisplayVideo360SourceConfig,
    resume: DisplayVideo360ResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[DisplayVideo360ResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    today = dt.datetime.now(dt.UTC).date()
    start = resolve_report_start_date(today, should_use_incremental_field, db_incremental_field_last_value)
    if resume is not None and resume.report_start_date:
        resumed = parse_report_date(resume.report_start_date)
        if resumed is not None:
            start = resumed

    advertiser_ids = parse_advertiser_ids(config.advertiser_ids)
    download = report_download_session()

    for window_start, window_end in report_windows(start, today):
        rows = run_report(
            session=session,
            download=download,
            endpoint=endpoint,
            start=window_start,
            end=window_end,
            partner_id=config.partner_id,
            advertiser_ids=advertiser_ids,
            logger=logger,
        )
        yield from _report_row_batches(rows)
        resumable_source_manager.save_state(
            DisplayVideo360ResumeConfig(report_start_date=(window_end + dt.timedelta(days=1)).isoformat())
        )


def _iter_top_level_rows(
    session: AuthorizedSession,
    api_version: str,
    endpoint: DisplayVideo360EndpointConfig,
    params: dict[str, Any],
    resume: DisplayVideo360ResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[DisplayVideo360ResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    page_token = resume.page_token if resume is not None and resume.advertiser_id is None else None
    for items, next_token in _iter_entity_pages(
        session, api_version, endpoint.path, endpoint.data_key, params, page_token, logger
    ):
        if items:
            yield items
        if next_token:
            # Saved after yielding, so a crash re-yields the last page instead of skipping it.
            resumable_source_manager.save_state(DisplayVideo360ResumeConfig(page_token=next_token))


def _iter_partner_rows(
    session: AuthorizedSession,
    api_version: str,
    config: DisplayVideo360SourceConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Read the single configured partner.

    `partners.list` returns every partner the credential can see, which for a Google account or
    service account that spans several DV360 accounts would import partners outside the connection's
    configured scope. Fetch `partners/{partnerId}` instead so the table can never reach past the
    partner the source is pinned to.
    """
    partner_id = config.partner_id.strip()
    body = _get_json(session, f"{DISPLAY_VIDEO_HOST}/{api_version}/partners/{partner_id}", logger)
    if body:
        yield [body]


def _iter_advertiser_child_rows(
    session: AuthorizedSession,
    api_version: str,
    endpoint: DisplayVideo360EndpointConfig,
    params: dict[str, Any],
    advertiser_ids: list[str],
    resume: DisplayVideo360ResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[DisplayVideo360ResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    remaining = advertiser_ids
    resume_advertiser_id: str | None = None
    resume_token: str | None = None
    if resume is not None and resume.advertiser_id is not None and resume.advertiser_id in advertiser_ids:
        remaining = advertiser_ids[advertiser_ids.index(resume.advertiser_id) :]
        resume_advertiser_id = resume.advertiser_id
        resume_token = resume.page_token

    for advertiser_id in remaining:
        path = endpoint.path.format(advertiser_id=advertiser_id)
        page_token = resume_token if advertiser_id == resume_advertiser_id else None
        for items, next_token in _iter_entity_pages(
            session, api_version, path, endpoint.data_key, params, page_token, logger
        ):
            if items:
                # Child resources already carry `advertiserId`; seed it so the composite primary
                # key is populated even if a resource ever omits it.
                yield [{"advertiserId": advertiser_id, **item} for item in items]
            resumable_source_manager.save_state(
                DisplayVideo360ResumeConfig(advertiser_id=advertiser_id, page_token=next_token)
            )


def get_rows(
    config: DisplayVideo360SourceConfig,
    endpoint_name: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DisplayVideo360ResumeConfig],
    integration: Integration | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = DISPLAY_VIDEO_360_ENDPOINTS[endpoint_name]
    session = display_video_360_session(config, integration)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if endpoint.kind == "report":
        yield from _iter_report_rows(
            session=session,
            endpoint=endpoint,
            config=config,
            resume=resume,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
        return

    if endpoint.kind == "partners":
        yield from _iter_partner_rows(session=session, api_version=api_version, config=config, logger=logger)
        return

    cutoff = (
        format_update_time(db_incremental_field_last_value)
        if endpoint.supports_incremental and should_use_incremental_field and db_incremental_field_last_value
        else None
    )
    params = _entity_params(endpoint, config.partner_id, cutoff)

    if endpoint.kind == "advertiser_child":
        advertiser_ids = resolve_advertiser_ids(session, api_version, config, logger)
        yield from _iter_advertiser_child_rows(
            session=session,
            api_version=api_version,
            endpoint=endpoint,
            params=params,
            advertiser_ids=advertiser_ids,
            resume=resume,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
        )
        return

    yield from _iter_top_level_rows(
        session=session,
        api_version=api_version,
        endpoint=endpoint,
        params=params,
        resume=resume,
        resumable_source_manager=resumable_source_manager,
        logger=logger,
    )


def validate_credentials(
    config: DisplayVideo360SourceConfig, api_version: str, integration: Integration | None = None
) -> tuple[bool, str | None]:
    """One cheap probe: fetch the configured partner through the entity API."""
    if not config.partner_id or not config.partner_id.strip():
        return False, "Enter the Display & Video 360 partner ID the data should be read from."

    try:
        session = display_video_360_session(config, integration)
    except DisplayVideo360CredentialsError as e:
        return False, str(e)

    url = f"{DISPLAY_VIDEO_HOST}/{api_version}/partners/{config.partner_id.strip()}"
    try:
        response = session.get(url, timeout=30)
    except GoogleAuthError:
        return False, (
            "PostHog could not authenticate with Google. Reconnect your Google account or check the service "
            "account key, and make sure the credentials still have access to Display & Video 360."
        )
    except requests.RequestException as e:
        return False, f"Could not reach the Display & Video 360 API: {e}"

    if response.ok:
        return True, None
    if response.status_code == 401:
        return False, "Google rejected the credentials. Reconnect your Google account or check the service account key."
    if response.status_code == 403:
        return False, (
            "The credentials are valid but cannot read Display & Video 360. Add the connected account or service "
            "account as a Display & Video 360 user with access to this partner, and enable both the Display & "
            "Video 360 API and the Bid Manager API on the Google Cloud project."
        )
    if response.status_code == 404:
        return False, f"Partner '{config.partner_id.strip()}' was not found. Check the partner ID and try again."
    return False, f"Display & Video 360 credential check failed (status {response.status_code})."


def display_video_360_source(
    config: DisplayVideo360SourceConfig,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DisplayVideo360ResumeConfig],
    integration: Integration | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = DISPLAY_VIDEO_360_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            config=config,
            endpoint_name=endpoint,
            api_version=api_version,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            integration=integration,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(endpoint_config.primary_key),
        # Fan-out endpoints walk one advertiser at a time, each ascending by `updateTime`, so the
        # stream is not globally ascending. Reporting "desc" makes the pipeline persist the
        # watermark only once the whole sync finishes, instead of advancing past advertisers it
        # has not reached yet (same reasoning as the GitHub and Klaviyo fan-outs).
        sort_mode="desc"
        if endpoint_config.kind == "advertiser_child" and endpoint_config.supports_incremental
        else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.kind == "report" else None,
        partition_format="month" if endpoint_config.kind == "report" else None,
        partition_keys=["date"] if endpoint_config.kind == "report" else None,
    )
