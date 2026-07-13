"""Scheduled CI-signals coordinator: detect across enrolled teams and emit into Signals.

Mirrors the job-logs coordinator (same product, same general-purpose queue): a thin workflow that
discovers enrolled teams and their GitHub sources, then runs one detect-and-emit activity per source.
Each source is independent and fail-silent, so one bad warehouse source can't sink the sweep. Emission goes
through the Signals facade's ``emit_signal``, which re-checks org AI-approval and the per-type source
config — this coordinator only decides *when* to look.
"""

import json
import asyncio
from dataclasses import dataclass
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
from products.engineering_analytics.backend.logic.signals.detect import detect_for_source
from products.engineering_analytics.backend.logic.sources import list_github_sources
from products.signals.backend.facade.api import emit_signal, team_ids_with_source_product_enabled

logger = structlog.get_logger(__name__)

# The product's rollout flag — the same one PostHogFeatureFlagPermission enforces on the API surface
# (presentation/views.py). Signal-source enrollment and the rollout flag are orthogonal gates, so the
# sweep re-checks the flag per team rather than emitting for teams the product isn't rolled out to.
ROLLOUT_FEATURE_FLAG = "engineering-analytics"
TEAM_ACTIVITY_BATCH_SIZE = 10


@dataclass(frozen=True)
class CISignalTarget:
    team_id: int
    source_id: str


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


def _discover_targets_for_team(team_id: int) -> list[CISignalTarget]:
    team = Team.objects.filter(id=team_id).first()
    if team is None or not _rollout_flag_enabled(team):
        return []
    return [CISignalTarget(team_id=team.id, source_id=source.id) for source in list_github_sources(team=team)]


def _detect_for_target(target: CISignalTarget) -> tuple[list[CISignalFinding], Team | None]:
    team = Team.objects.filter(id=target.team_id).first()
    if team is None or not _rollout_flag_enabled(team):
        return [], None
    return detect_for_source(team, target.source_id), team


async def _execute_target_activity(target: CISignalTarget) -> dict[str, Any] | None:
    try:
        return await workflow.execute_activity(
            detect_and_emit_ci_signals_activity,
            target,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
    except Exception:
        workflow.logger.warning(
            "ci_signals_source_failed", extra={"team_id": target.team_id, "source_id": target.source_id}
        )
        return None


async def _execute_discovery_activity(team_id: int) -> list[CISignalTarget]:
    try:
        return await workflow.execute_activity(
            discover_ci_signal_targets_activity,
            team_id,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
    except Exception:
        workflow.logger.warning("ci_signals_source_discovery_failed", extra={"team_id": team_id})
        return []


@activity.defn
async def discover_ci_signal_teams_activity() -> list[int]:
    """Team ids that have enabled the engineering_analytics signal source."""
    return await database_sync_to_async(team_ids_with_source_product_enabled, thread_sensitive=False)(SOURCE_PRODUCT)


@activity.defn
async def discover_ci_signal_targets_activity(team_id: int) -> list[CISignalTarget]:
    """Return the enrolled team's connected GitHub sources after rollout gating."""
    return await database_sync_to_async(_discover_targets_for_team, thread_sensitive=False)(team_id)


@activity.defn
async def detect_and_emit_ci_signals_activity(target: CISignalTarget) -> dict[str, Any]:
    """Detect CI conditions for one GitHub source and emit each as a signal. Fail-silent per finding so a
    single rejected/oversized signal doesn't drop the rest."""
    findings, team = await database_sync_to_async(_detect_for_target, thread_sensitive=False)(target)
    if team is None or not findings:
        return {"team_id": target.team_id, "source_id": target.source_id, "findings": 0, "emitted": 0}
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
                idempotency_key=f"{SOURCE_PRODUCT}:{finding.source_type}:{finding.source_id}",
            )
            emitted += 1
        except Exception:
            logger.exception(
                "ci_signal_emit_failed",
                team_id=target.team_id,
                github_source_id=target.source_id,
                source_type=finding.source_type,
                source_id=finding.source_id,
            )
    return {
        "team_id": target.team_id,
        "source_id": target.source_id,
        "findings": len(findings),
        "emitted": emitted,
    }


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
        targets: list[CISignalTarget] = []
        for start in range(0, len(team_ids), TEAM_ACTIVITY_BATCH_SIZE):
            batch = team_ids[start : start + TEAM_ACTIVITY_BATCH_SIZE]
            target_groups = await asyncio.gather(*(_execute_discovery_activity(team_id) for team_id in batch))
            for target_group in target_groups:
                targets.extend(target_group)

        emitted = 0
        for start in range(0, len(targets), TEAM_ACTIVITY_BATCH_SIZE):
            batch = targets[start : start + TEAM_ACTIVITY_BATCH_SIZE]
            results = await asyncio.gather(*(_execute_target_activity(target) for target in batch))
            for result in results:
                if result is None:
                    continue
                emitted += int(result.get("emitted", 0))
        return {"teams": len(team_ids), "sources": len(targets), "emitted": emitted}
