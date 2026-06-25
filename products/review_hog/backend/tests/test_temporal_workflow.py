"""Workflow-level tests for the ReviewHog Temporal pipeline.

Activities are replaced with `@activity.defn` stand-ins (matching the real activity names) so these
exercise the real orchestration + the real fan-out children without touching the DB or a sandbox.
"""

import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.review_hog.backend.temporal.activities import (
    AnalyzeChunkInput,
    DedupResult,
    LoadedPerspectiveDTO,
    LoadedValidationSkillDTO,
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
    }


@pytest.mark.asyncio
async def test_review_pr_workflow_runs_all_stages_and_fans_out():
    analyze_calls: list[int] = []
    review_calls: list[tuple[int, int]] = []
    validate_calls: list[str] = []

    @activity.defn(name="validate_github_integration_activity")
    async def validate_integration(input) -> None:
        return None

    @activity.defn(name="fetch_pr_data_activity")
    async def fetch(input) -> ReviewMeta:
        return ReviewMeta(report_id="rep-1", head_sha="sha1", branch="feat", repository="o/r", snapshotted=True)

    @activity.defn(name="sync_review_skills_activity")
    async def sync_skills(input) -> None:
        return None

    @activity.defn(name="generate_schemas_activity")
    async def gen_schemas(input) -> None:
        return None

    @activity.defn(name="split_chunks_activity")
    async def split(input) -> list[int]:
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
    async def publish(input) -> None:
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
                publish,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ReviewPRWorkflow.run,
                ReviewPRWorkflowInputs(team_id=1, user_id=2, pr_url="u", owner="o", repo="r", pr_number=7),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result == "rep-1"
    # The analyze child fans out one activity per chunk; review fans out per (perspective × chunk).
    assert sorted(analyze_calls) == [1, 2]
    assert len(review_calls) == 6  # 3 perspectives × 2 chunks
    assert validate_calls == ["issue-json"]  # one post-dedup issue


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

    # Chunk 2 fails after its retries; the workflow returns the survivors instead of failing the turn.
    assert analyzed == 2


@pytest.mark.asyncio
async def test_validate_issues_workflow_collects_kept_drops_failures():
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

    # Only the issue with a verdict is collected; the failed/None one is dropped.
    assert validations == {"kept": "vj"}
