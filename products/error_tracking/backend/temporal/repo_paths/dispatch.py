"""Starts the workflow that stores the file list of a release commit."""

import asyncio
from datetime import timedelta

from django.conf import settings

from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from products.error_tracking.backend.logic.repo_paths.release_repo import (
    ReleaseRepo,
    parse_release_repo,
    repo_paths_enabled,
)
from products.error_tracking.backend.models import ErrorTrackingRelease
from products.error_tracking.backend.temporal.repo_paths.types import RepoPathsWorkflowInputs
from products.error_tracking.backend.temporal.repo_paths.workflow import WORKFLOW_NAME, ErrorTrackingRepoPathsWorkflow

# Bounds the connect handshake and the start, so the Celery retry handles a stalled Temporal.
DISPATCH_TIMEOUT = timedelta(seconds=10)


def start_repo_paths_workflow(*, team_id: int, release_id: str) -> None:
    """Start the job for one release. Does nothing for a team outside the flag.

    Raises when Temporal does not accept the start, so the caller's retry starts it again.
    """
    if not repo_paths_enabled(team_id):
        return
    release = ErrorTrackingRelease.objects.filter(team_id=team_id, id=release_id).first()
    repo = parse_release_repo(release.metadata) if release is not None else None
    if not isinstance(repo, ReleaseRepo):
        return
    workflow_id = ErrorTrackingRepoPathsWorkflow.workflow_id_for(team_id, str(repo.slug), repo.commit)
    asyncio.run(_start(RepoPathsWorkflowInputs(team_id=team_id, release_id=release_id), workflow_id))


async def _start(inputs: RepoPathsWorkflowInputs, workflow_id: str) -> None:
    temporal = await asyncio.wait_for(async_connect(), timeout=DISPATCH_TIMEOUT.total_seconds())
    try:
        await asyncio.wait_for(
            temporal.start_workflow(
                WORKFLOW_NAME,
                inputs,
                id=workflow_id,
                task_queue=settings.ERROR_TRACKING_REPO_PATHS_TASK_QUEUE,
                # A release of a commit whose run is still open joins that run. After the run closes,
                # the next release of the commit starts a new one. That run fetches again only when no
                # list is stored: the last run stored nothing, or retention removed the list.
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            ),
            timeout=DISPATCH_TIMEOUT.total_seconds(),
        )
    except WorkflowAlreadyStartedError:
        pass
