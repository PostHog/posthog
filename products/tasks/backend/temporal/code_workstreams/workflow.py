import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.tasks.backend.temporal.code_workstreams.activities.discover_branch_prs import (
    DiscoverBranchPrsInput,
    DiscoverBranchPrsOutput,
    discover_branch_prs,
)
from products.tasks.backend.temporal.code_workstreams.activities.list_active_teams import (
    ListActiveCodeTeamsOutput,
    list_active_code_teams,
)
from products.tasks.backend.temporal.code_workstreams.activities.load_pr_urls import (
    LoadTeamPrUrlsInput,
    LoadTeamPrUrlsOutput,
    load_team_pr_urls,
)
from products.tasks.backend.temporal.code_workstreams.activities.poll_pull_requests import (
    PollTeamPullRequestsInput,
    poll_team_pull_requests,
)
from products.tasks.backend.temporal.code_workstreams.activities.rebuild_workstreams import (
    RebuildTeamWorkstreamsInput,
    rebuild_team_workstreams,
)
from products.tasks.backend.temporal.code_workstreams.constants import (
    MAX_PRS_PER_TEAM_PER_CYCLE,
    TEAM_FANOUT_CONCURRENCY,
)


@dataclass
class EvaluateTeamCodeWorkstreamsInput:
    team_id: int


@dataclass
class EvaluateCodeWorkstreamsInput:
    pass


@workflow.defn(name="evaluate-team-code-workstreams")
class EvaluateTeamCodeWorkstreamsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> EvaluateTeamCodeWorkstreamsInput:
        loaded = json.loads(inputs[0])
        return EvaluateTeamCodeWorkstreamsInput(team_id=loaded["team_id"])

    @workflow.run
    async def run(self, input: EvaluateTeamCodeWorkstreamsInput) -> None:
        pr_urls: LoadTeamPrUrlsOutput = await workflow.execute_activity(
            load_team_pr_urls,
            LoadTeamPrUrlsInput(team_id=input.team_id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        prs = list(pr_urls.prs)

        # Branch discovery surfaces PRs whose run never wrote output.pr_url. It calls GitHub, so it
        # runs as its own heartbeated activity rather than blocking the DB-only load step.
        budget = MAX_PRS_PER_TEAM_PER_CYCLE - len(prs)
        if budget > 0:
            discovered: DiscoverBranchPrsOutput = await workflow.execute_activity(
                discover_branch_prs,
                DiscoverBranchPrsInput(
                    team_id=input.team_id,
                    known_pr_urls=[pr.pr_url for pr in prs],
                    budget=budget,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            prs.extend(discovered.prs)

        if prs:
            await workflow.execute_activity(
                poll_team_pull_requests,
                PollTeamPullRequestsInput(team_id=input.team_id, prs=prs),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        await workflow.execute_activity(
            rebuild_team_workstreams,
            RebuildTeamWorkstreamsInput(team_id=input.team_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn(name="evaluate-code-workstreams")
class EvaluateCodeWorkstreamsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> EvaluateCodeWorkstreamsInput:
        return EvaluateCodeWorkstreamsInput()

    @workflow.run
    async def run(self, input: EvaluateCodeWorkstreamsInput) -> None:
        active: ListActiveCodeTeamsOutput = await workflow.execute_activity(
            list_active_code_teams,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not active.team_ids:
            return

        parent_id = workflow.info().workflow_id
        semaphore = asyncio.Semaphore(TEAM_FANOUT_CONCURRENCY)

        async def evaluate_team(team_id: int) -> None:
            async with semaphore:
                await workflow.execute_child_workflow(
                    EvaluateTeamCodeWorkstreamsWorkflow.run,
                    EvaluateTeamCodeWorkstreamsInput(team_id=team_id),
                    id=f"{parent_id}-team-{team_id}",
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        results = await asyncio.gather(
            *(evaluate_team(team_id) for team_id in active.team_ids),
            return_exceptions=True,
        )
        failures = [r for r in results if isinstance(r, Exception)]
        if failures:
            workflow.logger.warning(
                "code_workstreams_dispatch_partial_failures",
                total=len(active.team_ids),
                failures=len(failures),
            )
