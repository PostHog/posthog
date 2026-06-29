"""Workflow-level tests for the ReviewHog Temporal pipeline.

Activities are replaced with `@activity.defn` stand-ins (matching the real activity names) so these
exercise the real orchestration + the real fan-out children without touching the DB or a sandbox.
"""

import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.review_hog.backend.temporal.activities import (
    AnalyzeChunkInput,
    DedupResult,
    LoadedPerspectiveDTO,
    LoadedValidationSkillDTO,
    PublishInput,
    ResolveActingUserResult,
    ReviewChunkInput,
    ReviewMeta,
    ValidateIssueInput,
    ValidateIssueResult,
)
from products.review_hog.backend.temporal.types import ReviewPRWorkflowInputs
from products.review_hog.backend.temporal.workflow import (
    AnalyzeChunksInputs,
    AnalyzeChunksWorkflow,
    ReviewPerspectivesWorkflow,
    ReviewPRWorkflow,
    ValidateIssuesInputs,
    ValidateIssuesWorkflow,
)


def _stage_kwargs() -> dict:
    return {
        "team_id": 1,
        "user_id": 2,
        "report_id": "rep-1",
        "head_sha": "sha1",
        "repository": "o/r",
        "branch": "feat",
        "run_index": 1,
    }


async def _run_full_review_pr_workflow(
    *, publish: bool, already_published: bool = False, acting_user_id: int | None = 3
) -> dict:
    """Run `ReviewPRWorkflow` end-to-end with activity stand-ins; record what fanned out + published.

    `already_published` drives the fetch stand-in's `ReviewMeta.already_published` to exercise the
    parent's early-exit gate (a re-trigger at an already-published head). `acting_user_id` drives the
    resolve stand-in: None means the PR author maps to no PostHog user, so the parent skips the review.
    """
    split_calls: list[int] = []
    analyze_calls: list[int] = []
    review_calls: list[tuple[int, int]] = []
    validate_calls: list[str] = []
    publish_calls: list[int] = []

    @activity.defn(name="validate_github_integration_activity")
    async def validate_integration(input) -> None:
        return None

    @activity.defn(name="fetch_pr_data_activity")
    async def fetch(input) -> ReviewMeta:
        return ReviewMeta(
            report_id="rep-1",
            head_sha="sha1",
            branch="feat",
            repository="o/r",
            run_index=1,
            snapshotted=not already_published,
            already_published=already_published,
            new_comment_count=0,
            author_login="octocat",
        )

    @activity.defn(name="resolve_acting_user_activity")
    async def resolve_acting_user(input) -> ResolveActingUserResult:
        return ResolveActingUserResult(acting_user_id=acting_user_id)

    @activity.defn(name="sync_review_skills_activity")
    async def sync_skills(input) -> None:
        return None

    @activity.defn(name="generate_schemas_activity")
    async def gen_schemas(input) -> None:
        return None

    @activity.defn(name="split_chunks_activity")
    async def split(input) -> list[int]:
        split_calls.append(1)
        return [1, 2]

    @activity.defn(name="load_perspectives_activity")
    async def load_perspectives(input) -> list[LoadedPerspectiveDTO]:
        return [
            LoadedPerspectiveDTO(pass_number=1, skill_name="s-logic", version=1),
            LoadedPerspectiveDTO(pass_number=2, skill_name="s-sec", version=1),
            LoadedPerspectiveDTO(pass_number=3, skill_name="s-perf", version=1),
        ]

    @activity.defn(name="analyze_chunk_activity")
    async def analyze(input: AnalyzeChunkInput) -> bool:
        analyze_calls.append(input.chunk_id)
        return True

    @activity.defn(name="review_chunk_activity")
    async def review(input: ReviewChunkInput) -> bool:
        review_calls.append((input.pass_number, input.chunk_id))
        return True

    @activity.defn(name="combine_and_clean_activity")
    async def combine(input) -> list[str]:
        return ["issue-json"]

    @activity.defn(name="dedup_activity")
    async def dedup(input) -> DedupResult:
        return DedupResult(issues_json=["issue-json"], findings_count=1)

    @activity.defn(name="load_validation_skill_activity")
    async def load_validation(input) -> LoadedValidationSkillDTO:
        return LoadedValidationSkillDTO(skill_name="s-val", version=1)

    @activity.defn(name="validate_issue_activity")
    async def validate_issue(input: ValidateIssueInput) -> ValidateIssueResult:
        validate_calls.append(input.issue_json)
        return ValidateIssueResult(issue_id="1-1-1", validation_json="vj")

    @activity.defn(name="build_body_activity")
    async def build_body(input) -> None:
        return None

    @activity.defn(name="publish_review_activity")
    async def publish_act(input: PublishInput) -> None:
        publish_calls.append(input.pr_number)
        return None

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[
                ReviewPRWorkflow,
                AnalyzeChunksWorkflow,
                ReviewPerspectivesWorkflow,
                ValidateIssuesWorkflow,
            ],
            activities=[
                validate_integration,
                fetch,
                resolve_acting_user,
                sync_skills,
                gen_schemas,
                split,
                load_perspectives,
                analyze,
                review,
                combine,
                dedup,
                load_validation,
                validate_issue,
                build_body,
                publish_act,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ReviewPRWorkflow.run,
                ReviewPRWorkflowInputs(
                    team_id=1, user_id=2, pr_url="u", owner="o", repo="r", pr_number=7, publish=publish
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    return {
        "result": result,
        "split": split_calls,
        "analyze": analyze_calls,
        "review": review_calls,
        "validate": validate_calls,
        "publish": publish_calls,
    }


@pytest.mark.asyncio
async def test_review_pr_workflow_runs_all_stages_and_fans_out():
    recorded = await _run_full_review_pr_workflow(publish=False)
    assert recorded["result"] == "rep-1"
    # The analyze child fans out one activity per chunk; review fans out per (perspective × chunk).
    assert sorted(recorded["analyze"]) == [1, 2]
    assert len(recorded["review"]) == 6  # 3 perspectives × 2 chunks
    assert recorded["validate"] == ["issue-json"]  # one post-dedup issue
    assert recorded["publish"] == []  # publish=False → never posts to GitHub


@pytest.mark.asyncio
async def test_review_pr_workflow_publishes_only_when_publish_true():
    recorded = await _run_full_review_pr_workflow(publish=True)
    assert recorded["publish"] == [7]  # publish=True → posts the review back to the PR


@pytest.mark.asyncio
async def test_review_pr_workflow_early_exits_when_already_published():
    # A re-trigger at an already-published head: the gate returns the report id without running any
    # downstream stage — no re-chunk/analyze/review/dedup/validate and no re-publish.
    recorded = await _run_full_review_pr_workflow(publish=True, already_published=True)
    assert recorded["result"] == "rep-1"
    assert recorded["split"] == []
    assert recorded["analyze"] == []
    assert recorded["review"] == []
    assert recorded["validate"] == []
    assert recorded["publish"] == []


@pytest.mark.asyncio
async def test_review_pr_workflow_skips_when_author_maps_to_no_user():
    # Unmapped PR author → no perspectives → the gate returns before any sandbox spend and never
    # publishes. Guards against dropping the gate (which would review non-PostHog authors' PRs empty).
    recorded = await _run_full_review_pr_workflow(publish=True, acting_user_id=None)
    assert recorded["result"] == "rep-1"
    assert recorded["split"] == []
    assert recorded["analyze"] == []
    assert recorded["review"] == []
    assert recorded["validate"] == []
    assert recorded["publish"] == []


@pytest.mark.asyncio
async def test_analyze_chunks_workflow_is_best_effort_on_unit_failure():
    @activity.defn(name="analyze_chunk_activity")
    async def analyze(input: AnalyzeChunkInput) -> bool:
        if input.chunk_id == 2:
            raise RuntimeError("sandbox boom")
        return True

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[AnalyzeChunksWorkflow],
            activities=[analyze],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            analyzed = await env.client.execute_workflow(
                AnalyzeChunksWorkflow.run,
                AnalyzeChunksInputs(**_stage_kwargs(), chunk_ids=[1, 2, 3]),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    # 1 of 3 fails (33%, under the 70% floor): the workflow returns the survivors, not a failure.
    assert analyzed == 2


@pytest.mark.asyncio
async def test_analyze_chunks_workflow_fails_above_failure_floor():
    # 3 of 4 fail (75%, over the 70% floor): a near-total wipeout fails the run loudly instead of
    # finalizing an empty review as success.
    @activity.defn(name="analyze_chunk_activity")
    async def analyze(input: AnalyzeChunkInput) -> bool:
        if input.chunk_id in (1, 2, 3):
            raise RuntimeError("sandbox boom")
        return True

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[AnalyzeChunksWorkflow],
            activities=[analyze],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    AnalyzeChunksWorkflow.run,
                    AnalyzeChunksInputs(**_stage_kwargs(), chunk_ids=[1, 2, 3, 4]),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )


@pytest.mark.asyncio
async def test_validate_issues_workflow_collects_kept_drops_skips():
    @activity.defn(name="load_validation_skill_activity")
    async def load_validation(input) -> LoadedValidationSkillDTO:
        return LoadedValidationSkillDTO(skill_name="s-val", version=1)

    @activity.defn(name="validate_issue_activity")
    async def validate_issue(input: ValidateIssueInput) -> ValidateIssueResult:
        if "drop" in input.issue_json:
            return ValidateIssueResult(issue_id="dropped", validation_json=None)
        return ValidateIssueResult(issue_id="kept", validation_json="vj")

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ValidateIssuesWorkflow],
            activities=[load_validation, validate_issue],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            validations = await env.client.execute_workflow(
                ValidateIssuesWorkflow.run,
                ValidateIssuesInputs(**_stage_kwargs(), issues_json=["keep", "drop"]),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    # A None verdict is a deliberate skip (e.g. an unresolved chunk), not a failure: it's dropped from
    # the result but does NOT count toward the failure floor.
    assert validations == {"kept": "vj"}


@pytest.mark.asyncio
async def test_validate_issues_workflow_fails_above_failure_floor():
    # Every validate unit raises a genuine sandbox failure (100%, over the 70% floor) — distinct from
    # the None skip above — so the workflow fails loudly instead of returning an empty verdict set.
    @activity.defn(name="load_validation_skill_activity")
    async def load_validation(input) -> LoadedValidationSkillDTO:
        return LoadedValidationSkillDTO(skill_name="s-val", version=1)

    @activity.defn(name="validate_issue_activity")
    async def validate_issue(input: ValidateIssueInput) -> ValidateIssueResult:
        raise RuntimeError("sandbox boom")

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ValidateIssuesWorkflow],
            activities=[load_validation, validate_issue],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    ValidateIssuesWorkflow.run,
                    ValidateIssuesInputs(**_stage_kwargs(), issues_json=["a", "b"]),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
