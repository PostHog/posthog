from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models.integration.github_readiness import GitHubReadiness, GitHubReadinessStatus
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.replay_vision.backend.facade.api import signal_emitting_scanner_ids
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalSourceConfig
from products.tasks.backend.facade.github_readiness import get_team_github_readiness

if TYPE_CHECKING:
    from products.signals.backend.temporal.types import SignalData


@frozen
class CheckReportGitHubReadinessInput:
    team_id: int
    report_id: str
    reason: str | None = None


LEGACY_GITHUB_BLOCKERS = (
    "Requires human input: No GitHub integration connected to a team/user.",
    "Requires human input: No GitHub repositories connected to this team.",
    "Requires human input: The connected GitHub App is unavailable. Reconnect GitHub to continue.",
)


def github_blocked_reports() -> Q:
    return Q(status=SignalReport.Status.CANDIDATE, research_blocked_reason__isnull=False) | Q(
        status=SignalReport.Status.PENDING_INPUT, error__in=LEGACY_GITHUB_BLOCKERS
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


def check_report_github_readiness(team_id: int, report_id: str, reason: str | None = None) -> bool:
    if not SignalReport.objects.filter(
        team_id=team_id, id=report_id, status__in=[SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS]
    ).exists():
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
        report.save(update_fields=[*fields, "research_blocked_reason"])
    return False


@activity.defn
@scoped_temporal()
@close_db_connections
async def check_report_github_readiness_activity(input: CheckReportGitHubReadinessInput) -> bool:
    return await database_sync_to_async(check_report_github_readiness, thread_sensitive=False)(
        input.team_id, input.report_id, input.reason
    )
