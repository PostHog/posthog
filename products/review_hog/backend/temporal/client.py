"""Triggers for the single-turn `ReviewPRWorkflow`.

Two entry points drive the **same** workflow:
- `execute_review_pr_workflow` — **blocking** (`execute_workflow`), returns the `ReviewReport` id.
  Used by the `run_review` management command so the CLI eval loop stays intact: run, see the
  outcome, read the report (stage progress streams in the worker log via `workflow.logger`).
- `start_review_pr_workflow` — **non-blocking** (`start_workflow`), returns the workflow id. Used by
  the production triggers (the label endpoint and the inbox TaskRun-completion receiver), which fire
  and forget (the review runs in the worker; the report id is created when the run's fetch activity
  executes).

The review target is either a PR (`pr_url`) or a pushed branch with no PR yet
(`repository` + `head_branch`) — exactly one, validated in `_build_inputs`.
"""

import asyncio
import logging

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models.team.team import Team
from posthog.temporal.common.client import sync_connect

from products.review_hog.backend.reviewer.tools.github_meta import PRParser
from products.review_hog.backend.temporal.types import (
    TRIGGER_MANUAL,
    ReviewPRWorkflowInputs,
    review_branch_workflow_id,
    review_pr_workflow_id,
)

logger = logging.getLogger(__name__)

# Retry the whole review once on a hard failure; the re-run resumes (reuses persisted
# chunk/perspective/verdict rows for the same head) rather than redoing the work.
_PARENT_RETRY = RetryPolicy(maximum_attempts=2)


def _build_inputs(
    *,
    team_id: int,
    user_id: int,
    publish: bool,
    acting_user_id: int | None,
    trigger_source: str,
    signal_report_id: str | None,
    pr_url: str | None,
    repository: str | None,
    head_branch: str | None,
) -> tuple[ReviewPRWorkflowInputs, str]:
    """Validate the review target, the team, and build the workflow inputs + deterministic id.

    `owner` / `repo` / `pr_number` are parsed here so the workflow stays free of the GitHub-URL
    dependency and every trigger shares the deterministic per-target workflow id. Exactly one target
    shape is required: a PR (`pr_url`) or a branch (`repository` + `head_branch`).
    """
    if (pr_url is None) == (head_branch is None):
        raise ValueError("Exactly one review target is required: pr_url, or repository + head_branch")
    Team.objects.get(id=team_id)  # fail fast if the team doesn't exist

    if pr_url is not None:
        pr_info = PRParser().parse_github_pr_url(pr_url)
        owner, repo, pr_number = str(pr_info["owner"]), str(pr_info["repo"]), int(pr_info["pr_number"])
        workflow_id = review_pr_workflow_id(team_id=team_id, owner=owner, repo=repo, pr_number=pr_number)
    else:
        owner, _, repo = (repository or "").partition("/")
        if not owner or not repo or "/" in repo:
            raise ValueError(f"Branch targets need a repository in 'owner/repo' form, got {repository!r}")
        pr_number = None
        workflow_id = review_branch_workflow_id(team_id=team_id, owner=owner, repo=repo, head_branch=head_branch or "")

    inputs = ReviewPRWorkflowInputs(
        team_id=team_id,
        user_id=user_id,
        pr_url=pr_url,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        publish=publish,
        acting_user_id=acting_user_id,
        trigger_source=trigger_source,
        signal_report_id=signal_report_id,
        head_branch=head_branch,
    )
    return inputs, workflow_id


def execute_review_pr_workflow(
    *,
    pr_url: str | None = None,
    team_id: int,
    user_id: int,
    publish: bool = False,
    acting_user_id: int | None = None,
    trigger_source: str = TRIGGER_MANUAL,
    signal_report_id: str | None = None,
    repository: str | None = None,
    head_branch: str | None = None,
) -> str:
    """Start `ReviewPRWorkflow`, block until it completes, and return the `ReviewReport` id.

    `team_id` / `user_id` are explicit identity (the team the review persists under; the user the
    sandbox tasks run as). `publish` defaults off so a CLI run never posts unless asked.
    `acting_user_id` pins whose enabled perspectives drive the review (the eval passes the run user
    so it doesn't depend on the PR author being a PostHog user).
    """
    inputs, workflow_id = _build_inputs(
        team_id=team_id,
        user_id=user_id,
        publish=publish,
        acting_user_id=acting_user_id,
        trigger_source=trigger_source,
        signal_report_id=signal_report_id,
        pr_url=pr_url,
        repository=repository,
        head_branch=head_branch,
    )

    # `sync_connect` is @async_to_sync, so call it from sync code (outside any running loop); the
    # blocking workflow execution then runs inside `asyncio.run`.
    client = sync_connect()
    logger.info(f"Running ReviewPRWorkflow {workflow_id} on {settings.VIDEO_EXPORT_TASK_QUEUE} (publish={publish})")
    return asyncio.run(
        client.execute_workflow(
            "review-pr",
            inputs,
            id=workflow_id,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            # A new turn may start once the prior one finishes (the living-report re-review);
            # re-triggering while a run is in flight joins that run rather than erroring.
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            retry_policy=_PARENT_RETRY,
        )
    )


def start_review_pr_workflow(
    *,
    pr_url: str | None = None,
    team_id: int,
    user_id: int,
    publish: bool,
    acting_user_id: int | None = None,
    trigger_source: str = TRIGGER_MANUAL,
    signal_report_id: str | None = None,
    repository: str | None = None,
    head_branch: str | None = None,
) -> str:
    """Start `ReviewPRWorkflow` without blocking and return the workflow id.

    For the production triggers: the caller returns immediately while the review runs in the worker.
    `publish` is required (the caller decides explicitly). Safe to call from a synchronous DRF action
    or a `post_save` receiver — `sync_connect()` is `@async_to_sync` and the start is wrapped
    likewise. `acting_user_id` defaults None so the workflow resolves the PR author itself (the label
    trigger has not fetched the PR, so it cannot know the author); the inbox trigger sets it.

    Re-triggering the same target while a review is in flight (e.g. a push fires `synchronize`) joins
    the running workflow via `USE_EXISTING` rather than raising `WorkflowAlreadyStartedError` — so
    the trigger never errors on a normal push. (Re-reviewing a mid-flight new head is the loop's job.)
    """
    inputs, workflow_id = _build_inputs(
        team_id=team_id,
        user_id=user_id,
        publish=publish,
        acting_user_id=acting_user_id,
        trigger_source=trigger_source,
        signal_report_id=signal_report_id,
        pr_url=pr_url,
        repository=repository,
        head_branch=head_branch,
    )

    client = sync_connect()
    logger.info(f"Starting ReviewPRWorkflow {workflow_id} on {settings.VIDEO_EXPORT_TASK_QUEUE} (publish={publish})")
    async_to_sync(client.start_workflow)(
        "review-pr",
        inputs,
        id=workflow_id,
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        retry_policy=_PARENT_RETRY,
    )
    return workflow_id
