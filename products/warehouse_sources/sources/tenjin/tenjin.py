from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from products.warehouse_sources.sources.sdk import (
    JSONResponsePaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    SyncWindow,
    frozen,
    make_tracked_session,
    redact_literal_values,
    rest_api_resource,
)
from products.warehouse_sources.sources.tenjin.settings import DEFAULT_LOOKBACK_DAYS, TENJIN_REPORTS, TenjinReportConfig

TENJIN_BASE_URL = "https://api.tenjin.com/v2"
# First sync backfill depth. Attribution platforms rarely keep report data useful beyond this.
MAX_HISTORY_DAYS = 730
# Tenjin's own default range when start_date is omitted. A backfill requests one window at a time.
WINDOW_DAYS = 30
# The documented maximum, to keep the request count low on long backfills.
PER_PAGE = 1000
VALIDATE_TIMEOUT_SECONDS = 30
REJECTED_REQUEST_MESSAGE = "Tenjin rejected the report request"
ERROR_DETAIL_LIMIT = 300


class TenjinRetryableError(Exception):
    """Transient upstream failure (429 / 5xx) that survived the tracked session's own retries."""

    pass


class TenjinCredentialsError(Exception):
    """A credential check failed for a reason we can explain to the user."""

    pass


@frozen
class TenjinResumeConfig:
    # Absolute next-page URL from the response's `links.next`. It carries the full original query
    # (dates, group_by, metrics), so resuming from it continues the exact same report pull.
    next_url: Optional[str] = None
    # Last day the resume point covers: the window `next_url` pages through, else the last finished one.
    window_end: Optional[str] = None


def _today() -> date:
    return datetime.now(UTC).date()


def _to_date(value: Any) -> Optional[date]:
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
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> date:
    earliest = today - timedelta(days=MAX_HISTORY_DAYS)
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            return min(max(watermark - timedelta(days=lookback_days), earliest), today)
    return earliest


def date_windows(start: date, end: date) -> Iterator[SyncWindow[date]]:
    while start <= end:
        window_end = min(start + timedelta(days=WINDOW_DAYS - 1), end)
        yield SyncWindow(start=start, end=window_end)
        start = window_end + timedelta(days=1)


def rejected_request_message(response: requests.Response, api_key: str) -> str:
    """The error for a 400, with Tenjin's reason from its documented `{"error": "..."}` body and the token removed."""
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = body.get("error") if isinstance(body, dict) else None
    if not isinstance(detail, str) or not detail.strip():
        return f"{REJECTED_REQUEST_MESSAGE}. Check that your account has access to the requested report and metrics."
    return f"{REJECTED_REQUEST_MESSAGE}: {redact_literal_values(detail, (api_key,)).strip()[:ERROR_DETAIL_LIMIT]}"


def _report_config(
    api_key: str,
    endpoint: str,
    report: TenjinReportConfig,
    dates: dict[str, str],
    should_use_incremental_field: bool,
) -> RESTAPIConfig:
    return {
        "client": {
            "base_url": TENJIN_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "paginator": JSONResponsePaginator(next_url_path="links.next"),
            # `links.next` is response-controlled; pin every paginated/resumed request to the
            # Tenjin API host and refuse redirects, so a tampered next link can't carry the
            # bearer token off-host.
            "allowed_hosts": [],
            "allow_redirects": False,
            # The client ignores Tenjin's X-Retry-After, so the backoff must outlast its one-minute limit.
            "max_retries": 7,
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "endpoint": {
                    # Rows come wrapped JSON:API style ({"type": "report", "attributes": {...}});
                    # the attributes object is the flat row with dimensions and metrics.
                    "data_selector": "data[*].attributes",
                    "path": report.path,
                    "params": {
                        **dates,
                        # Always daily: rows carry no `date` at totals-daily granularity, which
                        # would break both the primary key and the incremental cursor.
                        "granularity": "daily",
                        "group_by": report.group_by,
                        "metrics": report.metrics,
                        "per_page": PER_PAGE,
                    },
                },
                "table_format": "delta",
            }
        ],
    }


def tenjin_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TenjinResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    report = TENJIN_REPORTS.get(endpoint)
    if report is None:
        raise ValueError(f"Unknown Tenjin report: {endpoint}")

    today = _today()
    start = resolve_start_date(
        should_use_incremental_field, db_incremental_field_last_value, today, lookback_days=report.lookback_days
    )
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_end:
        start = date.fromisoformat(resume.window_end) + timedelta(days=1)

    def save_checkpoint(state: Optional[dict[str, Any]], window_end: date) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(
                TenjinResumeConfig(next_url=str(state["next_url"]), window_end=window_end.isoformat())
            )

    def window_pages(window_end: date, dates: dict[str, str], next_url: Optional[str] = None) -> Iterator[Any]:
        yield from rest_api_resource(
            _report_config(api_key, endpoint, report, dates, should_use_incremental_field),
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=lambda state: save_checkpoint(state, window_end),
            initial_paginator_state={"next_url": next_url} if next_url else None,
        )
        if window_end < today:
            resumable_source_manager.save_state(TenjinResumeConfig(window_end=window_end.isoformat()))
        resumable_source_manager.safe_point()

    def pages() -> Iterator[Any]:
        try:
            if resume is not None and resume.window_end and resume.next_url:
                yield from window_pages(date.fromisoformat(resume.window_end), {}, resume.next_url)
            for window in date_windows(start, today):
                yield from window_pages(
                    window.end, {"start_date": window.start.isoformat(), "end_date": window.end.isoformat()}
                )
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 400:
                raise
            raise requests.HTTPError(rejected_request_message(e.response, api_key), response=e.response) from e

    # As a `Resource` the walk keeps framework checkpoints, so a hand-off never reads a page twice.
    hints = rest_api_resource(
        _report_config(api_key, endpoint, report, {}, should_use_incremental_field),
        team_id,
        job_id,
        db_incremental_field_last_value,
    )._hints
    walk = Resource(pages, name=endpoint, hints=hints)

    return SourceResponse(
        name=endpoint,
        items=lambda: walk,
        primary_keys=list(report.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["date"],
        # Tenjin documents no row order for report responses and offers no sort param, so rows
        # are not guaranteed to arrive ascending by `date`. desc mode persists the incremental
        # watermark only at successful job end instead of checkpointing a misleading per-batch
        # max; the resume checkpoint above covers mid-run interruptions.
        sort_mode="desc",
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the access token works with a one-day, one-row report probe.

    Returns ``True`` on success. Raises ``TenjinCredentialsError`` with a user-facing message when
    Tenjin rejects the token, ``TenjinRetryableError`` on rate-limit / 5xx responses, and lets
    transport errors propagate so a transient failure isn't mislabelled as a bad credential.
    Never returns ``False``.
    """
    today = _today().isoformat()
    params = {
        "start_date": today,
        "end_date": today,
        "group_by": "app",
        "metrics": "spend",
        "per_page": 1,
    }
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
        # The Bearer token rides in every request's default headers, so pin the session off
        # redirects; an upstream redirect must not carry the credential to another host.
        allow_redirects=False,
    )
    response = session.get(
        f"{TENJIN_BASE_URL}/reports/spend?{urlencode(params)}",
        timeout=VALIDATE_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise TenjinRetryableError(f"Tenjin API error (retryable): status={response.status_code}")
    if response.status_code == 200:
        return True
    if response.status_code in (401, 403):
        # Verified against the live API: a missing or unrecognized token returns 401, a token
        # Tenjin can't decode (or one lacking the Reporting Metrics permission) returns 403.
        raise TenjinCredentialsError(
            "Tenjin rejected the access token. Check that you pasted a valid token from "
            "Automate > API Access Tokens in the Tenjin dashboard and that it has the "
            "Reporting Metrics API permission."
        )
    raise TenjinCredentialsError(
        f"Tenjin returned an unexpected response (HTTP {response.status_code}) while validating "
        "credentials. If your access token looks correct, please try again shortly."
    )
