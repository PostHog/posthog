"""Triggers for the single-turn `ReviewPRWorkflow`.

Two entry points drive the **same** workflow:
- `execute_review_pr_workflow` — **blocking** (`execute_workflow`), returns the `ReviewReport` id.
  Used by the `run_review` management command so the CLI eval loop stays intact: run, see the
  outcome, read the report (stage progress streams in the worker log via `workflow.logger`).
- `start_review_pr_workflow` — **non-blocking** (`start_workflow`), returns the workflow id. Used by
  the production label trigger endpoint, which fires and forgets (the review runs in the worker; the
  report id is created when the run's fetch activity executes).
"""

import asyncio
import logging

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models.team.team import Team
from posthog.temporal.common.client import sync_connect

from products.review_hog.backend.reviewer.tools.github_meta import PRParser
from products.review_hog.backend.temporal.types import ReviewPRWorkflowInputs, review_pr_workflow_id

logger = logging.getLogger(__name__)

# Retry the whole review once on a hard failure; the re-run resumes (reuses persisted
# chunk/analysis/perspective rows for the same head) rather than redoing the work.
_PARENT_RETRY = RetryPolicy(maximum_attempts=2)


def _build_inputs(
    *, pr_url: str, team_id: int, user_id: int, publish: bool, acting_user_id: int | None
) -> tuple[ReviewPRWorkflowInputs, str]:
    """Parse the PR URL, validate the team, and build the workflow inputs + deterministic id.

    `owner` / `repo` / `pr_number` are parsed here so the workflow stays free of the GitHub-URL
    dependency and both triggers share the deterministic per-PR workflow id.
    """
    pr_info = PRParser().parse_github_pr_url(pr_url)
    owner, repo, pr_number = str(pr_info["owner"]), str(pr_info["repo"]), int(pr_info["pr_number"])
    Team.objects.get(id=team_id)  # fail fast if the team doesn't exist

    inputs = ReviewPRWorkflowInputs(
        team_id=team_id,
        user_id=user_id,
        pr_url=pr_url,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        publish=publish,
        acting_user_id=acting_user_id,
    )
    workflow_id = review_pr_workflow_id(team_id=team_id, owner=owner, repo=repo, pr_number=pr_number)
    return inputs, workflow_id


def execute_review_pr_workflow(
    *, pr_url: str, team_id: int, user_id: int, publish: bool = False, acting_user_id: int | None = None
) -> str:
    """Start `ReviewPRWorkflow`, block until it completes, and return the `ReviewReport` id.

    `team_id` / `user_id` are explicit identity (the team the review persists under; the user the
    sandbox tasks run as). `publish` defaults off so a CLI run never posts unless asked.
    `acting_user_id` pins whose enabled perspectives drive the review (the eval passes the run user
    so it doesn't depend on the PR author being a PostHog user).
    """
    inputs, workflow_id = _build_inputs(
        pr_url=pr_url, team_id=team_id, user_id=user_id, publish=publish, acting_user_id=acting_user_id
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
    *, pr_url: str, team_id: int, user_id: int, publish: bool, acting_user_id: int | None = None
) -> str:
    """Start `ReviewPRWorkflow` without blocking and return the workflow id.

    For the production label trigger: the request thread returns immediately while the review runs
    in the worker. `publish` is required (the caller decides explicitly). Safe to call from a
    synchronous DRF action — `sync_connect()` is `@async_to_sync` and the start is wrapped likewise.
    `acting_user_id` defaults None so the workflow resolves the PR author itself (the trigger has not
    fetched the PR, so it cannot know the author).

    Re-triggering the same PR while a review is in flight (e.g. a push fires `synchronize`) joins the
    running workflow via `USE_EXISTING` rather than raising `WorkflowAlreadyStartedError` — so the
    endpoint never 500s on a normal push. (Re-reviewing a mid-flight new head is the loop's job.)
    """
    inputs, workflow_id = _build_inputs(
        pr_url=pr_url, team_id=team_id, user_id=user_id, publish=publish, acting_user_id=acting_user_id
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
