from datetime import datetime

from django.db import transaction
from django.utils import timezone

from asgiref.sync import async_to_sync
from temporalio import activity

from posthog.models.integration import Integration
from posthog.models.integration.github_readiness import GitHubAccessUnavailable, GitHubReadinessStatus
from posthog.models.user_integration import UserIntegration
from posthog.temporal.common.utils import asyncify

from products.signals.backend.facade.github_recovery import implementation_may_resume
from products.tasks.backend.github_recovery import (
    GITHUB_BLOCKED_REASON,
    GITHUB_RECOVERY_DEADLINE,
    GITHUB_RECOVERY_STATE_KEYS,
    GitHubRecoveryCheck,
)
from products.tasks.backend.logic.repo_selection.github_readiness import (
    GITHUB_RECONNECT_REQUIRED_STATUSES,
    GITHUB_RECOVERY_WINDOW,
    get_team_github_readiness,
)
from products.tasks.backend.models import Task, TaskRun


@activity.defn
@asyncify
def check_self_driving_github_readiness(run_id: str) -> GitHubRecoveryCheck:
    now = timezone.now()
    with transaction.atomic():
        run = TaskRun.objects.select_related("task").select_for_update(of=("self",)).filter(id=run_id).first()
        if run is None or run.is_terminal or run.task.deleted:
            return GitHubRecoveryCheck(status="cancelled")
        if (
            run.task.origin_product != Task.OriginProduct.SIGNAL_REPORT
            or run.environment == TaskRun.Environment.LOCAL
            or run.status != TaskRun.Status.QUEUED
        ):
            return GitHubRecoveryCheck(status="ready")
        state = dict(run.state or {})
        recovering = bool(state.get(GITHUB_BLOCKED_REASON))
        if GITHUB_RECOVERY_DEADLINE in state:
            try:
                deadline = datetime.fromisoformat(state[GITHUB_RECOVERY_DEADLINE])
            except (ValueError, TypeError):
                return GitHubRecoveryCheck(status="expired")
            if timezone.is_naive(deadline) or deadline <= now:
                return GitHubRecoveryCheck(status="expired")
        else:
            deadline = now + GITHUB_RECOVERY_WINDOW
            # Register before checking GitHub so a concurrent reconnect can find and signal this run.
            state[GITHUB_RECOVERY_DEADLINE] = deadline.isoformat()
            run.state = state
            run.save(update_fields=["state", "updated_at"])
    readiness = get_team_github_readiness(run.team_id, verify=True, repository=run.task.repository)
    if readiness.status == GitHubReadinessStatus.READY:
        if recovering and (
            not run.task.signal_report_id
            or not run.task.created_by_id
            or not run.task.repository
            or TaskRun.objects.filter(task_id=run.task_id, team_id=run.team_id, created_at__gt=run.created_at).exists()
            or not async_to_sync(implementation_may_resume)(
                team_id=run.team_id,
                report_id=str(run.task.signal_report_id),
                task_id=str(run.task_id),
                user_id=run.task.created_by_id,
                repository=run.task.repository,
            )
        ):
            return GitHubRecoveryCheck(status="cancelled")
        if readiness.integration is not None:
            integration = readiness.integration.integration
            Task.objects.filter(id=run.task_id, team_id=run.team_id, deleted=False).update(
                github_integration_id=integration.id if isinstance(integration, Integration) else None,
                github_user_integration_id=integration.id if isinstance(integration, UserIntegration) else None,
            )
        TaskRun.update_state_atomic(run.id, updates={}, remove_keys=GITHUB_RECOVERY_STATE_KEYS)
        TaskRun.objects.filter(id=run.id, status=TaskRun.Status.QUEUED).update(
            error_message=None, queued_at=now, updated_at=now
        )
        return GitHubRecoveryCheck(status="ready")
    TaskRun.update_state_atomic(run.id, updates={GITHUB_BLOCKED_REASON: readiness.status})
    TaskRun.objects.filter(id=run.id, status=TaskRun.Status.QUEUED).update(
        error_message=str(GitHubAccessUnavailable(readiness.status).detail)
    )
    return GitHubRecoveryCheck(
        status="suspended" if readiness.status in GITHUB_RECONNECT_REQUIRED_STATUSES else "retry",
        retry_until=deadline,
    )
