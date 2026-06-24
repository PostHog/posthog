import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.tasks.backend.temporal.code_workstreams.activities.discover_branch_prs import DiscoverBranchPrsOutput
from products.tasks.backend.temporal.code_workstreams.activities.list_active_teams import ListActiveCodeTeamsOutput
from products.tasks.backend.temporal.code_workstreams.activities.load_pr_urls import (
    LoadTeamPrUrlsInput,
    LoadTeamPrUrlsOutput,
    PrRef,
)
from products.tasks.backend.temporal.code_workstreams.activities.poll_pull_requests import PollTeamPullRequestsOutput
from products.tasks.backend.temporal.code_workstreams.activities.rebuild_workstreams import RebuildTeamWorkstreamsOutput
from products.tasks.backend.temporal.code_workstreams.workflow import (
    EvaluateCodeWorkstreamsInput,
    EvaluateCodeWorkstreamsWorkflow,
    EvaluateTeamCodeWorkstreamsInput,
    EvaluateTeamCodeWorkstreamsWorkflow,
)


def _team_pipeline_activities(calls: list[str]):
    @activity.defn(name="load_team_pr_urls")
    async def load(input) -> LoadTeamPrUrlsOutput:
        calls.append("load")
        return LoadTeamPrUrlsOutput(
            prs=[
                PrRef(pr_url="https://github.com/o/r/pull/1", github_integration_id=1, github_user_integration_id=None)
            ]
        )

    @activity.defn(name="discover_branch_prs")
    async def discover(input) -> DiscoverBranchPrsOutput:
        calls.append("discover")
        return DiscoverBranchPrsOutput(prs=[])

    @activity.defn(name="poll_team_pull_requests")
    async def poll(input) -> PollTeamPullRequestsOutput:
        calls.append("poll")
        return PollTeamPullRequestsOutput(polled=1, updated=1, rate_limited=False)

    @activity.defn(name="rebuild_team_workstreams")
    async def rebuild(input) -> RebuildTeamWorkstreamsOutput:
        calls.append("rebuild")
        return RebuildTeamWorkstreamsOutput(users=1, workstreams=2, pruned=0)

    return [load, discover, poll, rebuild]


@pytest.mark.asyncio
async def test_team_workflow_runs_pipeline_in_order():
    calls: list[str] = []
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[EvaluateTeamCodeWorkstreamsWorkflow],
            activities=_team_pipeline_activities(calls),
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                EvaluateTeamCodeWorkstreamsWorkflow.run,
                EvaluateTeamCodeWorkstreamsInput(team_id=1),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
    assert calls == ["load", "discover", "poll", "rebuild"]


@pytest.mark.asyncio
async def test_team_workflow_skips_poll_when_no_prs():
    calls: list[str] = []

    @activity.defn(name="load_team_pr_urls")
    async def load(input) -> LoadTeamPrUrlsOutput:
        calls.append("load")
        return LoadTeamPrUrlsOutput(prs=[])

    @activity.defn(name="discover_branch_prs")
    async def discover(input) -> DiscoverBranchPrsOutput:
        calls.append("discover")
        return DiscoverBranchPrsOutput(prs=[])

    @activity.defn(name="poll_team_pull_requests")
    async def poll(input) -> PollTeamPullRequestsOutput:
        calls.append("poll")
        return PollTeamPullRequestsOutput(polled=0, updated=0, rate_limited=False)

    @activity.defn(name="rebuild_team_workstreams")
    async def rebuild(input) -> RebuildTeamWorkstreamsOutput:
        calls.append("rebuild")
        return RebuildTeamWorkstreamsOutput(users=0, workstreams=0, pruned=0)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[EvaluateTeamCodeWorkstreamsWorkflow],
            activities=[load, discover, poll, rebuild],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                EvaluateTeamCodeWorkstreamsWorkflow.run,
                EvaluateTeamCodeWorkstreamsInput(team_id=1),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
    assert calls == ["load", "discover", "rebuild"]


@pytest.mark.asyncio
async def test_dispatcher_fans_out_per_team():
    started_teams: list[int] = []

    @activity.defn(name="list_active_code_teams")
    async def list_teams(input=None) -> ListActiveCodeTeamsOutput:
        return ListActiveCodeTeamsOutput(team_ids=[1, 2, 3], truncated=False)

    @activity.defn(name="load_team_pr_urls")
    async def load(input: LoadTeamPrUrlsInput) -> LoadTeamPrUrlsOutput:
        started_teams.append(input.team_id)
        return LoadTeamPrUrlsOutput(prs=[])

    @activity.defn(name="discover_branch_prs")
    async def discover(input) -> DiscoverBranchPrsOutput:
        return DiscoverBranchPrsOutput(prs=[])

    @activity.defn(name="poll_team_pull_requests")
    async def poll(input) -> PollTeamPullRequestsOutput:
        return PollTeamPullRequestsOutput(polled=0, updated=0, rate_limited=False)

    @activity.defn(name="rebuild_team_workstreams")
    async def rebuild(input) -> RebuildTeamWorkstreamsOutput:
        return RebuildTeamWorkstreamsOutput(users=0, workstreams=0, pruned=0)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[EvaluateCodeWorkstreamsWorkflow, EvaluateTeamCodeWorkstreamsWorkflow],
            activities=[list_teams, load, discover, poll, rebuild],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                EvaluateCodeWorkstreamsWorkflow.run,
                EvaluateCodeWorkstreamsInput(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
    assert sorted(started_teams) == [1, 2, 3]
