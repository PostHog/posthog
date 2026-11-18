from django.db import models

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.facade.api import has_signal_emitting_scanner
from products.signals.backend.first_report_scout import first_report_state
from products.signals.backend.first_report_scout_types import FirstReportStatus
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalSourceConfig, SignalTeamConfig
from products.signals.backend.scout_harness.create_access import can_create_scout
from products.signals.backend.scout_harness.operational import operational_config_q


class InboxSetupState(models.TextChoices):
    NOT_STARTED = "not_started", "Not started"
    IN_PROGRESS = "in_progress", "In progress"
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    AI_DISABLED = "ai_disabled", "AI data processing disabled"


@frozen
class InboxStatus:
    setup_state: InboxSetupState
    has_report_history: bool
    first_report_status: FirstReportStatus | None
    can_configure: bool


def resolve_setup_state(
    *, ai_approved: bool, has_draft: bool, completed: bool, watching: bool, has_reports: bool
) -> InboxSetupState:
    if not ai_approved:
        return InboxSetupState.AI_DISABLED
    if has_draft and not completed:
        return InboxSetupState.IN_PROGRESS
    if watching:
        return InboxSetupState.ACTIVE
    if completed or has_reports:
        return InboxSetupState.PAUSED
    return InboxSetupState.NOT_STARTED


def get_inbox_status(team: Team, user: User) -> InboxStatus:
    canonical_team = team.parent_team or team
    config = SignalTeamConfig.objects.filter(team_id=team.id).only("onboarding").first()
    onboarding = (config.onboarding or {}) if config else {}
    has_reports = (
        SignalReport.objects.filter(team_id=team.id)
        .filter(
            models.Q(first_visible_at__isnull=False)
            | models.Q(status__in=[SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT])
        )
        .exists()
    )
    sources = (
        SignalSourceConfig.objects.filter(team_id=team.id, enabled=True)
        .exclude(source_product="signals_scout", source_type="cross_source_issue")
        .exclude(source_product="llm_analytics", source_type="evaluation")
        .exclude(source_product="session_replay", source_type="session_analysis_cluster")
    )
    scouts = (
        SignalScoutConfig.objects.for_team(canonical_team.id)
        .filter(enabled=True, emit=True)
        .exclude(managed_by="background")
        .exclude(operational_config_q())
    )
    watching = (
        sources.exists()
        or (
            SignalSourceConfig.is_source_enabled(canonical_team.id, "signals_scout", "cross_source_issue")
            and scouts.exists()
        )
        or has_signal_emitting_scanner(team.id)
    )
    setup_state = resolve_setup_state(
        ai_approved=team.organization.is_ai_data_processing_approved is True,
        has_draft=bool(onboarding.get("draft")),
        completed=bool(onboarding.get("completed_at")),
        watching=watching,
        has_reports=has_reports,
    )
    first_status = None
    if setup_state == InboxSetupState.ACTIVE and not has_reports:
        status = first_report_state(canonical_team.id).get("status")
        if isinstance(status, str) and status in FirstReportStatus.values:
            first_status = FirstReportStatus(status)
        elif onboarding.get("jobs", {}).get("scout") == "pending":
            first_status = FirstReportStatus.PENDING
    access = UserAccessControl(user=user, team=team)
    return InboxStatus(
        setup_state=setup_state,
        has_report_history=has_reports,
        first_report_status=first_status,
        can_configure=access.check_access_level_for_resource("inbox", "editor")
        and UserAccessControl(user=user, team=canonical_team).check_access_level_for_resource("signal_scout", "editor")
        and can_create_scout(user, canonical_team),
    )
