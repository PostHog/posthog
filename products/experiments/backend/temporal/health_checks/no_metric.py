from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult

from products.experiments.backend.health.checks.no_metric import no_metric
from products.experiments.backend.temporal.health_checks.findings import (
    detect_experiment_findings,
    live_gate_team_ids,
    render_finding_alert,
    running_experiment,
)


class ExperimentNoMetricCheck(HealthCheck):
    """A running experiment has no metric, so it collects exposures but shows no results."""

    name = "experiment_no_metric"
    kind = "experiment_no_metric"
    owner = JobOwners.TEAM_EXPERIMENTS
    product = Product.EXPERIMENTS
    schedule = "0 8 * * *"
    policy = HealthExecutionPolicy(batch_size=250, max_concurrent=2)
    # Payloads carry experiment names.
    access_controlled_resource = "experiment"
    remediation = Remediation(
        human="""
            Open the experiment and add a primary metric. Metrics apply to all collected data, so the results
            show as soon as the metric is added.
        """,
        agent="""
            Read this issue with `health-issues-get`, then re-read the experiment with `experiment-get`, because
            the issue is a snapshot from the last run. Ask the user which outcome the experiment should move,
            then propose a primary metric for it.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return render_finding_alert(issue)

    @classmethod
    def eligible_team_ids(cls, team_ids: list[int]) -> list[int]:
        return live_gate_team_ids(team_ids)

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        # An ended experiment without a metric is history, not something to fix.
        return detect_experiment_findings(team_ids, no_metric, scope=running_experiment)
