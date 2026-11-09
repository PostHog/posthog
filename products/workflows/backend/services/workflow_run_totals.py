from datetime import UTC, datetime
from typing import Any, Optional

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.workload import Workload

from products.workflows.backend.metrics import HOG_FLOW_VERSION_APP_SOURCE
from products.workflows.backend.services.batch_run_outcome import RUN_LEVEL_INSTANCE_ID

HOG_FLOW_APP_SOURCE = "hog_flow"
RUN_OUTCOMES = ["succeeded", "failed"]

# Both series record the same runs, so summing them would count each run twice. Each one also misses runs the other
# has: the version-agnostic series keys batch runs by run id, and the versioned one holds nothing from before its
# mirror shipped. So each hour of a workflow counts whichever series recorded more of that outcome.
RUN_TOTALS_BY_WORKFLOW = """
    SELECT workflow_id, metric_name, sum(runs)
    FROM (
        SELECT
            if(app_source = %(versioned)s, splitByChar('/', app_source_id)[1], app_source_id) AS workflow_id,
            toStartOfHour(timestamp) AS hour,
            metric_name,
            greatest(sumIf(count, app_source = %(versioned)s), sumIf(count, app_source = %(unversioned)s)) AS runs
        FROM app_metrics2
        WHERE team_id = %(team_id)s
        AND app_source IN (%(versioned)s, %(unversioned)s)
        AND instance_id = %(instance_id)s
        AND metric_name IN %(names)s
        AND timestamp >= toDateTime64(%(after)s, 6)
        {before_clause}
        GROUP BY workflow_id, hour, metric_name
    )
    GROUP BY workflow_id, metric_name
"""


def fetch_run_totals_by_workflow(
    team_id: int, after: datetime, before: Optional[datetime] = None
) -> dict[str, dict[str, int]]:
    """Succeeded and failed runs per workflow id, with batch runs counted toward their workflow."""
    params: dict[str, Any] = {
        "team_id": team_id,
        "versioned": HOG_FLOW_VERSION_APP_SOURCE,
        "unversioned": HOG_FLOW_APP_SOURCE,
        "instance_id": RUN_LEVEL_INSTANCE_ID,
        "names": RUN_OUTCOMES,
        "after": after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "before": before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if before else None,
    }
    query = RUN_TOTALS_BY_WORKFLOW.format(
        before_clause="AND timestamp <= toDateTime64(%(before)s, 6)" if before else ""
    )
    totals: dict[str, dict[str, int]] = {}
    for workflow_id, metric_name, count in sync_execute(query, params, workload=Workload.ONLINE):
        totals.setdefault(workflow_id, {})[metric_name] = count
    return totals
