from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult

from products.experiments.backend.health.checks.flag_state import flag_state
from products.experiments.backend.temporal.health_checks.findings import (
    detect_experiment_findings,
    live_gate_team_ids,
    render_finding_alert,
)


class ExperimentFlagStateCheck(HealthCheck):
    """An experiment and its feature flag disagree: paused, no rollout, one variant shipped while
    running, or users still exposed to several variants before launch or after the end."""

    name = "experiment_flag_state"
    kind = "experiment_flag_state"
    owner = JobOwners.TEAM_EXPERIMENTS
    product = Product.EXPERIMENTS
    schedule = "0 8 * * *"
    policy = HealthExecutionPolicy(batch_size=250, max_concurrent=2)
    # Payloads carry experiment names.
    access_controlled_resource = "experiment"
    remediation = Remediation(
        human="""
            Open the experiment and its linked feature flag. If the experiment is running, resume the flag,
            restore the rollout, or end the experiment with a conclusion. If the experiment has not launched
            or has ended, disable the flag, or launch or resume the experiment.
        """,
        agent="""
            Read this issue with `health-issues-get`, then re-read the experiment with `experiment-get` and its
            flag with the feature flag tools, because the issue is a snapshot from the last run. Explain the
            conflict to the user and propose the fix from the issue detail. Do not change the flag or the
            experiment without the user's confirmation, because both changes affect live traffic.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return render_finding_alert(issue)

    @classmethod
    def eligible_team_ids(cls, team_ids: list[int]) -> list[int]:
        return live_gate_team_ids(team_ids)

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        return detect_experiment_findings(team_ids, flag_state)
