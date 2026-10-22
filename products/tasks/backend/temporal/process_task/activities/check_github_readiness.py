from temporalio import activity

from posthog.models.integration.github_readiness import GitHubAccessUnavailable, GitHubReadinessStatus
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.logic.repo_selection.github_readiness import get_team_github_readiness
from products.tasks.backend.models import Task, TaskRun


@activity.defn
@asyncify
def check_self_driving_github_readiness(run_id: str) -> str:
    run = TaskRun.objects.select_related("task").filter(id=run_id).first()
    if run is None:
        return "ready"
    if run.is_terminal:
        return "cancelled"
    if run.task.origin_product != Task.OriginProduct.SIGNAL_REPORT or run.environment == "local":
        return "ready"
    readiness = get_team_github_readiness(run.team_id, verify=True)
    if readiness.status == GitHubReadinessStatus.READY:
        if (run.state or {}).get("github_blocked_reason"):
            TaskRun.update_state_atomic(run.id, updates={}, remove_keys=["github_blocked_reason"])
            TaskRun.objects.filter(id=run.id, status=TaskRun.Status.QUEUED).update(error_message=None)
        return "ready"
    TaskRun.update_state_atomic(run.id, updates={"github_blocked_reason": readiness.status})
    TaskRun.objects.filter(id=run.id, status=TaskRun.Status.QUEUED).update(
        error_message=str(GitHubAccessUnavailable(readiness.status).detail)
    )
    return "blocked"
