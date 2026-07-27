import io
import re
import csv
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.settings import (
    SWARMIA_ENDPOINTS,
    SwarmiaEndpointConfig,
)

SWARMIA_BASE_URL = "https://app.swarmia.com/api/v0"

REQUEST_TIMEOUT_SECONDS = 60


class SwarmiaRetryableError(Exception):
    pass


@dataclasses.dataclass
class SwarmiaResumeConfig:
    # ISO date (YYYY-MM-DD) of the start of the next window to fetch. Saved after each window's rows
    # are yielded, so a crash resumes at the first window whose rows may not have been committed.
    next_window_start: str


# Documented CSV headers mapped to warehouse-friendly column names. Undocumented headers fall
# through to `_normalize_column`.
_COLUMN_RENAMES: dict[str, str] = {
    "Start Date": "start_date",
    "End Date": "end_date",
    "Parent Team(s)": "parent_teams",
    "Team": "team",
    "Cycle Time (s)": "cycle_time_seconds",
    "Review Rate (%)": "review_rate_percent",
    "Time to first review (s)": "time_to_first_review_seconds",
    "PRs merged / week": "prs_merged_per_week",
    "Merge Time (s)": "merge_time_seconds",
    "PRs in progress": "prs_in_progress",
    "Contributors": "contributors",
    "Deployment Frequency (per day)": "deployment_frequency_per_day",
    "Change Lead Time Minutes": "change_lead_time_minutes",
    "Average Time to Deploy Minutes": "average_time_to_deploy_minutes",
    "Change Failure Rate (%)": "change_failure_rate_percent",
    "Mean Time to Recovery Minutes": "mean_time_to_recovery_minutes",
    "Deployment Count": "deployment_count",
    "Investment Category": "investment_category",
    "FTE months": "fte_months",
    "Relative Percentage": "relative_percentage",
    "Commits": "commits",
    "Pull Request Comments": "pull_request_comments",
    "Pull Request Creations": "pull_request_creations",
    "Pull Request Merges": "pull_request_merges",
    "Pull Request Reviews": "pull_request_reviews",
    "Month": "month",
    "Employee ID": "employee_id",
    "Name": "name",
    "Email": "email",
    "Capitalizable work": "capitalizable_work",
    "Developer months": "developer_months",
    "Additional context": "additional_context",
    "Author ID": "author_id",
    "FTE": "fte",
    "Custom field": "custom_field",
    "Swarmia issue type": "swarmia_issue_type",
    "Issue key": "issue_key",
}

# Window-bound columns parsed to dates so incremental watermarks and partitioning work on real
# date values rather than strings.
_DATE_COLUMNS = {"start_date", "end_date", "month"}

# Metric columns parsed as floats. Always float (never int) so a column's Arrow type can't flip
# between integer and double across batches or syncs.
_FLOAT_COLUMNS = {
    "cycle_time_seconds",
    "review_rate_percent",
    "time_to_first_review_seconds",
    "prs_merged_per_week",
    "merge_time_seconds",
    "prs_in_progress",
    "contributors",
    "deployment_frequency_per_day",
    "change_lead_time_minutes",
    "average_time_to_deploy_minutes",
    "change_failure_rate_percent",
    "mean_time_to_recovery_minutes",
    "deployment_count",
    "fte_months",
    "relative_percentage",
    "commits",
    "pull_request_comments",
    "pull_request_creations",
    "pull_request_merges",
    "pull_request_reviews",
    "developer_months",
    "fte",
}


def _normalize_column(name: str) -> str:
    normalized = name.strip().replace("%", "percent").replace("/", " per ")
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", normalized).strip("_").lower()
    return normalized or "column"


def _rename_column(name: str) -> str:
    return _COLUMN_RENAMES.get(name.strip(), _normalize_column(name))


def _parse_date(value: str) -> date | None:
    """Parse the date formats Swarmia reports use: YYYY-MM-DD, or YYYY-MM for month columns."""
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _convert_value(column: str, value: str | None) -> Any:
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None
    if column in _DATE_COLUMNS:
        return _parse_date(text) or text
    if column in _FLOAT_COLUMNS:
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _get_headers(api_key: str) -> dict[str, str]:
    # Bearer header rather than the documented ?token= query param — proxies may log query strings.
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/csv",
    }


def _make_session(api_key: str) -> requests.Session:
    # capture=False keeps requests metered and logged but excludes them from HTTP sample capture:
    # Swarmia CSV exports carry free-text issue titles and custom fields that scrubadub can't reliably
    # redact, so the raw bodies must never land in the shared HTTP-sample store. Requests stay metered
    # and logged; only the sampled payload is dropped. The token is redacted everywhere it appears.
    return make_tracked_session(redact_values=(api_key,), capture=False)


@retry(
    retry=retry_if_exception_type(
        (
            SwarmiaRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_csv(
    session: requests.Session,
    path: str,
    params: dict[str, str],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[dict[str | None, str]]:
    url = f"{SWARMIA_BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise SwarmiaRetryableError(f"Swarmia API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Swarmia API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return list(csv.DictReader(io.StringIO(response.text)))


def _rows_from_csv(config: SwarmiaEndpointConfig, raw_rows: list[dict[str | None, str]]) -> list[dict[str, Any]]:
    if config.unpivot_month_columns:
        return _unpivot_month_columns(raw_rows)

    rows: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        row: dict[str, Any] = {}
        for raw_column, value in raw_row.items():
            if raw_column is None:
                continue
            column = _rename_column(raw_column)
            row[column] = _convert_value(column, value)
        rows.append(row)
    return rows


def _unpivot_month_columns(raw_rows: list[dict[str | None, str]]) -> list[dict[str, Any]]:
    """Melt capex/employees rows ({Employee ID, Name, Email, <one column per month>}) into one row
    per employee per month, so the table schema doesn't change with the requested year."""
    rows: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        identity: dict[str, Any] = {}
        months: list[tuple[date, Any]] = []
        for raw_column, value in raw_row.items():
            if raw_column is None:
                continue
            month = _parse_date(raw_column)
            if month is not None:
                months.append((month, _convert_value("fte", value)))
            else:
                column = _rename_column(raw_column)
                identity[column] = _convert_value(column, value)
        for month, fte in months:
            rows.append({**identity, "month": month, "fte": fte})
    return rows


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        parsed = _parse_date(value[:10])
        if parsed:
            return parsed
    return None


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _build_windows(config: SwarmiaEndpointConfig, range_start: date, today: date) -> list[tuple[date, date]]:
    """Build the complete (fully in the past) windows covering `range_start`..yesterday.

    Only complete windows are fetched: a partial window's end date shifts every day, which would
    give the same logical row a new primary key on every sync and pile up overlapping rows.
    """
    windows: list[tuple[date, date]] = []
    if config.window == "week":
        start = _week_start(range_start)
        while start + timedelta(days=6) < today:
            windows.append((start, start + timedelta(days=6)))
            start += timedelta(days=7)
    elif config.window == "month":
        start = _month_start(range_start)
        while _next_month(start) - timedelta(days=1) < today:
            windows.append((start, _next_month(start) - timedelta(days=1)))
            start = _next_month(start)
    else:  # year — capex/employees reports the current (partial) year fine, one row per employee
        for year in range(range_start.year, today.year + 1):
            windows.append((date(year, 1, 1), date(year, 12, 31)))
    return windows


def _window_params(config: SwarmiaEndpointConfig, window_start: date, window_end: date) -> dict[str, str]:
    if config.timeframe_param == "month":
        return {"month": window_start.strftime("%Y-%m")}
    if config.timeframe_param == "year":
        return {"year": str(window_start.year)}
    return {"startDate": window_start.isoformat(), "endDate": window_end.isoformat()}


def check_credentials(api_key: str) -> int | None:
    """Probe the cheapest report with the token. Returns the HTTP status, or None on network failure."""
    try:
        response = _make_session(api_key).get(
            f"{SWARMIA_BASE_URL}/reports/pullRequests?{urlencode({'timeframe': 'last_7_days'})}",
            headers=_get_headers(api_key),
            timeout=10,
        )
        return response.status_code
    except Exception:
        return None


def check_endpoint_access(api_key: str, endpoints: list[str]) -> dict[str, str | None]:
    """Probe each report with a minimal window. Some reports (investment, capex, effort) map to
    plan-gated Swarmia features, so a valid token can still be denied per report."""
    session = _make_session(api_key)
    headers = _get_headers(api_key)
    today = datetime.now(UTC).date()
    last_month_start = _month_start(_month_start(today) - timedelta(days=1))

    results: dict[str, str | None] = {}
    for endpoint in endpoints:
        config = SWARMIA_ENDPOINTS.get(endpoint)
        if config is None:
            results[endpoint] = None
            continue
        if config.timeframe_param == "date_range" and config.window == "week":
            params = {"timeframe": "last_7_days"}
        else:
            window_end = _next_month(last_month_start) - timedelta(days=1)
            params = _window_params(config, last_month_start, window_end)
        try:
            response = session.get(
                f"{SWARMIA_BASE_URL}{config.path}?{urlencode(params)}",
                headers=headers,
                timeout=10,
            )
        except Exception:
            # A network blip is not a missing permission; report reachable rather than scaring the user.
            results[endpoint] = None
            continue
        if response.status_code in (401, 403):
            results[endpoint] = (
                "Your Swarmia API token can't access this report. It may require a plan or feature "
                "that isn't enabled for your organization."
            )
        else:
            results[endpoint] = None
    return results


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SwarmiaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = SWARMIA_ENDPOINTS[endpoint]
    session = _make_session(api_key)
    headers = _get_headers(api_key)
    today = datetime.now(UTC).date()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        range_start = date.fromisoformat(resume.next_window_start)
        logger.debug(f"Swarmia: resuming {endpoint} from window start {range_start}")
    elif should_use_incremental_field and (watermark := _coerce_date(db_incremental_field_last_value)) is not None:
        # The watermark is the last fully-synced window's end date (any schema-level lookback is
        # already subtracted by the framework); windows re-align to their grid below, and re-pulled
        # windows merge-dedupe on the primary key.
        range_start = watermark + timedelta(days=1)
    else:
        range_start = today - timedelta(days=config.default_lookback_days)

    windows = _build_windows(config, range_start, today)

    for index, (window_start, window_end) in enumerate(windows):
        params = _window_params(config, window_start, window_end)
        raw_rows = _fetch_csv(session, config.path, params, headers, logger)
        rows = _rows_from_csv(config, raw_rows)
        if rows:
            yield rows
        # Save AFTER yielding so a crash re-fetches (and merge dedupes) the last window rather than
        # skipping it.
        if index + 1 < len(windows):
            resumable_source_manager.save_state(
                SwarmiaResumeConfig(next_window_start=windows[index + 1][0].isoformat())
            )


def swarmia_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SwarmiaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = SWARMIA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Windows are iterated oldest-first, so the incremental watermark (max end_date) advances
        # monotonically batch by batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
