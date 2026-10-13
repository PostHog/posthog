from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult

from products.experiments.backend.health.checks.forced_variant import forced_variant_release_condition
from products.experiments.backend.temporal.health_checks.findings import (
    detect_experiment_findings,
    live_gate_team_ids,
    render_finding_alert,
)


class ExperimentForcedVariantCheck(HealthCheck):
    """A release condition of the experiment's flag pins a variant, so the users it matches are not
    randomly assigned."""

    name = "experiment_forced_variant"
    kind = "experiment_forced_variant"
    owner = JobOwners.TEAM_EXPERIMENTS
    product = Product.EXPERIMENTS
    schedule = "0 8 * * *"
    policy = HealthExecutionPolicy(batch_size=250, max_concurrent=2)
    # Payloads carry experiment names.
    access_controlled_resource = "experiment"
    remediation = Remediation(
        human="""
            Open the release conditions of the experiment's feature flag and remove the variant override,
            so users are assigned at random. Keep an override only for internal or test users, and check that
            the filter for internal and test users excludes them from the results.
        """,
        agent="""
            Read this issue with `health-issues-get`, then re-read the flag's release conditions with the
            feature flag tools, because the issue is a snapshot from the last run. The evidence names the
            condition sets and the pinned variants. Ask the user whether each override is intended, for
            example to target internal users, before you propose to remove it.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return render_finding_alert(issue)

    @classmethod
    def eligible_team_ids(cls, team_ids: list[int]) -> list[int]:
        return live_gate_team_ids(team_ids)

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        return detect_experiment_findings(team_ids, forced_variant_release_condition)
