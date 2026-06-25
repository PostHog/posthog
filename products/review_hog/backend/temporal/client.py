"""Trigger for the single-turn `ReviewPRWorkflow` (used by the `run_review` management command).

Blocks until the workflow finishes (`execute_workflow`) and returns the report id, so the CLI eval
loop stays intact — run, see the outcome, read the report — while the stage-by-stage progress streams
in the worker log via `workflow.logger`.
"""

import asyncio
import logging

from django.conf import settings

from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.models.team.team import Team
from posthog.temporal.common.client import sync_connect

from products.review_hog.backend.reviewer.tools.github_meta import PRParser
from products.review_hog.backend.temporal.types import ReviewPRWorkflowInputs, review_pr_workflow_id

logger = logging.getLogger(__name__)


def execute_review_pr_workflow(*, pr_url: str, team_id: int, user_id: int) -> str:
    """Start `ReviewPRWorkflow`, block until it completes, and return the `ReviewReport` id.

    `team_id` / `user_id` are explicit identity (the team the review persists under; the user the
    sandbox tasks run as). `owner` / `repo` / `pr_number` are parsed here so the workflow stays free
    of the GitHub-URL dependency and shares the deterministic per-PR workflow id.
    """
    pr_info = PRParser().parse_github_pr_url(pr_url)
    owner, repo, pr_number = str(pr_info["owner"]), str(pr_info["repo"]), int(pr_info["pr_number"])
    Team.objects.get(id=team_id)  # fail fast if the team doesn't exist

    inputs = ReviewPRWorkflowInputs(
        team_id=team_id, user_id=user_id, pr_url=pr_url, owner=owner, repo=repo, pr_number=pr_number
    )
    workflow_id = review_pr_workflow_id(team_id=team_id, owner=owner, repo=repo, pr_number=pr_number)

    # `sync_connect` is @async_to_sync, so call it from sync code (outside any running loop); the
    # blocking workflow execution then runs inside `asyncio.run`.
    client = sync_connect()
    logger.info(f"Starting ReviewPRWorkflow {workflow_id} on {settings.VIDEO_EXPORT_TASK_QUEUE}")
    return asyncio.run(
        client.execute_workflow(
            "review-pr",
            inputs,
            id=workflow_id,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            # A new turn may start once the prior one finishes (the living-report re-review), but a
            # second concurrent run of the same PR is rejected.
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            # Retry the whole review once on a hard failure; the re-run resumes (reuses persisted
            # chunk/analysis/perspective rows for the same head) rather than redoing the work.
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
    )
