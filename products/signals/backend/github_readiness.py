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
from products.signals.backend.github_optional import ResearchAccessPolicy
from products.signals.backend.github_recovery import GITHUB_RECOVERY_WINDOW
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalSourceConfig
from products.signals.backend.research_telemetry import capture_research_access_event
from products.tasks.backend.facade.github_readiness import get_team_github_readiness

if TYPE_CHECKING:
    from products.signals.backend.temporal.types import SignalData


@frozen
class CheckReportGitHubReadinessInput:
    team_id: int
    report_id: str
    reason: str | None = None
    recovery: bool = False


def github_blocked_reports() -> Q:
    return Q(
        status=SignalReport.Status.CANDIDATE,
        research_blocked_reason__isnull=False,
        research_blocked_at__gt=timezone.now() - GITHUB_RECOVERY_WINDOW,
    )


def _recovery_scanner_ids(signals: list[SignalData]) -> set[str]:
    scanner_ids: set[str] = set()
    for signal in signals:
        if signal.source_product == "replay_vision":
            try:
                scanner_ids.add(str(UUID(str(signal.extra.get("scanner_id", "")))))
            except ValueError:
                continue
    return scanner_ids


def _emitter_enabled(signal: SignalData, *, scanners: set[str], scouts: set[str]) -> bool:
    if signal.source_product == "replay_vision":
        return signal.extra.get("scanner_id") in scanners
    if signal.source_product == "signals_scout":
        return signal.extra.get("skill_name") in scouts
    return True


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
    scanner_ids = _recovery_scanner_ids(signals)
    enabled_scanners = signal_emitting_scanner_ids(team_id, list(scanner_ids)) if scanner_ids else set()
    return [
        signal
        for signal in signals
        if source_enabled[(signal.source_product, signal.source_type)]
        and _emitter_enabled(signal, scanners=enabled_scanners, scouts=scout_names)
    ]


RESEARCH_SUSPENDED_FOR_GITHUB_ERROR_TYPE = "ResearchSuspendedForGitHub"


def _suspend_research(team_id: int, report_id: str, reason: GitHubReadinessStatus, *, recovery: bool) -> bool:
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=team_id, id=report_id)
        if report.status not in (SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS):
            return False
        fields = []
        if report.status == SignalReport.Status.IN_PROGRESS:
            fields = report.transition_to(SignalReport.Status.CANDIDATE)
        report.research_blocked_reason = reason
        report.research_blocked_at = report.research_blocked_at or timezone.now()
        report.save(update_fields=[*fields, "research_blocked_reason", "research_blocked_at"])
        if not recovery:
            from products.signals.backend.github_readiness_tasks import (  # noqa: PLC0415 - recovery tasks import the readiness check
                resume_github_blocked_reports,
            )

            # A reconnect can commit before this blocker, so its event may already have scanned the project.
            transaction.on_commit(lambda: resume_github_blocked_reports.delay(team_id))
    capture_research_access_event(
        team_id=team_id, report_id=report_id, origin="pipeline", reason=reason, fallback=False
    )
    return False


def suspend_research_after_lost_read_access(team_id: int, report_id: str) -> None:
    readiness = get_team_github_readiness(team_id, verify=True)
    status = (
        GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE
        if readiness.status == GitHubReadinessStatus.READY
        else readiness.status
    )
    # `recovery=True` skips the immediate recovery scan. GitHub can report ready while credential minting
    # keeps failing, and that scan would then repeat a full research session in a loop.
    _suspend_research(team_id, report_id, status, recovery=True)


def check_report_github_readiness(
    team_id: int, report_id: str, reason: str | None = None, *, recovery: bool = False
) -> bool:
    report = SignalReport.objects.filter(
        team_id=team_id, id=report_id, status__in=[SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS]
    ).first()
    if report is None:
        return False
    if (
        recovery
        and report.research_blocked_at
        and report.research_blocked_at <= timezone.now() - GITHUB_RECOVERY_WINDOW
    ):
        return False
    if ResearchAccessPolicy.enabled(team_id):
        return True
    readiness = (
        GitHubReadiness(status=GitHubReadinessStatus(reason))
        if reason
        else get_team_github_readiness(team_id, verify=True)
    )
    if readiness.status == GitHubReadinessStatus.READY:
        return True
    return _suspend_research(team_id, report_id, readiness.status, recovery=recovery)


@activity.defn
@scoped_temporal()
@close_db_connections
async def check_report_github_readiness_activity(input: CheckReportGitHubReadinessInput) -> bool:
    return await database_sync_to_async(check_report_github_readiness, thread_sensitive=False)(
        input.team_id, input.report_id, input.reason, recovery=input.recovery
    )
