"""The periodic finding-outcome sweep workflow.

Fans over teams sequentially — the sweep is not latency-sensitive and sequential keeps the GitHub
egress footprint bounded. Each team's activity is independently retried and its failure is isolated,
so one team's bad state never sinks the whole sweep.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from products.review_hog.backend.temporal.outcomes_types import (
    CLASSIFY_FINDING_OUTCOMES_WORKFLOW,
    ClassifyFindingOutcomesInputs,
    ClassifyTeamOutcomesInputs,
)

_DISCOVER_TIMEOUT = timedelta(minutes=5)
# One team can classify up to OUTCOME_MAX_REPORTS_PER_SWEEP reports, each with GitHub reads + a judge
# call per candidate finding — minutes of work — so the per-team activity gets a generous ceiling.
_CLASSIFY_TIMEOUT = timedelta(minutes=30)
_RETRY = RetryPolicy(maximum_attempts=2)


@workflow.defn(name=CLASSIFY_FINDING_OUTCOMES_WORKFLOW)
class ClassifyFindingOutcomesWorkflow:
    @workflow.run
    async def run(self, inputs: ClassifyFindingOutcomesInputs) -> int:
        team_ids: list[int] = await workflow.execute_activity(
            "discover_outcome_teams_activity",
            inputs,
            start_to_close_timeout=_DISCOVER_TIMEOUT,
            retry_policy=_RETRY,
        )

        total = 0
        for team_id in team_ids:
            try:
                total += await workflow.execute_activity(
                    "classify_team_outcomes_activity",
                    ClassifyTeamOutcomesInputs(team_id=team_id, lookback_days=inputs.lookback_days),
                    start_to_close_timeout=_CLASSIFY_TIMEOUT,
                    retry_policy=_RETRY,
                )
            except ActivityError:
                workflow.logger.warning("Finding-outcome classification failed for team %s; continuing", team_id)
        return total
