from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.settings import TENJIN_REPORTS

TENJIN_BASE_URL = "https://api.tenjin.com/v2"
# First sync backfill depth. Attribution platforms rarely keep report data useful beyond this.
MAX_HISTORY_DAYS = 730
# Tenjin keeps restating recent days (late SKAN postbacks, ad network cost corrections), so an
# incremental run re-reads a trailing window; the merge dedupes on the dimension key.
LOOKBACK_DAYS = 7
# The documented maximum, to keep the request count low on long backfills.
PER_PAGE = 1000
VALIDATE_TIMEOUT_SECONDS = 30


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
) -> date:
    earliest = today - timedelta(days=MAX_HISTORY_DAYS)
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            return min(max(watermark - timedelta(days=LOOKBACK_DAYS), earliest), today)
    return earliest


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
    start = resolve_start_date(should_use_incremental_field, db_incremental_field_last_value, today)

    config: RESTAPIConfig = {
        "client": {
            "base_url": TENJIN_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "paginator": JSONResponsePaginator(next_url_path="links.next"),
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
                        "start_date": start.isoformat(),
                        "end_date": today.isoformat(),
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

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(TenjinResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
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
