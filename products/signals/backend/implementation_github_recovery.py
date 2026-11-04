from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Case, F, Value, When
from django.utils import timezone

from asgiref.sync import async_to_sync

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.models import Team, User
from posthog.models.integration.github_readiness import GitHubAccessUnavailable, GitHubReadinessStatus
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.free_trial import self_driving_free_trial_enabled
from products.signals.backend.github_recovery import (
    GITHUB_ACCESS_FAILURE,
    GITHUB_RECOVERY_STATE_KEYS,
    GITHUB_RECOVERY_WINDOW,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.quota import self_driving_quota_gate
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.github_readiness import get_team_github_readiness
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult
from products.tasks.backend.facade.task_run_signals import TaskRunPreflightError

if TYPE_CHECKING:
    from products.tasks.backend.facade.contracts import TaskRunDTO


def _recovery_deadline(state: Mapping[str, object]) -> datetime | None:
    value = state.get("github_recovery_deadline")
    if not isinstance(value, str):
        return None
    try:
        deadline = datetime.fromisoformat(value)
    except ValueError:
        return None
    return deadline if timezone.is_aware(deadline) else None


def _manual_implementation_may_retry(team_id: int, report_id: str, task_id: str, user_id: int, repository: str) -> bool:
    team = Team.objects.select_related("organization").get(pk=team_id)
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or UserPermissions(user=user, team=team).current_team.effective_membership_level is None:
        return False
    # The retry starts the run without the task API, so it repeats the API's task access check here.
    if not UserAccessControl(user=user, team=team).check_access_level_for_resource("task", "editor"):
        return False
    if (
        not team.organization.is_ai_data_processing_approved
        or self_driving_quota_gate(team).enforced
        or self_driving_free_trial_enabled(team)
    ):
        return False
    link = (
        SignalReportTask.objects.select_related("report")
        .filter(team_id=team_id, report_id=report_id, task_id=task_id, relationship="implementation")
        .first()
    )
    report = link.report if link else None
    row = (
        SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, type="repo_selection")
        .order_by("-created_at", "-id")
        .first()
    )
    selection = RepoSelectionResult.model_validate_json(row.content) if row else None
    # Without a named selection, task creation picked the repository itself. Callers already compare
    # the task with the repository snapshot taken when GitHub blocked it.
    named_repository = selection.repository if selection else None
    return bool(
        report
        and link
        and report.status == SignalReport.Status.READY
        and report.run_count == link.report_run_count
        and (report.content_revision_count or 0) == link.report_content_revision_count
        and (named_repository is None or named_repository.casefold() == repository.casefold())
    )


def implementation_may_retry(
    *, team_id: int, report_id: str, task_id: str, user_id: int, repository: str, automated: bool = True
) -> bool:
    from products.signals.backend.auto_start import (  # noqa: PLC0415 - breaks the Signals/Tasks autostart cycle
        ImplementationRecovery,
        maybe_autostart_from_report_artefacts,
    )

    if not automated:
        return _manual_implementation_may_retry(team_id, report_id, task_id, user_id, repository)
    outcome = async_to_sync(maybe_autostart_from_report_artefacts)(
        team_id=team_id,
        report_id=report_id,
        recovery=ImplementationRecovery(task_id=task_id, user_id=user_id, repository=repository),
        ch_user=ClickHouseUser.SIGNALS,
    )
    return outcome.status == "queued"


def record_implementation_github_blocker(team_id: int, report_id: str, reason: str | None) -> None:
    now = timezone.now()
    # A blocker inside the recovery window keeps its start time. An expired one belongs to an earlier
    # attempt, so the new attempt starts its own window.
    blocked_at = Case(
        When(implementation_blocked_at__gte=now - GITHUB_RECOVERY_WINDOW, then=F("implementation_blocked_at")),
        default=Value(now),
    )
    SignalReport.objects.filter(team_id=team_id, id=report_id).update(
        implementation_blocked_reason=reason,
        implementation_blocked_at=blocked_at if reason else None,
    )


def require_implementation_github_access(run_id: str, create_pr: bool) -> None:
    if not create_pr:
        return
    run = tasks_facade.get_task_run(run_id)
    if (
        run is None
        or run.status != "queued"
        or run.environment != "cloud"
        or run.task_origin_product != "signal_report"
    ):
        return
    link = (
        SignalReportTask.objects.filter(team_id=run.team_id)
        .filter(task_id=run.task_id, relationship="implementation")
        .first()
    )
    tasks = tasks_facade.get_tasks_by_ids([run.task_id], [run.team_id])
    if link is None or not tasks:
        return
    task = tasks[0]
    repository = task.repository
    user_id = task.created_by_id
    if not repository or user_id is None:
        return
    deadline = _recovery_deadline(run.state)
    recovering = "github_recovery_deadline" in run.state
    if recovering and (deadline is None or deadline <= timezone.now()):
        raise TaskRunPreflightError("GitHubRecoveryExpired", "GitHub recovery expired. Start a new implementation.")
    readiness = get_team_github_readiness(run.team_id, verify=True, repository=task.repository)
    if readiness.status == GitHubReadinessStatus.READY:
        if recovering and (
            task.archived
            or run.state.get("github_recovery_repository") != task.repository
            or run.state.get("github_recovery_user_id") != task.created_by_id
            or not implementation_may_retry(
                team_id=run.team_id,
                report_id=str(link.report_id),
                task_id=str(task.id),
                user_id=user_id,
                repository=repository,
                automated=task.internal,
            )
        ):
            raise TaskRunPreflightError(
                "GitHubRecoveryIneligible",
                "This implementation is no longer eligible to retry. Start a new implementation.",
            )
        if readiness.integration is not None:
            tasks_facade.set_task_project_github_integration(
                run.task_id, run.team_id, readiness.integration.integration.id
            )
        record_implementation_github_blocker(run.team_id, str(link.report_id), None)
        return
    tasks_facade.update_task_run_state(
        run.id,
        updates={
            "github_blocked_reason": readiness.status,
            "github_recovery_deadline": (deadline or timezone.now() + GITHUB_RECOVERY_WINDOW).isoformat(),
            "github_recovery_repository": run.state.get("github_recovery_repository", task.repository),
            "github_recovery_user_id": run.state.get("github_recovery_user_id", task.created_by_id),
        },
    )
    record_implementation_github_blocker(run.team_id, str(link.report_id), readiness.status)
    raise TaskRunPreflightError(GITHUB_ACCESS_FAILURE, str(GitHubAccessUnavailable(readiness.status).detail))


def _create_replacement_run(
    failed: "TaskRunDTO", *, report_id: str, user_id: int, deadline: datetime, integration_id: int | None
) -> None:
    team_id = failed.team_id
    links = SignalReportTask.objects.filter(team_id=team_id, report_id=report_id, relationship="implementation")
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=team_id, id=report_id)
        if (
            report.status != SignalReport.Status.READY
            or deadline <= timezone.now()
            or not links.filter(
                task_id=failed.task_id,
                report_run_count=report.run_count,
                report_content_revision_count=report.content_revision_count or 0,
            ).exists()
        ):
            return
        latest = tasks_facade.get_signal_report_implementation_runs(
            team_id, report_id, links.values_list("task_id", flat=True)
        )
        if not latest or latest[0].id != failed.id or latest[0].status != "failed":
            return
        if integration_id is not None:
            tasks_facade.set_task_project_github_integration(failed.task_id, team_id, integration_id)
        # Preflight failed before delivery, so the first turn is still undelivered. An interactive run
        # without it boots idle.
        message = failed.state.get("pending_user_message")
        first_turn = {"pending_user_message": message} if isinstance(message, str) and message else {}
        result = tasks_facade.run_task(
            failed.task_id,
            team_id,
            user_id,
            pipeline_rerun=True,
            free_trial_enabled=False,
            validated_data={
                "mode": failed.mode,
                "run_source": failed.state.get("run_source", "signal_report"),
                "resume_from_run_id": str(failed.id),
                **first_turn,
            },
        )
        if result is not None and result.run_id is not None:
            tasks_facade.update_task_run_state(
                result.run_id,
                updates={key: failed.state[key] for key in GITHUB_RECOVERY_STATE_KEYS},
            )


def retry_report_implementation(team_id: int, report_id: str) -> None:
    links = SignalReportTask.objects.filter(team_id=team_id).filter(report_id=report_id, relationship="implementation")
    runs = tasks_facade.get_signal_report_implementation_runs(
        team_id, report_id, links.values_list("task_id", flat=True)
    )
    if not runs:
        return
    failed = runs[0]
    deadline = _recovery_deadline(failed.state)
    if (
        failed.status != "failed"
        or failed.environment != "cloud"
        or failed.state.get("failure_error_type") != GITHUB_ACCESS_FAILURE
        or deadline is None
        or deadline <= timezone.now()
    ):
        return
    tasks = tasks_facade.get_tasks_by_ids([failed.task_id], [team_id])
    if not tasks or tasks[0].archived:
        return
    task = tasks[0]
    user_id = failed.state.get("github_recovery_user_id")
    repository = failed.state.get("github_recovery_repository")
    if (
        not isinstance(user_id, int)
        or not isinstance(repository, str)
        or task.created_by_id != user_id
        or task.repository != repository
    ):
        return
    readiness = get_team_github_readiness(team_id, verify=True, repository=repository)
    if readiness.status == GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE:
        raise GitHubAccessUnavailable(readiness.status)
    if readiness.status != GitHubReadinessStatus.READY:
        return
    if not implementation_may_retry(
        team_id=team_id,
        report_id=report_id,
        task_id=str(task.id),
        user_id=user_id,
        repository=repository,
        automated=task.internal,
    ):
        return
    _create_replacement_run(
        failed,
        report_id=report_id,
        user_id=user_id,
        deadline=deadline,
        integration_id=readiness.integration.integration.id if readiness.integration is not None else None,
    )
