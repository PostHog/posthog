"""Workflow-level tests for the ReviewHog Temporal pipeline.

Activities are replaced with `@activity.defn` stand-ins (matching the real activity names) so these
exercise the real orchestration + the real fan-out children without touching the DB or a sandbox.
"""

import json
import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.review_hog.backend.reviewer.constants import BLIND_SPOT_PASS_NUMBER
from products.review_hog.backend.temporal.activities import (
    BuildBodyInput,
    DedupResult,
    LoadBlindSpotsInput,
    LoadedBlindSpotsSkillDTO,
    LoadedPerspectiveDTO,
    LoadedValidationSkillDTO,
    LoadPerspectivesInput,
    LoadValidationInput,
    PublishInput,
    ResolveActingUserResult,
    ReviewChunkInput,
    ReviewMeta,
    ValidateChunkInput,
    ValidateChunkResult,
)
from products.review_hog.backend.temporal.types import ReviewPRWorkflowInputs
from products.review_hog.backend.temporal.workflow import (
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
    *,
    publish: bool,
    already_published: bool = False,
    acting_user_id: int | None = 3,
    review_labeled_prs: bool = True,
    input_acting_user_id: int | None = None,
) -> dict:
    # Runs the real ReviewPRWorkflow with activity stand-ins, recording what fanned out + published.
    # already_published drives the early-exit gate; acting_user_id None means the author isn't a
    # PostHog user, so the workflow skips the review. review_labeled_prs is the author's label
    # opt-out; input_acting_user_id is the CLI override on the workflow input (the ungated path).
    split_calls: list[int] = []
    # Each review unit as (pass_number, chunk_id, blind_spot_check, skill_name, wave lens names) — the
    # blind-spot fields let the fan-out test pin the second round's routing contract.
    review_calls: list[tuple[int, int, bool, str, tuple[str, ...]]] = []
    validate_calls: list[int] = []
    publish_calls: list[int] = []
    # The urgency threshold each downstream consumer received (must be the resolve snapshot's value).
    threshold_calls: list[tuple[str, str]] = []
    # The user id the parent threads into the perspective / blind-spots / validation loads (should be
    # the RESOLVED value, not the None workflow input) — guards each per-user selection seam.
    load_user_ids: list[int | None] = []

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
        # A non-default threshold, so the threading asserts can't pass on the dataclass defaults.
        return ResolveActingUserResult(
            acting_user_id=acting_user_id, review_labeled_prs=review_labeled_prs, urgency_threshold="must_fix"
        )

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
    async def load_perspectives(input: LoadPerspectivesInput) -> list[LoadedPerspectiveDTO]:
        load_user_ids.append(input.acting_user_id)
        return [
            LoadedPerspectiveDTO(pass_number=1, skill_name="s-logic", version=1),
            LoadedPerspectiveDTO(pass_number=2, skill_name="s-sec", version=1),
            LoadedPerspectiveDTO(pass_number=3, skill_name="s-perf", version=1),
        ]

    @activity.defn(name="load_blind_spots_skill_activity")
    async def load_blind_spots(input: LoadBlindSpotsInput) -> LoadedBlindSpotsSkillDTO:
        load_user_ids.append(input.acting_user_id)
        return LoadedBlindSpotsSkillDTO(skill_name="s-blind", version=1)

    @activity.defn(name="review_chunk_activity")
    async def review(input: ReviewChunkInput) -> bool:
        review_calls.append(
            (
                input.pass_number,
                input.chunk_id,
                input.blind_spot_check,
                input.skill_name,
                tuple(p.skill_name for p in input.wave_perspectives),
            )
        )
        return True

    @activity.defn(name="combine_and_clean_activity")
    async def combine(input) -> list[str]:
        return ["issue-json"]

    @activity.defn(name="dedup_activity")
    async def dedup(input) -> DedupResult:
        # Two survivors in two different chunks, so validate fans out one warm session per chunk.
        return DedupResult(issues_json=[json.dumps({"id": "1-1-1"}), json.dumps({"id": "1-2-1"})], findings_count=2)

    @activity.defn(name="load_validation_skill_activity")
    async def load_validation(input: LoadValidationInput) -> LoadedValidationSkillDTO:
        load_user_ids.append(input.acting_user_id)
        return LoadedValidationSkillDTO(skill_name="s-val", version=1)

    @activity.defn(name="validate_chunk_activity")
    async def validate_chunk(input: ValidateChunkInput) -> ValidateChunkResult:
        validate_calls.append(input.chunk_id)
        return ValidateChunkResult(chunk_id=input.chunk_id, validated_count=len(input.issues_json))

    @activity.defn(name="build_body_activity")
    async def build_body(input: BuildBodyInput) -> None:
        threshold_calls.append(("body", input.urgency_threshold))
        return None

    @activity.defn(name="publish_review_activity")
    async def publish_act(input: PublishInput) -> None:
        publish_calls.append(input.pr_number)
        threshold_calls.append(("publish", input.urgency_threshold))
        return None

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[
                ReviewPRWorkflow,
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
                load_blind_spots,
                review,
                combine,
                dedup,
                load_validation,
                validate_chunk,
                build_body,
                publish_act,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ReviewPRWorkflow.run,
                ReviewPRWorkflowInputs(
                    team_id=1,
                    user_id=2,
                    pr_url="u",
                    owner="o",
                    repo="r",
                    pr_number=7,
                    publish=publish,
                    acting_user_id=input_acting_user_id,
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    return {
        "result": result,
        "split": split_calls,
        "review": review_calls,
        "validate": validate_calls,
        "publish": publish_calls,
        "load_user_ids": load_user_ids,
        "thresholds": threshold_calls,
    }


@pytest.mark.asyncio
async def test_review_pr_workflow_runs_all_stages_and_fans_out():
    recorded = await _run_full_review_pr_workflow(publish=False)
    assert recorded["result"] == "rep-1"
    # Review fans out per (perspective × chunk), then the always-on blind-spot check adds one unit
    # per chunk; validate fans out one warm session per chunk.
    wave = [c for c in recorded["review"] if not c[2]]
    blind = [c for c in recorded["review"] if c[2]]
    assert len(wave) == 6  # 3 perspectives × 2 chunks
    # The blind-spot round runs strictly after the wave: one unit per chunk, on the loaded
    # blind-spots skill, at the reserved pass number, told which lenses already ran.
    assert recorded["review"][:6] == wave
    assert sorted((p, c) for p, c, *_ in blind) == [(BLIND_SPOT_PASS_NUMBER, 1), (BLIND_SPOT_PASS_NUMBER, 2)]
    assert {c[3] for c in blind} == {"s-blind"}
    assert {c[4] for c in blind} == {("s-logic", "s-sec", "s-perf")}
    assert {c[4] for c in wave} == {()}  # the wave itself gets no cross-perspective context
    assert sorted(recorded["validate"]) == [1, 2]  # one session per chunk-with-issues
    assert recorded["publish"] == []  # publish=False → never posts to GitHub
    # The RESOLVED acting user (3 from the resolve stub), not the None workflow input, threads into
    # the perspective, blind-spots, and validation loads — the per-user selection seam for each.
    assert recorded["load_user_ids"] == [3, 3, 3]


@pytest.mark.asyncio
async def test_review_pr_workflow_publishes_only_when_publish_true():
    recorded = await _run_full_review_pr_workflow(publish=True)
    assert recorded["publish"] == [7]  # publish=True → posts the review back to the PR
    # The acting user's threshold snapshot (not the dataclass default) reaches both consumers, so
    # body counts and posted comments gate on the same set.
    assert recorded["thresholds"] == [("body", "must_fix"), ("publish", "must_fix")]


@pytest.mark.asyncio
async def test_review_pr_workflow_early_exits_when_already_published():
    # A re-trigger at an already-published head: the gate returns the report id without running any
    # downstream stage — no re-chunk/review/dedup/validate and no re-publish.
    recorded = await _run_full_review_pr_workflow(publish=True, already_published=True)
    assert recorded["result"] == "rep-1"
    assert recorded["split"] == []
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
    assert recorded["review"] == []
    assert recorded["validate"] == []
    assert recorded["publish"] == []


@pytest.mark.asyncio
async def test_review_pr_workflow_skips_when_author_opted_out_of_label_reviews():
    # The label trigger's per-author opt-out: an author who turned labeled-PR reviews off gets no
    # review and no publish — before any sandbox spend, like the unmapped-author gate.
    recorded = await _run_full_review_pr_workflow(publish=True, review_labeled_prs=False)
    assert recorded["result"] == "rep-1"
    assert recorded["split"] == []
    assert recorded["review"] == []
    assert recorded["publish"] == []


@pytest.mark.asyncio
async def test_review_pr_workflow_cli_override_ignores_label_opt_out():
    # An explicit CLI/eval invocation (acting-user override on the input) must run even when that
    # user opted out of the label trigger — the opt-out gates only the cloud path.
    recorded = await _run_full_review_pr_workflow(publish=False, review_labeled_prs=False, input_acting_user_id=3)
    assert recorded["split"] == [1]
    assert len(recorded["review"]) > 0


async def _run_validate_workflow(*, issues_json: list[str], validate_chunk) -> tuple[int, list]:
    """Run `ValidateIssuesWorkflow` with a stand-in chunk validator; return (result, recorded calls)."""

    @activity.defn(name="load_validation_skill_activity")
    async def load_validation(input) -> LoadedValidationSkillDTO:
        return LoadedValidationSkillDTO(skill_name="s-val", version=1)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ValidateIssuesWorkflow],
            activities=[load_validation, validate_chunk],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ValidateIssuesWorkflow.run,
                ValidateIssuesInputs(**_stage_kwargs(), issues_json=issues_json, acting_user_id=3),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
    return result


@pytest.mark.asyncio
async def test_validate_issues_workflow_fans_out_one_session_per_chunk():
    # Survivors are grouped by their chunk (id = "{pass}-{chunk}-{issue}"): one warm session per chunk,
    # its issues batched in. A malformed id is dropped from grouping, not sent to any session.
    calls: list[tuple[int, tuple[str, ...]]] = []

    @activity.defn(name="validate_chunk_activity")
    async def validate_chunk(input: ValidateChunkInput) -> ValidateChunkResult:
        calls.append((input.chunk_id, tuple(sorted(input.issues_json))))
        return ValidateChunkResult(chunk_id=input.chunk_id, validated_count=len(input.issues_json))

    issues = [
        json.dumps({"id": "1-1-1"}),  # chunk 1
        json.dumps({"id": "2-1-2"}),  # chunk 1 (different perspective)
        json.dumps({"id": "1-2-1"}),  # chunk 2
        "not-json",  # malformed → skipped
    ]
    await _run_validate_workflow(issues_json=issues, validate_chunk=validate_chunk)

    by_chunk = {chunk_id: set(issues_json) for chunk_id, issues_json in calls}
    assert set(by_chunk) == {1, 2}
    assert by_chunk[1] == {json.dumps({"id": "1-1-1"}), json.dumps({"id": "2-1-2"})}
    assert by_chunk[2] == {json.dumps({"id": "1-2-1"})}


@pytest.mark.asyncio
async def test_validate_issues_workflow_is_best_effort_on_chunk_failure():
    # One chunk of two fails (50%, under the 70% floor): the workflow returns the survivor count and
    # does NOT fail — a chunk that can't open its session degrades best-effort, the run still finalizes.
    @activity.defn(name="validate_chunk_activity")
    async def validate_chunk(input: ValidateChunkInput) -> ValidateChunkResult:
        if input.chunk_id == 2:
            raise RuntimeError("sandbox boom")
        return ValidateChunkResult(chunk_id=input.chunk_id, validated_count=1)

    issues = [json.dumps({"id": "1-1-1"}), json.dumps({"id": "1-2-1"})]
    validated = await _run_validate_workflow(issues_json=issues, validate_chunk=validate_chunk)
    assert validated == 1  # chunk 1 survived; chunk 2 dropped


@pytest.mark.asyncio
async def test_validate_issues_workflow_fails_above_failure_floor():
    # Both chunks' sessions fail (100%, over the 70% floor): a near-total wipeout fails the run loudly
    # instead of finalizing with no verdicts.
    @activity.defn(name="validate_chunk_activity")
    async def validate_chunk(input: ValidateChunkInput) -> ValidateChunkResult:
        raise RuntimeError("sandbox boom")

    issues = [json.dumps({"id": "1-1-1"}), json.dumps({"id": "1-2-1"})]
    with pytest.raises(WorkflowFailureError):
        await _run_validate_workflow(issues_json=issues, validate_chunk=validate_chunk)
