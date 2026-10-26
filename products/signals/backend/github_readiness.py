from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models.integration.github_readiness import GitHubReadiness, GitHubReadinessStatus
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.replay_vision.backend.facade.api import signal_emitting_scanner_ids
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalSourceConfig
from products.tasks.backend.facade.github_readiness import (
    GITHUB_RECONNECT_REQUIRED_STATUSES,
    GITHUB_RECOVERY_WINDOW,
    get_team_github_readiness,
)

if TYPE_CHECKING:
    from products.signals.backend.temporal.types import SignalData


@frozen
class ReleaseGitHubRecoveryInput:
    team_id: int
    report_id: str


@frozen
class CheckReportGitHubReadinessInput:
    team_id: int
    report_id: str
    reason: str | None = None
    recovery: bool = False


LEGACY_GITHUB_BLOCKERS = (
    "Requires human input: No GitHub integration connected to a team/user.",
    "Requires human input: No GitHub repositories connected to this team.",
    "Requires human input: The connected GitHub App is unavailable. Reconnect GitHub to continue.",
)


def github_blocked_reports(*, connection_restored: bool = False) -> Q:
    cutoff = timezone.now() - GITHUB_RECOVERY_WINDOW
    blocked = Q(
        status=SignalReport.Status.CANDIDATE,
        research_blocked_reason__isnull=False,
        research_blocked_at__gt=cutoff,
    )
    if not connection_restored:
        return blocked & Q(research_blocked_reason=GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE)
    return blocked | (
        Q(status=SignalReport.Status.PENDING_INPUT, error__in=LEGACY_GITHUB_BLOCKERS)
        & (Q(last_run_at__gt=cutoff) | Q(last_run_at__isnull=True, created_at__gt=cutoff))
    )


def enabled_recovery_signals(team_id: int, signals: list[SignalData]) -> list[SignalData]:
    team = Team.objects.get(pk=team_id)
    source_enabled = {
        (product, source_type): SignalSourceConfig.is_source_enabled(
            (team.parent_team_id or team_id) if product == "signals_scout" else team_id, product, source_type
        )
        for product, source_type in {(signal.source_product, signal.source_type) for signal in signals}
    }
    scout_names = set(
        SignalScoutConfig.objects.for_team(team.parent_team_id or team_id)
        .filter(enabled=True, emit=True)
        .values_list("skill_name", flat=True)
    )
    scanner_ids: set[str] = set()
    for signal in signals:
        if signal.source_product == "replay_vision":
            try:
                scanner_ids.add(str(UUID(str(signal.extra.get("scanner_id", "")))))
            except ValueError:
                continue
    enabled_scanners = signal_emitting_scanner_ids(team_id, list(scanner_ids)) if scanner_ids else set()
    return [
        signal
        for signal in signals
        if source_enabled[(signal.source_product, signal.source_type)]
        and (signal.source_product != "replay_vision" or signal.extra.get("scanner_id") in enabled_scanners)
        and (signal.source_product != "signals_scout" or signal.extra.get("skill_name") in scout_names)
    ]


def check_report_github_readiness(
    team_id: int, report_id: str, reason: str | None = None, *, recovery: bool = False
) -> bool:
    report = SignalReport.objects.filter(
        team_id=team_id, id=report_id, status__in=[SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS]
    ).first()
    if report is None:
        return False
    if report.research_blocked_at and report.research_blocked_at <= timezone.now() - GITHUB_RECOVERY_WINDOW:
        return False
    if not reason and not recovery and report.research_blocked_reason in GITHUB_RECONNECT_REQUIRED_STATUSES:
        return False
    readiness = (
        GitHubReadiness(status=GitHubReadinessStatus(reason))
        if reason
        else get_team_github_readiness(team_id, verify=True)
    )
    if readiness.status == GitHubReadinessStatus.READY:
        return True
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=team_id, id=report_id)
        if report.status not in (SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS):
            return False
        fields = []
        if report.status == SignalReport.Status.IN_PROGRESS:
            fields = report.transition_to(SignalReport.Status.CANDIDATE)
        report.research_blocked_reason = readiness.status
        report.research_blocked_at = report.research_blocked_at or timezone.now()
        report.save(update_fields=[*fields, "research_blocked_reason", "research_blocked_at"])
    return False


@activity.defn
@scoped_temporal()
@close_db_connections
async def check_report_github_readiness_activity(input: CheckReportGitHubReadinessInput) -> bool:
    return await database_sync_to_async(check_report_github_readiness, thread_sensitive=False)(
        input.team_id, input.report_id, input.reason, recovery=input.recovery
    )


def release_github_recovery(team_id: int, report_id: str) -> None:
    """Remove a candidate report from GitHub recovery. `research_blocked_at` stays, so the original
    recovery deadline still applies if the report is blocked again."""
    SignalReport.objects.filter(
        team_id=team_id, id=report_id, status=SignalReport.Status.CANDIDATE, research_blocked_reason__isnull=False
    ).update(research_blocked_reason=None)


@activity.defn
@scoped_temporal()
@close_db_connections
async def release_github_recovery_activity(input: ReleaseGitHubRecoveryInput) -> None:
    await database_sync_to_async(release_github_recovery, thread_sensitive=False)(input.team_id, input.report_id)
