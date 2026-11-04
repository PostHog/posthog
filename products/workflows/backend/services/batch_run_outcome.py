"""The final status of a completed batch run, read from the app metrics of its child runs.

The resolver marks a run completed when it has enqueued the whole audience, before the child runs
execute. This module checks the child runs after that point and moves the run to failed or
partially_failed when its sends errored.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from prometheus_client import Counter

from posthog.schema import ProductKey

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from products.workflows.backend.facade.contracts import WorkflowBatchJobNotFound
from products.workflows.backend.facade.enums import HogFlowBatchJobState
from products.workflows.backend.services.batch_jobs import get_batch_job, set_batch_job_status

logger = structlog.get_logger(__name__)

# The executor records run-level metrics without a step, so ClickHouse stores an empty instance_id.
RUN_LEVEL_INSTANCE_ID = ""

BATCH_RUN_OUTCOMES = Counter(
    "workflows_batch_run_outcome_total",
    "Completed batch runs checked for errored sends, by the status found and whether every child run had ended.",
    labelnames=["outcome", "settled"],
)


@frozen
class BatchRunSendCounts:
    # Child runs the resolver started: the run-level `triggered` metric.
    started: int
    # Child runs that ended: the run-level `succeeded` and `failed` metrics, plus `canceled`.
    finished: int
    # The highest step-level `failed` count. With on_error set to continue, an errored run still counts as
    # succeeded at run level, and the maximum, unlike a sum, counts a run that errors at two steps once.
    errored: int

    @property
    def settled(self) -> bool:
        return self.finished >= self.started

    @property
    def outcome(self) -> HogFlowBatchJobState:
        if self.errored == 0 or self.started == 0:
            return HogFlowBatchJobState.COMPLETED
        if self.errored >= self.started:
            return HogFlowBatchJobState.FAILED
        return HogFlowBatchJobState.PARTIALLY_FAILED


def batch_run_send_counts_from_rows(rows: list[tuple[str, str, int]]) -> BatchRunSendCounts:
    """Fold `(instance_id, metric_name, count)` rows of one batch run into its send counts."""
    started = finished = 0
    errored_by_step: dict[str, int] = {}
    for instance_id, metric_name, count in rows:
        if metric_name == "canceled":
            # A canceled run records the step it stopped at, so its instance_id is not empty.
            finished += count
        elif instance_id == RUN_LEVEL_INSTANCE_ID:
            if metric_name == "triggered":
                started += count
            elif metric_name in ("succeeded", "failed"):
                finished += count
        elif metric_name == "failed":
            errored_by_step[instance_id] = errored_by_step.get(instance_id, 0) + count
    return BatchRunSendCounts(started=started, finished=finished, errored=max(errored_by_step.values(), default=0))


def fetch_batch_run_send_counts(*, team_id: int, batch_job_id: UUID, run_created_at: datetime) -> BatchRunSendCounts:
    # The table keeps one timestamp per collapsed clock hour, so the lower bound is the start of the
    # hour the run was created in. A bound in the middle of that hour could drop the run's first rows.
    after = run_created_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    with tags_context(product=ProductKey.WORKFLOWS, feature=Feature.BATCH_RUN_OUTCOME):
        rows: Any = sync_execute(
            """
            SELECT instance_id, metric_name, sum(count) AS count
            FROM app_metrics2
            WHERE team_id = %(team_id)s
              AND app_source = 'hog_flow'
              AND app_source_id = %(app_source_id)s
              AND timestamp >= toDateTime64(%(after)s, 6)
              AND metric_name IN ('triggered', 'succeeded', 'failed', 'canceled')
            GROUP BY instance_id, metric_name
            """,
            {"team_id": team_id, "app_source_id": str(batch_job_id), "after": after.strftime("%Y-%m-%dT%H:%M:%S")},
            workload=Workload.OFFLINE,
            team_id=team_id,
        )
    return batch_run_send_counts_from_rows([(str(row[0]), str(row[1]), int(row[2])) for row in rows])


def settle_batch_job_outcome(*, team_id: int, batch_job_id: str, final_check: bool) -> bool:
    """Write the status a completed run settles at. Returns False while its child runs still execute.

    On the final check the status comes from the counts so far, so that a child run that never
    records an end cannot hold the check open forever.
    """
    try:
        job = get_batch_job(team_id=team_id, batch_job_id=batch_job_id)
    except WorkflowBatchJobNotFound:
        # The run or its team was deleted, so there is nothing to check and a retry cannot help.
        return True
    if job.status != HogFlowBatchJobState.COMPLETED:
        return True
    counts = fetch_batch_run_send_counts(team_id=team_id, batch_job_id=job.id, run_created_at=job.created_at)
    if not counts.settled and not final_check:
        return False
    outcome = counts.outcome
    BATCH_RUN_OUTCOMES.labels(outcome=outcome.value, settled=str(counts.settled).lower()).inc()
    if not counts.settled:
        logger.warning(
            "batch_run_outcome_unsettled",
            team_id=team_id,
            batch_job_id=batch_job_id,
            started=counts.started,
            finished=counts.finished,
            errored=counts.errored,
        )
    if outcome != HogFlowBatchJobState.COMPLETED:
        # Conditional, so a status that something else wrote since the read above wins.
        set_batch_job_status(
            team_id=team_id,
            batch_job_id=job.id,
            status=outcome,
            from_statuses=[HogFlowBatchJobState.COMPLETED],
        )
    return True
