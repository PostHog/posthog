from posthog.clickhouse.query_tagging import Product
from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult

from products.error_tracking.backend.logic.recommendations.source_maps import SourceMapsRecommendation
from products.error_tracking.backend.models import ErrorTrackingRecommendation

RECOMMENDATIONS_PATH = "/error_tracking?activeTab=recommendations"
SOURCE_MAPS_DOCS_URL = "https://posthog.com/docs/error-tracking/upload-source-maps"
# Same command the source maps fix wizard modal shows (sourceMapsFixWizardLogic.wizardCommand);
# remediation is a static per-kind constant, so the EU region flag is a note rather than interpolated.
WIZARD_COMMAND = "npx -y @posthog/wizard@latest upload-source-maps"


class MissingSourceMapsCheck(HealthCheck):
    """Flags teams whose JavaScript stack traces are mostly unresolved for lack of source maps.

    Reads the persisted `source_maps` recommendation rows rather than recomputing, so the
    Health page and the error tracking recommendations tab can never disagree — clicking
    through from a health issue always lands on a recommendation showing the same state.
    Rows are kept fresh (≤6h stale) by the recommendations background sweep; teams without
    a computed row yet are skipped until the sweep covers them.
    """

    name = "error_tracking_missing_source_maps"
    kind = "error_tracking_missing_source_maps"
    owner = JobOwners.TEAM_ERROR_TRACKING
    product = Product.ERROR_TRACKING
    policy = HealthExecutionPolicy(batch_size=250, max_concurrent=2)
    schedule = "0 7 * * *"
    remediation = Remediation(
        human=f"""
            Run the source maps wizard in your project: `{WIZARD_COMMAND}` (add `--region eu`
            on EU Cloud), or follow the docs at {SOURCE_MAPS_DOCS_URL}.
        """,
        agent=f"""
            Run `{WIZARD_COMMAND}` in the user's project (add `--region eu` if the project is
            on EU Cloud), or set up uploads manually following {SOURCE_MAPS_DOCS_URL}.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        pct = round((issue.payload.get("unresolved_pct") or 0) * 100)
        lookback_hours = issue.payload.get("lookback_hours") or 24
        return AlertContent(
            title="Missing source maps",
            summary=(
                f"{pct}% of JavaScript stack frames were unresolved in the last {lookback_hours} hours. "
                "Upload source maps so stack traces show your original source code."
            ),
            link=RECOMMENDATIONS_PATH,
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        recommendation = SourceMapsRecommendation()
        rows = ErrorTrackingRecommendation.objects.filter(
            team_id__in=team_ids,
            type=SourceMapsRecommendation.type,
            computed_at__isnull=False,
            dismissed_at__isnull=True,
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for row in rows:
            if recommendation.is_completed(row.meta):
                continue
            issues[row.team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload=row.meta,
                    hash_keys=[],
                )
            ]
        return issues
