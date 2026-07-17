"""Scheduled CI-signals coordinator: detect across enrolled teams and emit into Signals.

Mirrors the job-logs coordinator: one fail-silent detect-and-emit activity per source; emit_signal
re-checks org AI-approval and per-type config. The sweep has no request user, so it scans only the
source ids the enabling user snapshot-authorized, under that user's current UserAccessControl
(``list_authorized_ci_signal_sources``) — deletion, revocation, or a deactivated authorizer fail closed.
"""

import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.utils import timezone

import structlog
import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.models.team import Team
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

from products.engineering_analytics.backend.facade.contracts import ENGINEERING_ANALYTICS_FEATURE_FLAG
from products.engineering_analytics.backend.logic.ci_signals_config import (
    is_dry_run,
    list_authorized_ci_signal_sources,
    resolve_authorizer,
)
from products.engineering_analytics.backend.logic.signals.contracts import SOURCE_PRODUCT, CISignalFinding
from products.engineering_analytics.backend.logic.signals.detect import detect_for_source
from products.signals.backend.facade.api import emit_signal, team_ids_with_source_product_enabled
from products.signals.backend.models import SignalEmissionRecord

logger = structlog.get_logger(__name__)

TEAM_ACTIVITY_BATCH_SIZE = 10


@dataclass(frozen=True)
class CISignalTarget:
    team_id: int
    source_id: str
    authorized_by_user_id: int


def _rollout_flag_enabled(team: Team) -> bool:
    # Enrollment and the rollout flag are orthogonal gates; the sweep re-checks the flag per team.
    org_id = str(team.organization_id)
    project_id = str(team.id)
    return bool(
        posthoganalytics.feature_enabled(
            ENGINEERING_ANALYTICS_FEATURE_FLAG,
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
    return [
        CISignalTarget(team_id=team.id, source_id=source.source_id, authorized_by_user_id=source.authorized_by_user_id)
        for source in list_authorized_ci_signal_sources(team=team)
    ]


def _detect_for_target(target: CISignalTarget) -> tuple[list[CISignalFinding], Team | None]:
    team = Team.objects.filter(id=target.team_id).first()
    # Re-check the flag and authorizer at detection time — retries can run long after discovery.
    if team is None or not _rollout_flag_enabled(team):
        return [], None
    user = resolve_authorizer(team=team, user_id=target.authorized_by_user_id)
    if user is None:
        return [], None
    access_control = UserAccessControl(user=user, team=team)
    return detect_for_source(team, target.source_id, user_access_control=access_control), team


def _claim_unemitted(team: Team, findings: list[CISignalFinding]) -> list[CISignalFinding]:
    """Drop findings already emitted, and claim the rest.

    The sweep re-detects standing conditions every hour, so without a durable claim they re-emit
    forever. Claimed before emitting (as conversations does), which trades a dropped signal on a
    mid-emit crash for never double-emitting.
    """
    if not findings:
        return []
    emitted_keys = set(
        SignalEmissionRecord.objects.filter(
            team=team,
            source_product=SOURCE_PRODUCT,
            source_id__in=[finding.source_id for finding in findings],
        ).values_list("source_type", "source_id")
    )
    fresh = [finding for finding in findings if (finding.source_type, finding.source_id) not in emitted_keys]
    if fresh:
        now = timezone.now()
        SignalEmissionRecord.objects.bulk_create(
            [
                SignalEmissionRecord(
                    team=team,
                    source_product=SOURCE_PRODUCT,
                    source_type=finding.source_type,
                    source_id=finding.source_id,
                    emitted_at=now,
                )
                for finding in fresh
            ],
            ignore_conflicts=True,
        )
    return fresh


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
    # Claims nothing, so clearing the flag re-emits these findings rather than skipping them.
    if await database_sync_to_async(is_dry_run, thread_sensitive=False)(team=team):
        logger.info(
            "ci_signals_dry_run",
            team_id=target.team_id,
            github_source_id=target.source_id,
            findings=len(findings),
            source_ids=[finding.source_id for finding in findings],
        )
        return {
            "team_id": target.team_id,
            "source_id": target.source_id,
            "findings": len(findings),
            "emitted": 0,
            "dry_run": True,
        }
    fresh = await database_sync_to_async(_claim_unemitted, thread_sensitive=False)(team, findings)
    if not fresh:
        return {"team_id": target.team_id, "source_id": target.source_id, "findings": len(findings), "emitted": 0}
    emitted = 0
    for finding in fresh:
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
            team_id_batch = team_ids[start : start + TEAM_ACTIVITY_BATCH_SIZE]
            target_groups = await asyncio.gather(*(_execute_discovery_activity(team_id) for team_id in team_id_batch))
            for target_group in target_groups:
                targets.extend(target_group)

        emitted = 0
        for start in range(0, len(targets), TEAM_ACTIVITY_BATCH_SIZE):
            target_batch = targets[start : start + TEAM_ACTIVITY_BATCH_SIZE]
            results = await asyncio.gather(*(_execute_target_activity(target) for target in target_batch))
            for result in results:
                if result is None:
                    continue
                emitted += int(result.get("emitted", 0))
        return {"teams": len(team_ids), "sources": len(targets), "emitted": emitted}
