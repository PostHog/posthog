from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.error_tracking.backend.temporal.repo_paths.types import (
    BUDGET_EXHAUSTED_OUTCOME,
    RepoPathsWorkflowInputs,
    StoreReleaseFileListInputs,
)

WORKFLOW_NAME = "error-tracking-repo-paths"

ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)
# Longer than the git fetch timeout, so that git times out first and the attempt reports why.
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)
# The fetch budget has an hourly limit, so the deferrals together wait longer than one hour.
BUDGET_DEFERRALS = 6
BUDGET_DEFERRAL_DELAY = timedelta(minutes=15)
BUDGET_DEFERRAL_JITTER_SECONDS = 300


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingRepoPathsWorkflow(PostHogWorkflow):
    inputs_cls = RepoPathsWorkflowInputs

    @staticmethod
    def workflow_id_for(team_id: int, slug: str, commit: str) -> str:
        # Keyed by commit, not by release: services of one monorepo release the same commit, and
        # they share one run.
        return f"{WORKFLOW_NAME}:{team_id}:{slug}:{commit}"

    @workflow.run
    async def run(self, inputs: RepoPathsWorkflowInputs) -> str:
        for _ in range(BUDGET_DEFERRALS):
            outcome = await self._store(inputs, last_try=False)
            if outcome != BUDGET_EXHAUSTED_OUTCOME:
                return outcome
            jitter = timedelta(seconds=workflow.random().uniform(0, BUDGET_DEFERRAL_JITTER_SECONDS))
            await workflow.sleep(BUDGET_DEFERRAL_DELAY + jitter)
        return await self._store(inputs, last_try=True)

    async def _store(self, inputs: RepoPathsWorkflowInputs, *, last_try: bool) -> str:
        return await workflow.execute_activity(
            "store_release_file_list_activity",
            StoreReleaseFileListInputs(team_id=inputs.team_id, release_id=inputs.release_id, last_try=last_try),
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
