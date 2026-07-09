"""Workflow-level tests for the ReviewHog Temporal pipeline.

Activities are replaced with `@activity.defn` stand-ins (matching the real activity names) so these
exercise the real orchestration + the real fan-out children without touching the DB or a sandbox.
"""

import json
import uuid

import pytest

import temporalio.worker
from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.review_hog.backend.reviewer.constants import BLIND_SPOT_PASS_NUMBER, VALIDATION_MAX_ATTEMPTS
from products.review_hog.backend.reviewer.tools.select_perspectives import ChunkSelectionDTO, PerspectiveSelectionDTO
from products.review_hog.backend.temporal.activities import (
    AppendCodeReviewArtefactInput,
    BuildBodyInput,
    DedupResult,
    LoadBlindSpotsInput,
    LoadedBlindSpotsSkillDTO,
    LoadedPerspectiveDTO,
    LoadedValidationSkillDTO,
    LoadPerspectivesInput,
    LoadValidationInput,
    PublishInput,
    PublishResult,
    ResolveActingUserResult,
    ReviewChunkInput,
    ReviewMeta,
    SelectPerspectivesInput,
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

_REVIEW_URL = "https://github.com/o/r/pull/7#pullrequestreview-1"


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
    review_inbox_prs: bool = False,
    input_acting_user_id: int | None = None,
    trigger_source: str = "manual",
    signal_report_id: str | None = None,
    input_pr_number: int | None = 7,
    input_head_branch: str | None = None,
    meta_pr_number: int | None = 7,
    empty_diff: bool = False,
    fail_dedup: bool = False,
    selection: PerspectiveSelectionDTO | None = None,
    fail_selection: bool = False,
    fail_review_units: frozenset[tuple[int, int]] = frozenset(),
) -> dict:
    # Runs the real ReviewPRWorkflow with activity stand-ins, recording what fanned out + published.
    # already_published / empty_diff drive the early-exit gates; acting_user_id None means the author
    # isn't a PostHog user, so the workflow skips the review. review_labeled_prs / review_inbox_prs
    # are the trigger-aware opt-outs read per trigger_source; input_acting_user_id is the explicit
    # override on the workflow input (CLI / inbox). meta_pr_number is the publish destination fetch
    # resolved (None = branch target with no PR → store-only); fail_dedup forces a mid-run failure so
    # the failed-turn receipt path can be observed.
    split_calls: list[int] = []
    # Each review unit as (pass_number, chunk_id, blind_spot_check, skill_name, wave lens names) — the
    # blind-spot fields let the fan-out test pin the second round's routing contract.
    review_calls: list[tuple[int, int, bool, str, tuple[str, ...]]] = []
    validate_calls: list[int] = []
    publish_calls: list[int] = []
    # Each code_review receipt appended to the signals report, as (outcome, review_url).
    receipt_calls: list[tuple[str, str | None]] = []
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
            pr_number=meta_pr_number,
            pr_url="u" if meta_pr_number is not None else None,
            empty_diff=empty_diff,
        )

    @activity.defn(name="resolve_acting_user_activity")
    async def resolve_acting_user(input) -> ResolveActingUserResult:
        # A non-default threshold, so the threading asserts can't pass on the dataclass defaults.
        return ResolveActingUserResult(
            acting_user_id=acting_user_id,
            review_labeled_prs=review_labeled_prs,
            urgency_threshold="must_fix",
            review_inbox_prs=review_inbox_prs,
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
        # Descriptions matter: an undescribed perspective is never prunable, so a selection could
        # not thin the fan-out and the sparse-routing test would silently assert the dense product.
        return [
            LoadedPerspectiveDTO(pass_number=1, skill_name="s-logic", version=1, description="logic lens"),
            LoadedPerspectiveDTO(pass_number=2, skill_name="s-sec", version=1, description="security lens"),
            LoadedPerspectiveDTO(pass_number=3, skill_name="s-perf", version=1, description="performance lens"),
        ]

    @activity.defn(name="select_perspectives_activity")
    async def select_perspectives(input: SelectPerspectivesInput) -> PerspectiveSelectionDTO | None:
        if fail_selection:
            raise ApplicationError("selector down", non_retryable=True)
        return selection

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
        if (input.pass_number, input.chunk_id) in fail_review_units:
            raise ApplicationError("sandbox died", non_retryable=True)
        return True

    @activity.defn(name="dedup_activity")
    async def dedup(input) -> DedupResult:
        if fail_dedup:
            raise ApplicationError("sandbox layer down", non_retryable=True)
        # Two survivors in two different chunks, so validate fans out one warm session per chunk.
        return DedupResult(issue_ids=["1-1-1", "1-2-1"])

    @activity.defn(name="load_validation_skill_activity")
    async def load_validation(input: LoadValidationInput) -> LoadedValidationSkillDTO:
        load_user_ids.append(input.acting_user_id)
        return LoadedValidationSkillDTO(skill_name="s-val", version=1)

    @activity.defn(name="validate_chunk_activity")
    async def validate_chunk(input: ValidateChunkInput) -> ValidateChunkResult:
        validate_calls.append(input.chunk_id)
        return ValidateChunkResult(chunk_id=input.chunk_id, validated_count=len(input.issue_ids))

    @activity.defn(name="build_body_activity")
    async def build_body(input: BuildBodyInput) -> None:
        threshold_calls.append(("body", input.urgency_threshold))
        return None

    @activity.defn(name="publish_review_activity")
    async def publish_act(input: PublishInput) -> PublishResult:
        publish_calls.append(input.pr_number)
        threshold_calls.append(("publish", input.urgency_threshold))
        return PublishResult(posted=True, review_url=_REVIEW_URL)

    @activity.defn(name="append_code_review_artefact_activity")
    async def append_receipt(input: AppendCodeReviewArtefactInput) -> None:
        receipt_calls.append((input.outcome, input.review_url))
        return None

    result: str | None = None
    failed = False
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
                select_perspectives,
                load_blind_spots,
                review,
                dedup,
                load_validation,
                validate_chunk,
                build_body,
                publish_act,
                append_receipt,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            try:
                result = await env.client.execute_workflow(
                    ReviewPRWorkflow.run,
                    ReviewPRWorkflowInputs(
                        team_id=1,
                        user_id=2,
                        pr_url="u" if input_pr_number is not None else None,
                        owner="o",
                        repo="r",
                        pr_number=input_pr_number,
                        publish=publish,
                        acting_user_id=input_acting_user_id,
                        trigger_source=trigger_source,
                        signal_report_id=signal_report_id,
                        head_branch=input_head_branch,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
            except WorkflowFailureError:
                failed = True

    return {
        "result": result,
        "failed": failed,
        "split": split_calls,
        "review": review_calls,
        "validate": validate_calls,
        "publish": publish_calls,
        "receipts": receipt_calls,
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
async def test_review_pr_workflow_selection_prunes_fan_out_and_scopes_blind_spot_lenses():
    # The selector's plan gates the wave: only the selected (perspective, chunk) pairs run, a
    # zero-selected chunk still gets its blind-spot unit, and each blind-spot unit is told exactly
    # the lenses that ran on ITS chunk — not the full roster (which would make the sweep skip ground
    # nobody actually covered).
    selection = PerspectiveSelectionDTO(
        chunks=[
            ChunkSelectionDTO(chunk_id=1, perspectives=["s-logic", "s-sec"], reason="r1"),
            ChunkSelectionDTO(chunk_id=2, perspectives=[], reason="r2"),
        ]
    )
    recorded = await _run_full_review_pr_workflow(publish=False, selection=selection)
    wave = [c for c in recorded["review"] if not c[2]]
    blind = [c for c in recorded["review"] if c[2]]
    assert sorted((p, c) for p, c, *_ in wave) == [(1, 1), (2, 1)]
    assert sorted((p, c) for p, c, *_ in blind) == [(BLIND_SPOT_PASS_NUMBER, 1), (BLIND_SPOT_PASS_NUMBER, 2)]
    assert {c[1]: c[4] for c in blind} == {1: ("s-logic", "s-sec"), 2: ()}


@pytest.mark.asyncio
async def test_review_pr_workflow_excludes_a_failed_perspective_from_blind_spot_lenses():
    # A failed wave unit left no persisted review, so its ground is NOT spoken for: telling the
    # blind-spot sweep it ran would hide exactly the coverage gap the failure created. The other
    # chunk's unit succeeded, so that chunk still reports the full roster.
    recorded = await _run_full_review_pr_workflow(publish=False, fail_review_units=frozenset({(2, 1)}))
    assert recorded["failed"] is False  # one unit of six is under the failure floor
    blind = [c for c in recorded["review"] if c[2]]
    assert {c[1]: c[4] for c in blind} == {1: ("s-logic", "s-perf"), 2: ("s-logic", "s-sec", "s-perf")}


@pytest.mark.asyncio
async def test_review_pr_workflow_falls_back_to_dense_when_selection_fails():
    # Selection is an optimization: its failure must neither fail the run nor thin the review —
    # every (perspective, chunk) pair still runs, and the blind-spot units see the full roster.
    recorded = await _run_full_review_pr_workflow(publish=False, fail_selection=True)
    assert recorded["failed"] is False
    wave = [c for c in recorded["review"] if not c[2]]
    blind = [c for c in recorded["review"] if c[2]]
    assert len(wave) == 6  # 3 perspectives × 2 chunks, exactly as without a selector
    assert {c[4] for c in blind} == {("s-logic", "s-sec", "s-perf")}


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


@parameterized.expand(
    [
        # (name, trigger_source, review_labeled_prs, review_inbox_prs, input_acting_user_id, expect_ran)
        # The label trigger's per-author opt-out gates only the cloud path (no explicit override)...
        ("label_opt_out_skips", "label", False, True, None, False),
        # ...an explicit override (CLI re-run of a labeled PR) always runs...
        ("label_override_ignores_opt_out", "label", False, True, 3, True),
        # ...and the inbox toggle has no say over the label path.
        ("label_ignores_inbox_toggle", "label", True, False, None, True),
        # The inbox trigger honors only review_inbox_prs (default off = the budget gate); the
        # receiver always sets the acting override, so the override must NOT bypass this gate.
        ("inbox_default_off_skips", "inbox", True, False, 3, False),
        ("inbox_opt_in_runs_despite_label_opt_out", "inbox", False, True, 3, True),
        # Manual (CLI/eval) stays ungated regardless of either toggle.
        ("manual_ungated", "manual", False, False, 3, True),
    ]
)
@pytest.mark.asyncio
async def test_review_pr_workflow_trigger_aware_gates(
    _name, trigger_source, review_labeled_prs, review_inbox_prs, input_acting_user_id, expect_ran
):
    # The trigger-source gate matrix: a miswired gate either reviews PRs for opted-out users (burning
    # sandbox cost) or silently disables a production trigger. Skipped turns must also append no
    # code_review receipt (nothing was done); executed no-publish turns append a "stored" one.
    recorded = await _run_full_review_pr_workflow(
        publish=False,
        trigger_source=trigger_source,
        review_labeled_prs=review_labeled_prs,
        review_inbox_prs=review_inbox_prs,
        input_acting_user_id=input_acting_user_id,
        signal_report_id="sr-1",
    )
    assert recorded["result"] == "rep-1"
    if expect_ran:
        assert recorded["split"] == [1]
        assert recorded["receipts"] == [("stored", None)]
    else:
        assert recorded["split"] == []
        assert recorded["review"] == []
        assert recorded["publish"] == []
        assert recorded["receipts"] == []


@pytest.mark.asyncio
async def test_review_pr_workflow_appends_published_receipt_with_review_url():
    # The inbox flow's happy path: a published turn's receipt carries outcome="published" and the
    # GitHub review permalink, so the signals report links straight to the posted review.
    recorded = await _run_full_review_pr_workflow(
        publish=True, trigger_source="inbox", review_inbox_prs=True, input_acting_user_id=3, signal_report_id="sr-1"
    )
    assert recorded["publish"] == [7]
    assert recorded["receipts"] == [("published", _REVIEW_URL)]


@pytest.mark.asyncio
async def test_review_pr_workflow_appends_failed_receipt_and_still_fails():
    # A mid-run failure must both surface (the workflow fails, so Temporal retries) AND leave a
    # failed-turn receipt on the signals report — otherwise the report reads as "never reviewed".
    recorded = await _run_full_review_pr_workflow(
        publish=True,
        trigger_source="inbox",
        review_inbox_prs=True,
        input_acting_user_id=3,
        signal_report_id="sr-1",
        fail_dedup=True,
    )
    assert recorded["failed"] is True
    assert recorded["receipts"] == [("failed", None)]


@pytest.mark.asyncio
async def test_review_pr_workflow_appends_no_receipt_without_signal_report():
    # Label/manual runs have no signals provenance — the receipt activity must not fire at all.
    recorded = await _run_full_review_pr_workflow(publish=True)
    assert recorded["publish"] == [7]
    assert recorded["receipts"] == []


@pytest.mark.asyncio
async def test_review_pr_workflow_branch_target_stores_without_publishing():
    # A branch target with no resolvable PR: the full pipeline runs, publish is skipped (there is
    # nowhere to post), and the receipt records "stored" — the target's shape decides, not a flag.
    recorded = await _run_full_review_pr_workflow(
        publish=True,
        trigger_source="inbox",
        review_inbox_prs=True,
        input_acting_user_id=3,
        signal_report_id="sr-1",
        input_pr_number=None,
        input_head_branch="feat",
        meta_pr_number=None,
    )
    assert recorded["split"] == [1]
    assert recorded["publish"] == []
    assert recorded["receipts"] == [("stored", None)]


@pytest.mark.asyncio
async def test_review_pr_workflow_early_exits_on_empty_branch_diff():
    # "Pushed nothing → do nothing": an empty compare diff skips before any sandbox spend and
    # appends no receipt.
    recorded = await _run_full_review_pr_workflow(
        publish=True,
        trigger_source="inbox",
        review_inbox_prs=True,
        input_acting_user_id=3,
        signal_report_id="sr-1",
        input_pr_number=None,
        input_head_branch="feat",
        meta_pr_number=None,
        empty_diff=True,
    )
    assert recorded["result"] == "rep-1"
    assert recorded["split"] == []
    assert recorded["review"] == []
    assert recorded["receipts"] == []


def test_review_pr_workflow_inputs_deserialize_old_payloads():
    # In-flight Temporal payloads serialized before the trigger-source/branch-target fields existed
    # must still deserialize on deploy — a new non-defaulted field here breaks every running review.
    old_shape = {"team_id": 1, "user_id": 2, "pr_url": "u", "owner": "o", "repo": "r", "pr_number": 7}
    inputs = ReviewPRWorkflow.parse_inputs([json.dumps(old_shape)])
    assert inputs.trigger_source == "manual"
    assert inputs.signal_report_id is None
    assert inputs.head_branch is None


async def _run_validate_workflow(*, issue_ids: list[str], validate_chunk) -> int:
    """Run `ValidateIssuesWorkflow` with a stand-in chunk validator; return the validated count."""

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
                ValidateIssuesInputs(**_stage_kwargs(), issue_ids=issue_ids, acting_user_id=3),
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
        calls.append((input.chunk_id, tuple(sorted(input.issue_ids))))
        return ValidateChunkResult(chunk_id=input.chunk_id, validated_count=len(input.issue_ids))

    issue_ids = [
        "1-1-1",  # chunk 1
        "2-1-2",  # chunk 1 (different perspective)
        "1-2-1",  # chunk 2
        "malformed",  # not {pass}-{chunk}-{issue} → skipped
    ]
    await _run_validate_workflow(issue_ids=issue_ids, validate_chunk=validate_chunk)

    by_chunk = {chunk_id: set(ids) for chunk_id, ids in calls}
    assert set(by_chunk) == {1, 2}
    assert by_chunk[1] == {"1-1-1", "2-1-2"}
    assert by_chunk[2] == {"1-2-1"}


@pytest.mark.asyncio
async def test_validate_issues_workflow_retries_a_failed_chunk_validation():
    # A transiently failing chunk validation must be re-attempted up to VALIDATION_MAX_ATTEMPTS, not
    # dropped — and the retry count must track the constant the activity's final-attempt check uses.
    attempts: list[int] = []

    @activity.defn(name="validate_chunk_activity")
    async def validate_chunk(input: ValidateChunkInput) -> ValidateChunkResult:
        attempts.append(activity.info().attempt)
        if activity.info().attempt < VALIDATION_MAX_ATTEMPTS:
            raise RuntimeError("transient turn failure")
        return ValidateChunkResult(chunk_id=input.chunk_id, validated_count=1)

    validated = await _run_validate_workflow(issue_ids=["1-1-1"], validate_chunk=validate_chunk)
    assert validated == 1
    assert attempts == list(range(1, VALIDATION_MAX_ATTEMPTS + 1))


@pytest.mark.asyncio
async def test_validate_issues_workflow_is_best_effort_on_chunk_failure():
    # One chunk of two fails (50%, under the 70% floor): the workflow returns the survivor count and
    # does NOT fail — a chunk that can't open its session degrades best-effort, the run still finalizes.
    @activity.defn(name="validate_chunk_activity")
    async def validate_chunk(input: ValidateChunkInput) -> ValidateChunkResult:
        if input.chunk_id == 2:
            raise RuntimeError("sandbox boom")
        return ValidateChunkResult(chunk_id=input.chunk_id, validated_count=1)

    validated = await _run_validate_workflow(issue_ids=["1-1-1", "1-2-1"], validate_chunk=validate_chunk)
    assert validated == 1  # chunk 1 survived; chunk 2 dropped


@pytest.mark.asyncio
async def test_validate_issues_workflow_fails_above_failure_floor():
    # Both chunks' sessions fail (100%, over the 70% floor): a near-total wipeout fails the run loudly
    # instead of finalizing with no verdicts.
    @activity.defn(name="validate_chunk_activity")
    async def validate_chunk(input: ValidateChunkInput) -> ValidateChunkResult:
        raise RuntimeError("sandbox boom")

    with pytest.raises(WorkflowFailureError):
        await _run_validate_workflow(issue_ids=["1-1-1", "1-2-1"], validate_chunk=validate_chunk)
