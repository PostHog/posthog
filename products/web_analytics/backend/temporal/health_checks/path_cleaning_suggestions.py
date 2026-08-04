from django.conf import settings

import structlog

from posthog.clickhouse.query_tagging import Product
from posthog.dags.common.owners import JobOwners
from posthog.models import Team
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult

from products.web_analytics.backend.path_cleaning_suggestions.service import (
    build_suggestion_payload,
    generate_suggestions_for_team,
)

logger = structlog.get_logger(__name__)

# LLM generation is orders of magnitude slower and costlier than the framework's
# ClickHouse detectors, so batches stay small and strictly sequential.
LLM_EXECUTION_POLICY = HealthExecutionPolicy(batch_size=10, max_concurrent=1)


class PathCleaningSuggestionsCheck(HealthCheck):
    """Suggests AI-generated path-cleaning rules for teams with messy path cardinality.

    Unlike the other web-analytics checks this is an *opportunity*, not a defect —
    severity stays INFO and the issue carries the validated suggested rules in its
    payload so the settings banner and the health page can offer one-click apply.
    The issue auto-resolves once the team configures any path-cleaning rules
    (applied via the suggestion or by hand), because configured teams are reported
    healthy on the next run.
    """

    name = "path_cleaning_suggestions"
    kind = "path_cleaning_suggestions"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    product = Product.WEB_ANALYTICS
    policy = LLM_EXECUTION_POLICY
    schedule = "23 6 * * 1"  # weekly, Monday 06:23 UTC
    remediation = Remediation(
        human="""
            Open Settings → Product analytics → Path cleaning rules. Review the suggested rules —
            each one shows the regex, the replacement alias, and how many of your real paths it matched —
            then apply them all or add the ones you want by hand. Rules collapse dynamic URL segments
            (IDs, slugs, tokens) so the Paths table groups equivalent pages together.
        """,
        agent="""
            Fetch this issue's payload: `rules` is a list of validated path-cleaning rules
            (regex, alias, order, and match_count — how many of the team's real sampled paths the
            rule rewrote). To apply them, call the web-analytics path-cleaning-suggestions `apply`
            endpoint with this issue's id (requires project admin) — it merges the rules into the
            team's `path_cleaning_filters` without overwriting existing rules and resolves this
            issue. To regenerate fresher suggestions first, call the `generate` endpoint.
        """,
    )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        cohort = set(settings.WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS)
        candidate_ids = [team_id for team_id in team_ids if team_id in cohort]
        if not candidate_ids:
            return {}

        issues: dict[int, list[HealthCheckResult]] = {}

        # Teams with an ACTIVE suggestion keep it alive without a fresh LLM round trip —
        # re-emitting the stored payload preserves the row (and its dismissed flag) while
        # letting the framework resolve it the moment the team configures rules.
        existing_by_team = {
            issue.team_id: issue
            for issue in HealthIssue.objects.filter(
                team_id__in=candidate_ids, kind=self.kind, status=HealthIssue.Status.ACTIVE
            )
        }

        teams = {team.id: team for team in Team.objects.filter(id__in=candidate_ids)}
        for team_id in candidate_ids:
            team = teams.get(team_id)
            if team is None:
                continue
            # Every gate runs inside the per-team guard: a ClickHouse or LLM failure for
            # one team must not abort the batch (the framework counts it as unprocessed).
            try:
                if team.path_cleaning_filters:
                    continue  # healthy → any active suggestion auto-resolves
                existing = existing_by_team.get(team_id)
                if existing is not None:
                    issues[team_id] = [
                        HealthCheckResult(severity=HealthIssue.Severity.INFO, payload=existing.payload, hash_keys=[])
                    ]
                    continue
                result = generate_suggestions_for_team(team)
                if result.status != "generated" or not result.rules:
                    # Skips and empty generations store nothing — an empty suggestion row
                    # would shadow an actionable one in every "latest suggestion" read.
                    continue
                issues[team_id] = [
                    HealthCheckResult(
                        severity=HealthIssue.Severity.INFO,
                        payload=build_suggestion_payload(result),
                        hash_keys=[],
                    )
                ]
            except Exception:
                logger.exception("path_cleaning_suggestions_check_failed", team_id=team_id)

        return issues

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        rule_count = len(issue.payload.get("rules", []))
        return AlertContent(
            title="Path cleaning suggestions available",
            summary=f"{rule_count} suggested path-cleaning rule{'s' if rule_count != 1 else ''} "
            "ready to review, generated from your real page paths",
            link="/settings/environment-product-analytics#path-cleaning",
        )
