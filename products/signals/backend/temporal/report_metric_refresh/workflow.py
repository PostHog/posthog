import asyncio
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.signals.backend.temporal import metrics
    from products.signals.backend.temporal.report_metric_refresh.activities import (
        collect_report_metric_refresh_page_activity,
        refresh_report_metric_snapshots_batch_activity,
    )
    from products.signals.backend.temporal.report_metric_refresh.types import (
        REPORT_METRIC_REFRESH_BATCH_SIZE,
        REPORT_METRIC_REFRESH_BATCH_TIMEOUT_SECONDS,
        REPORT_METRIC_REFRESH_DISCOVERY_PAGE_SIZE,
        REPORT_METRIC_REFRESH_INTERVAL_SECONDS,
        REPORT_METRIC_REFRESH_MAX_CONCURRENT_BATCHES,
        REPORT_METRIC_REFRESH_MAX_REPORTS,
        ReportMetricRefreshBatchInput,
        ReportMetricRefreshBatchResult,
        ReportMetricRefreshCursor,
        ReportMetricRefreshInput,
        ReportMetricRefreshPageInput,
        ReportMetricRefreshResult,
        ReportMetricRefreshTarget,
    )

WORKFLOW_NAME = "signals-report-metric-refresh"


@workflow.defn(name=WORKFLOW_NAME)
class SignalReportMetricRefreshWorkflow(PostHogWorkflow):
    @workflow.run
    async def run(self, inputs: ReportMetricRefreshInput) -> ReportMetricRefreshResult:
        refresh_interval_seconds = (
            inputs.refresh_interval_seconds
            if 0 < inputs.refresh_interval_seconds <= 24 * 60 * 60
            else REPORT_METRIC_REFRESH_INTERVAL_SECONDS
        )
        max_reports = (
            inputs.max_reports
            if 0 < inputs.max_reports <= REPORT_METRIC_REFRESH_MAX_REPORTS
            else REPORT_METRIC_REFRESH_MAX_REPORTS
        )
        batch_size = (
            inputs.batch_size
            if 0 < inputs.batch_size <= REPORT_METRIC_REFRESH_BATCH_SIZE
            else REPORT_METRIC_REFRESH_BATCH_SIZE
        )
        max_concurrency = max(1, min(inputs.max_concurrent_batches, REPORT_METRIC_REFRESH_MAX_CONCURRENT_BATCHES))
        semaphore = asyncio.Semaphore(max_concurrency)

        async def refresh_batch(targets: list[ReportMetricRefreshTarget]) -> ReportMetricRefreshBatchResult:
            async with semaphore:
                return await workflow.execute_activity(
                    refresh_report_metric_snapshots_batch_activity,
                    ReportMetricRefreshBatchInput(targets=targets, stale_before=stale_before),
                    start_to_close_timeout=timedelta(seconds=REPORT_METRIC_REFRESH_BATCH_TIMEOUT_SECONDS),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=common.RetryPolicy(maximum_attempts=2),
                )

        # Freeze eligibility for the whole workflow. Temporal retries receive this same cutoff, so
        # an activity that completed some targets before failing will skip them on its next attempt.
        stale_before = workflow.now() - timedelta(seconds=refresh_interval_seconds)
        cursor: ReportMetricRefreshCursor | None = None
        selected = attempted = updated = failed = skipped = batches_failed = 0
        while selected < max_reports:
            page = await workflow.execute_activity(
                collect_report_metric_refresh_page_activity,
                ReportMetricRefreshPageInput(
                    stale_before=stale_before,
                    page_size=min(REPORT_METRIC_REFRESH_DISCOVERY_PAGE_SIZE, max_reports - selected),
                    cursor=cursor,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
            if not page.targets:
                break

            selected += len(page.targets)
            batches = [page.targets[offset : offset + batch_size] for offset in range(0, len(page.targets), batch_size)]
            results = await asyncio.gather(*[refresh_batch(batch) for batch in batches], return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    batches_failed += 1
                    workflow.logger.warning(
                        "signals.report_metric_refresh.batch_failed",
                        extra={"error": str(result)},
                    )
                    continue
                attempted += result.attempted
                updated += result.updated
                failed += result.failed
                skipped += result.skipped

            if page.next_cursor is None:
                break
            cursor = page.next_cursor

        # The run completes even when batches fail, so emit a completion log and alerting counters:
        # without them a degraded sweep (every batch failing) reports success and pages nothing.
        workflow.logger.info(
            "signals.report_metric_refresh.tick_done",
            extra={
                "selected": selected,
                "attempted": attempted,
                "updated": updated,
                "failed": failed,
                "skipped": skipped,
                "batches_failed": batches_failed,
            },
        )
        metrics.record_report_metric_refresh_summary(
            updated=updated, failed=failed, skipped=skipped, batches_failed=batches_failed
        )

        return ReportMetricRefreshResult(
            selected=selected,
            attempted=attempted,
            updated=updated,
            failed=failed,
            skipped=skipped,
            batches_failed=batches_failed,
        )
