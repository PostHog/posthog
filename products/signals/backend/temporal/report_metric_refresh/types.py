from datetime import datetime

from posthog.dataclasses import frozen

# Sweep more often than a snapshot becomes stale. That gives a failed or interrupted batch several
# chances to catch up without executing a healthy metric more than once per hour. A Trends query can
# consume its full 60-second query budget. Three hundred fifty targets form 70 five-query activities;
# at 10-way concurrency, seven seven-minute waves (including two minutes of activity headroom) take
# 49 minutes. That leaves 11 minutes for the discovery activity and workflow overhead inside the
# schedule's one-hour workflow timeout.
REPORT_METRIC_REFRESH_SCHEDULE_MINUTES = 15
REPORT_METRIC_REFRESH_INTERVAL_SECONDS = 60 * 60
REPORT_METRIC_REFRESH_QUERY_TIMEOUT_SECONDS = 60
REPORT_METRIC_REFRESH_MAX_REPORTS = 350
REPORT_METRIC_REFRESH_DISCOVERY_PAGE_SIZE = 500
REPORT_METRIC_REFRESH_BATCH_SIZE = 5
REPORT_METRIC_REFRESH_MAX_CONCURRENT_BATCHES = 10
REPORT_METRIC_REFRESH_BATCH_TIMEOUT_SECONDS = (
    REPORT_METRIC_REFRESH_BATCH_SIZE * REPORT_METRIC_REFRESH_QUERY_TIMEOUT_SECONDS + 2 * 60
)


@frozen
class ReportMetricRefreshInput:
    refresh_interval_seconds: int = REPORT_METRIC_REFRESH_INTERVAL_SECONDS
    max_reports: int = REPORT_METRIC_REFRESH_MAX_REPORTS
    batch_size: int = REPORT_METRIC_REFRESH_BATCH_SIZE
    max_concurrent_batches: int = REPORT_METRIC_REFRESH_MAX_CONCURRENT_BATCHES


@frozen
class ReportMetricRefreshTarget:
    team_id: int
    report_id: str


@frozen
class ReportMetricRefreshCursor:
    attempted_at: datetime | None
    report_id: str


@frozen
class ReportMetricRefreshPageInput:
    stale_before: datetime
    page_size: int
    cursor: ReportMetricRefreshCursor | None = None


@frozen
class ReportMetricRefreshPage:
    targets: list[ReportMetricRefreshTarget]
    next_cursor: ReportMetricRefreshCursor | None


@frozen
class ReportMetricRefreshBatchInput:
    targets: list[ReportMetricRefreshTarget]
    stale_before: datetime


@frozen
class ReportMetricRefreshBatchResult:
    attempted: int
    updated: int
    failed: int
    skipped: int


@frozen
class ReportMetricRefreshResult:
    selected: int
    attempted: int
    updated: int
    failed: int
    skipped: int
    batches_failed: int
