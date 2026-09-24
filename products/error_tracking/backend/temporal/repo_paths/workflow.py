from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.error_tracking.backend.temporal.repo_paths.types import RepoPathsWorkflowInputs

WORKFLOW_NAME = "error-tracking-repo-paths"

ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)
# Longer than the git fetch timeout, so that git times out first and the attempt reports why.
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)


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
        return await workflow.execute_activity(
            "store_release_file_list_activity",
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
