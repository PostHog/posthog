import shlex
from dataclasses import dataclass

import structlog
from temporalio import activity

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.agent_command import SET_TOKEN_TIMEOUT_SECONDS, CommandResult, send_set_gh_token
from products.tasks.backend.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.utils import (
    get_sandbox_github_token,
    mark_gh_token_issued,
    should_refresh_gh_token,
)

logger = structlog.get_logger(__name__)


@dataclass
class RefreshGithubTokenInput:
    run_id: str


@activity.defn
def refresh_github_token(input: RefreshGithubTokenInput) -> None:
    """Push a freshly-minted GitHub token into a live sandbox agent-server.

    Mints a fresh token via the same resolution as provisioning
    (``get_sandbox_github_token``), dispatches ``posthog/set_token`` so the
    agent process env reflects the rotation, and rewrites ``.git/config``'s
    embedded ``x-access-token`` so raw ``git push``/``git fetch`` continue to
    work mid-session.

    Best-effort: every failure is non-fatal so a stale credential never blocks
    the run on its own. The 30-min cache gate prevents redundant work when
    the periodic timer races with workflow restarts.
    """
    run_id = input.run_id

    if not should_refresh_gh_token(run_id):
        logger.info("refresh_gh_token_skipped_within_interval", run_id=run_id)
        return

    try:
        task_run = TaskRun.objects.select_related(
            "task__created_by", "task__github_integration", "task__github_user_integration"
        ).get(id=run_id)
    except TaskRun.DoesNotExist:
        logger.warning("refresh_gh_token_run_not_found", run_id=run_id)
        return

    task = task_run.task
    state = task_run.state or {}
    sandbox_id = state.get("sandbox_id")
    sandbox_url = state.get("sandbox_url")
    if not sandbox_url or not sandbox_id:
        logger.info("refresh_gh_token_skipped_no_sandbox", run_id=run_id)
        return

    github_integration_id = task.github_integration_id
    has_credentials = github_integration_id is not None or task.github_user_integration_id is not None
    if not has_credentials:
        logger.info("refresh_gh_token_skipped_no_credentials", run_id=run_id)
        return

    with log_activity_execution(
        "refresh_github_token",
        run_id=run_id,
        task_id=str(task.id),
        sandbox_id=sandbox_id,
    ):
        try:
            github_token = get_sandbox_github_token(
                github_integration_id,
                run_id=run_id,
                state=state,
                task=task,
                github_user_integration_id=(
                    str(task.github_user_integration_id) if task.github_user_integration_id else None
                ),
                repository=task.repository,
            )
        except Exception as e:
            logger.warning("refresh_gh_token_mint_failed", run_id=run_id, error=str(e))
            return

        if not github_token:
            logger.info("refresh_gh_token_no_token_resolved", run_id=run_id)
            return

        auth_token: str | None = None
        created_by = task.created_by
        if created_by and created_by.id:
            distinct_id = created_by.distinct_id or f"user_{created_by.id}"
            try:
                auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)
            except Exception as e:
                logger.warning("refresh_gh_token_auth_token_failed", run_id=run_id, error=str(e))
                return

        result: CommandResult = send_set_gh_token(
            task_run,
            github_token,
            auth_token=auth_token,
            timeout=SET_TOKEN_TIMEOUT_SECONDS,
        )
        if not result.success:
            logger.warning(
                "refresh_gh_token_command_failed",
                run_id=run_id,
                error=result.error,
                status_code=result.status_code,
            )
            return

        # Rewrite the embedded `x-access-token` in .git/config so raw
        # `git push`/`git fetch` use the rotated token. Skipped when the run
        # has no repository (Slack repo-less runs).
        if task.repository:
            _rewrite_git_remote(sandbox_id, task.repository, github_token, run_id=run_id)

        mark_gh_token_issued(run_id)
        logger.info("refresh_gh_token_delivered", run_id=run_id)


def _rewrite_git_remote(sandbox_id: str, repository: str, github_token: str, *, run_id: str) -> None:
    """Refresh the GitHub token embedded in `.git/config`'s remote URL.

    Mirrors the logic in ``inject_fresh_tokens_on_resume`` but runs mid-session
    against a live sandbox. Guards on `.git` existing so a repo-less or
    pre-clone sandbox is a no-op.
    """
    try:
        sandbox = Sandbox.get_by_id(sandbox_id)
    except Exception as e:
        logger.warning("refresh_gh_token_sandbox_lookup_failed", run_id=run_id, error=str(e))
        return

    org, repo = repository.lower().split("/")
    repo_path = f"/tmp/workspace/repos/{org}/{repo}"
    update_remote = (
        f"if [ -d {shlex.quote(repo_path + '/.git')} ]; then "
        f"cd {shlex.quote(repo_path)} && "
        f"git remote set-url origin "
        f"https://x-access-token:{shlex.quote(github_token)}@github.com/{shlex.quote(repository)}.git; "
        f"fi"
    )

    try:
        result = sandbox.execute(update_remote, timeout_seconds=30)
    except Exception as e:
        logger.warning("refresh_gh_token_git_remote_exec_failed", run_id=run_id, error=str(e))
        return

    if result.exit_code != 0:
        logger.warning(
            "refresh_gh_token_git_remote_update_failed",
            run_id=run_id,
            stderr=result.stderr,
            exit_code=result.exit_code,
        )
