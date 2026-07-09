"""Scheduled CI-signals coordinator: detect across enrolled teams and emit into Signals.

Mirrors the job-logs coordinator (same product, same general-purpose queue): a thin workflow that
discovers enrolled teams via an activity, then runs one detect-and-emit activity per team. Each team
is independent and fail-silent, so one team's bad warehouse data can't sink the sweep. Emission goes
through the Signals facade's ``emit_signal``, which re-checks org AI-approval and the per-type source
config — this coordinator only decides *when* to look.
"""

import json
from datetime import timedelta
from typing import Any

import structlog
import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

from products.engineering_analytics.backend.logic.signals.contracts import SOURCE_PRODUCT, CISignalFinding
from products.engineering_analytics.backend.logic.signals.detect import detect_for_team
from products.signals.backend.facade.api import emit_signal, team_ids_with_source_product_enabled

logger = structlog.get_logger(__name__)

# The product's rollout flag — the same one PostHogFeatureFlagPermission enforces on the API surface
# (presentation/views.py). Signal-source enrollment and the rollout flag are orthogonal gates, so the
# sweep re-checks the flag per team rather than emitting for teams the product isn't rolled out to.
ROLLOUT_FEATURE_FLAG = "engineering-analytics"


def _rollout_flag_enabled(team: Team) -> bool:
    org_id = str(team.organization_id)
    project_id = str(team.id)
    return bool(
        posthoganalytics.feature_enabled(
            ROLLOUT_FEATURE_FLAG,
            str(team.uuid),
            groups={"organization": org_id, "project": project_id},
            group_properties={"organization": {"id": org_id}, "project": {"id": project_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def _detect_for_team_id(team_id: int) -> tuple[list[CISignalFinding], Team | None]:
    team = Team.objects.filter(id=team_id).first()
    if team is None or not _rollout_flag_enabled(team):
        return [], None
    return detect_for_team(team), team


@activity.defn
async def discover_ci_signal_teams_activity() -> list[int]:
    """Team ids that have enabled the engineering_analytics signal source."""
    return await database_sync_to_async(team_ids_with_source_product_enabled, thread_sensitive=False)(SOURCE_PRODUCT)


@activity.defn
async def detect_and_emit_ci_signals_activity(team_id: int) -> dict[str, Any]:
    """Detect CI conditions for one team and emit each as a signal. Fail-silent per finding so a
    single rejected/oversized signal doesn't drop the rest."""
    findings, team = await database_sync_to_async(_detect_for_team_id, thread_sensitive=False)(team_id)
    if team is None or not findings:
        return {"team_id": team_id, "findings": 0, "emitted": 0}
    emitted = 0
    for finding in findings:
        try:
            await emit_signal(
                team=team,
                source_product=SOURCE_PRODUCT,
                source_type=finding.source_type,
                source_id=finding.source_id,
                description=finding.description,
                weight=finding.weight,
                extra=finding.extra,
                remediation=finding.remediation,
            )
            emitted += 1
        except Exception:
            logger.exception(
                "ci_signal_emit_failed",
                team_id=team_id,
                source_type=finding.source_type,
                source_id=finding.source_id,
            )
    return {"team_id": team_id, "findings": len(findings), "emitted": emitted}


@workflow.defn(name="engineering-analytics-ci-signals-coordinator")
class CISignalsCoordinatorWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> dict[str, Any]:
        return json.loads(inputs[0]) if inputs else {}

    @workflow.run
    async def run(self, _state: dict[str, Any] | None = None) -> dict[str, Any]:
        team_ids = await workflow.execute_activity(
            discover_ci_signal_teams_activity,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        emitted = 0
        for team_id in team_ids:
            try:
                result = await workflow.execute_activity(
                    detect_and_emit_ci_signals_activity,
                    team_id,
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                emitted += int(result.get("emitted", 0))
            except Exception:
                # One team's failure (after retries) shouldn't abort the sweep.
                workflow.logger.warning("ci_signals_team_failed", extra={"team_id": team_id})
                continue
        return {"teams": len(team_ids), "emitted": emitted}
