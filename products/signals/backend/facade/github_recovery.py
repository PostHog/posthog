from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.models import Team, User
from posthog.sync import database_sync_to_async
from posthog.user_permissions import UserPermissions

from products.signals.backend.free_trial import self_driving_free_trial_enabled
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.quota import self_driving_quota_gate
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult


def _manual_implementation_may_resume(
    team_id: int, report_id: str, task_id: str, user_id: int, repository: str
) -> bool:
    team = Team.objects.select_related("organization").get(pk=team_id)
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or UserPermissions(user=user, team=team).current_team.effective_membership_level is None:
        return False
    if (
        not team.organization.is_ai_data_processing_approved
        or self_driving_quota_gate(team).enforced
        or self_driving_free_trial_enabled(team)
    ):
        return False
    report = SignalReport.objects.filter(
        team_id=team_id, id=report_id, report_tasks__task_id=task_id, report_tasks__relationship="implementation"
    ).first()
    row = (
        SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, type="repo_selection")
        .order_by("-created_at", "-id")
        .first()
    )
    selection = RepoSelectionResult.model_validate_json(row.content) if row else None
    return bool(
        report
        and report.status == SignalReport.Status.READY
        and report.run_count == (report.implemented_at_run_count or 0)
        and (report.content_revision_count or 0) == (report.implemented_at_revision_count or 0)
        and selection
        and selection.repository
        and selection.repository.casefold() == repository.casefold()
    )


async def implementation_may_resume(
    *, team_id: int, report_id: str, task_id: str, user_id: int, repository: str, automated: bool = True
) -> bool:
    from products.signals.backend.auto_start import (  # noqa: PLC0415 - breaks the Signals/Tasks autostart cycle
        ImplementationResume,
        maybe_autostart_from_report_artefacts,
    )

    if not automated:
        return await database_sync_to_async(_manual_implementation_may_resume, thread_sensitive=False)(
            team_id, report_id, task_id, user_id, repository
        )
    outcome = await maybe_autostart_from_report_artefacts(
        team_id=team_id,
        report_id=report_id,
        resume=ImplementationResume(task_id=task_id, user_id=user_id, repository=repository),
        ch_user=ClickHouseUser.SIGNALS,
    )
    return outcome.status == "queued"


def record_implementation_github_blocker(team_id: int, report_id: str, reason: str | None) -> None:
    SignalReport.objects.filter(team_id=team_id, id=report_id).update(
        implementation_blocked_reason=reason,
        implementation_blocked_at=Coalesce("implementation_blocked_at", timezone.now()) if reason else None,
    )
