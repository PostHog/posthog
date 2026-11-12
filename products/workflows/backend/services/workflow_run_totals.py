from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.workload import Workload

from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.services.batch_run_outcome import RUN_LEVEL_INSTANCE_ID

HOG_FLOW_APP_SOURCE = "hog_flow"
RUN_OUTCOMES = ["succeeded", "failed"]

# The worker writes every run to this series and mirrors it under the versioned one in the same call, so this series
# alone holds every run, from before the mirror shipped too. It keys a batch-triggered run by its batch job id instead
# of the workflow id, so the caller maps those keys back to their workflow.
RUN_TOTALS_BY_SOURCE = """
    SELECT app_source_id, metric_name, sum(count)
    FROM app_metrics2
    WHERE team_id = %(team_id)s
    AND app_source = %(app_source)s
    AND instance_id = %(instance_id)s
    AND metric_name IN %(names)s
    AND timestamp >= toDateTime64(%(after)s, 6)
    {before_clause}
    GROUP BY app_source_id, metric_name
"""


def _batch_job_workflows(team_id: int, source_ids: set[str]) -> dict[str, str]:
    job_ids = []
    for source_id in source_ids:
        try:
            job_ids.append(UUID(source_id))
        except ValueError:
            continue
    jobs = HogFlowBatchJob.objects.filter(team_id=team_id, id__in=job_ids).values_list("id", "hog_flow_id")
    return {str(job_id): str(hog_flow_id) for job_id, hog_flow_id in jobs}


def fetch_run_totals_by_workflow(
    team_id: int, after: datetime, before: Optional[datetime] = None
) -> dict[str, dict[str, int]]:
    """Succeeded and failed runs per workflow id, with batch runs counted toward their workflow."""
    params: dict[str, Any] = {
        "team_id": team_id,
        "app_source": HOG_FLOW_APP_SOURCE,
        "instance_id": RUN_LEVEL_INSTANCE_ID,
        "names": RUN_OUTCOMES,
        "after": after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "before": before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if before else None,
    }
    query = RUN_TOTALS_BY_SOURCE.format(before_clause="AND timestamp <= toDateTime64(%(before)s, 6)" if before else "")
    # DEFAULT follows the caller: sync_execute sends API-key polling offline and app requests online.
    rows = sync_execute(query, params, workload=Workload.DEFAULT)
    workflow_by_job = _batch_job_workflows(team_id, {source_id for source_id, _, _ in rows})
    totals: dict[str, dict[str, int]] = {}
    for source_id, metric_name, count in rows:
        outcomes = totals.setdefault(workflow_by_job.get(source_id, source_id), {})
        outcomes[metric_name] = outcomes.get(metric_name, 0) + count
    return totals
