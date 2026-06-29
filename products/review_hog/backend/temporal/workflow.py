"""Single-turn ReviewHog PR review as a Temporal workflow.

`ReviewPRWorkflow` is pure orchestration mirroring the former `run.py main()`: setup activities →
three fan-out child workflows (analyze / perspective review / validate) → finishing activities. Only
small, serializable values cross boundaries — `report_id` + `head_sha` + unit keys / JSON issue
slices — and every consumer reloads its inputs from the `pr_snapshot` artefact, so no big payload
hits Temporal's ~2 MiB cap. Stage progress is logged via `workflow.logger` so it streams in the
worker log (the former stdout banners).

The fan-out children dispatch per-unit sandbox activities (each retried) under a fresh
`asyncio.Semaphore` and `gather(return_exceptions=True)`, so a minority of failed units degrade
best-effort; a near-total wipeout (> `FAN_OUT_FAILURE_FLOOR`) fails the run loudly instead of
finalizing an empty review as success. Publishing is per-run: the final stage posts to GitHub only
when `inputs.publish` is set (the cloud label trigger), and is skipped for eval / CLI runs.
"""

import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from products.review_hog.backend.reviewer.constants import FAN_OUT_FAILURE_FLOOR, MAX_CONCURRENT_SANDBOXES
from products.review_hog.backend.temporal.activities import (
    AnalyzeChunkInput,
    BuildBodyInput,
    CombineCleanInput,
    DedupInput,
    DedupResult,
    FetchPRDataInput,
    GenerateSchemasInput,
    LoadedPerspectiveDTO,
    LoadedValidationSkillDTO,
    LoadPerspectivesInput,
    PublishInput,
    ResolveActingUserInput,
    ReviewChunkInput,
    ReviewMeta,
    SandboxStageInput,
    SyncReviewSkillsInput,
    ValidateIntegrationInput,
    ValidateIssueInput,
    ValidateIssueResult,
    analyze_chunk_activity,
    build_body_activity,
    combine_and_clean_activity,
    dedup_activity,
    fetch_pr_data_activity,
    generate_schemas_activity,
    load_perspectives_activity,
    load_validation_skill_activity,
    publish_review_activity,
    resolve_acting_user_activity,
    review_chunk_activity,
    split_chunks_activity,
    sync_review_skills_activity,
    validate_github_integration_activity,
    validate_issue_activity,
)
from products.review_hog.backend.temporal.types import ReviewPRWorkflowInputs

# Timeouts: a sandbox turn can over-investigate (measured up to ~6m), so 30m start-to-close with a
# 5m heartbeat; local (non-sandbox) activities are quick.
_SANDBOX_TIMEOUT = timedelta(minutes=30)
_SANDBOX_HEARTBEAT = timedelta(minutes=5)
_QUICK_TIMEOUT = timedelta(minutes=2)
_FETCH_TIMEOUT = timedelta(minutes=5)
_RETRY = RetryPolicy(maximum_attempts=2)


def _enforce_failure_floor(stage: str, failed: int, total: int) -> None:
    """Fail the run when more than `FAN_OUT_FAILURE_FLOOR` of a fan-out stage's units failed.

    A few flaky units degrade best-effort; a near-total wipeout (e.g. the sandbox layer down) must
    surface loudly instead of letting the pipeline finalize an empty review as success.
    """
    if total and failed / total > FAN_OUT_FAILURE_FLOOR:
        raise ApplicationError(
            f"{stage}: {failed}/{total} units failed (> {FAN_OUT_FAILURE_FLOOR:.0%}); failing the run"
        )


@dataclass
class AnalyzeChunksInputs(SandboxStageInput):
    chunk_ids: list[int]


@dataclass
class ReviewPerspectivesInputs(SandboxStageInput):
    chunk_ids: list[int]
    # The user whose enabled perspectives this review fans out over (the PR author, or the CLI override).
    acting_user_id: int


@dataclass
class ValidateIssuesInputs(SandboxStageInput):
    issues_json: list[str]


@temporalio.workflow.defn(name="review-analyze-chunks")
class AnalyzeChunksWorkflow:
    """Fan out one analysis sandbox activity per chunk (bounded, best-effort)."""

    @temporalio.workflow.run
    async def run(self, inputs: AnalyzeChunksInputs) -> int:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)

        async def _analyze(chunk_id: int) -> bool:
            async with semaphore:
                return await workflow.execute_activity(
                    analyze_chunk_activity,
                    AnalyzeChunkInput(
                        team_id=inputs.team_id,
                        user_id=inputs.user_id,
                        report_id=inputs.report_id,
                        head_sha=inputs.head_sha,
                        repository=inputs.repository,
                        branch=inputs.branch,
                        run_index=inputs.run_index,
                        chunk_id=chunk_id,
                    ),
                    start_to_close_timeout=_SANDBOX_TIMEOUT,
                    heartbeat_timeout=_SANDBOX_HEARTBEAT,
                    retry_policy=_RETRY,
                )

        results = await asyncio.gather(*(_analyze(c) for c in inputs.chunk_ids), return_exceptions=True)
        total = len(inputs.chunk_ids)
        failed = sum(1 for r in results if isinstance(r, BaseException))
        _enforce_failure_floor("Analyze", failed, total)
        analyzed = total - failed
        if failed:
            workflow.logger.warning(f"Analyzed {analyzed}/{total} chunk(s); {failed} failed best-effort")
        return analyzed


@temporalio.workflow.defn(name="review-perspectives")
class ReviewPerspectivesWorkflow:
    """Fan out one review sandbox activity per (perspective × chunk) (bounded, best-effort).

    Perspectives are resolved (and version-pinned) once via an activity, then every (perspective,
    chunk) pair runs concurrently with no cross-perspective context — overlap is resolved by the
    downstream dedup stage.
    """

    @temporalio.workflow.run
    async def run(self, inputs: ReviewPerspectivesInputs) -> int:
        perspectives: list[LoadedPerspectiveDTO] = await workflow.execute_activity(
            load_perspectives_activity,
            LoadPerspectivesInput(team_id=inputs.team_id, acting_user_id=inputs.acting_user_id),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )
        units = [(perspective, chunk_id) for perspective in perspectives for chunk_id in inputs.chunk_ids]
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)

        async def _review(perspective: LoadedPerspectiveDTO, chunk_id: int) -> bool:
            async with semaphore:
                return await workflow.execute_activity(
                    review_chunk_activity,
                    ReviewChunkInput(
                        team_id=inputs.team_id,
                        user_id=inputs.user_id,
                        report_id=inputs.report_id,
                        head_sha=inputs.head_sha,
                        repository=inputs.repository,
                        branch=inputs.branch,
                        run_index=inputs.run_index,
                        chunk_id=chunk_id,
                        pass_number=perspective.pass_number,
                        skill_name=perspective.skill_name,
                        skill_version=perspective.version,
                    ),
                    start_to_close_timeout=_SANDBOX_TIMEOUT,
                    heartbeat_timeout=_SANDBOX_HEARTBEAT,
                    retry_policy=_RETRY,
                )

        results = await asyncio.gather(*(_review(p, c) for p, c in units), return_exceptions=True)
        total = len(units)
        failed = sum(1 for r in results if isinstance(r, BaseException))
        _enforce_failure_floor("Review", failed, total)
        reviewed = total - failed
        if failed:
            workflow.logger.warning(
                f"Reviewed {reviewed}/{total} (perspective, chunk) pair(s); {failed} failed best-effort"
            )
        return reviewed


@temporalio.workflow.defn(name="review-validate-issues")
class ValidateIssuesWorkflow:
    """Fan out one validation sandbox activity per issue (bounded); return the kept verdicts.

    Returns `{issue_id: validation_json}` for the issues the validator ruled on, so the parent can
    render the body. Each per-issue activity also persists its verdict, so publishing stays
    DB-driven.
    """

    @temporalio.workflow.run
    async def run(self, inputs: ValidateIssuesInputs) -> dict[str, str]:
        if not inputs.issues_json:
            return {}
        skill: LoadedValidationSkillDTO = await workflow.execute_activity(
            load_validation_skill_activity,
            ValidateIntegrationInput(team_id=inputs.team_id),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)

        async def _validate(issue_json: str) -> ValidateIssueResult:
            async with semaphore:
                return await workflow.execute_activity(
                    validate_issue_activity,
                    ValidateIssueInput(
                        team_id=inputs.team_id,
                        user_id=inputs.user_id,
                        report_id=inputs.report_id,
                        head_sha=inputs.head_sha,
                        repository=inputs.repository,
                        branch=inputs.branch,
                        run_index=inputs.run_index,
                        issue_json=issue_json,
                        skill_name=skill.skill_name,
                        skill_version=skill.version,
                    ),
                    start_to_close_timeout=_SANDBOX_TIMEOUT,
                    heartbeat_timeout=_SANDBOX_HEARTBEAT,
                    retry_policy=_RETRY,
                )

        results = await asyncio.gather(*(_validate(j) for j in inputs.issues_json), return_exceptions=True)
        total = len(inputs.issues_json)
        failed = sum(1 for r in results if isinstance(r, BaseException))
        _enforce_failure_floor("Validate", failed, total)
        validations: dict[str, str] = {}
        for result in results:
            if isinstance(result, ValidateIssueResult) and result.validation_json is not None:
                validations[result.issue_id] = result.validation_json
        if failed:
            workflow.logger.warning(f"Validated {len(validations)}/{total} issue(s); {failed} failed best-effort")
        return validations


@temporalio.workflow.defn(name="review-pr")
class ReviewPRWorkflow:
    """Single-turn PR review: setup → analyze → review → combine → dedup → validate → build → publish."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ReviewPRWorkflowInputs:
        return ReviewPRWorkflowInputs(**json.loads(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: ReviewPRWorkflowInputs) -> str:
        repository = inputs.repository
        workflow.logger.info(f"ReviewHog · reviewing PR #{inputs.pr_number} · {repository}")

        await workflow.execute_activity(
            validate_github_integration_activity,
            ValidateIntegrationInput(team_id=inputs.team_id),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )

        workflow.logger.info("STAGE 1/9 · Fetch PR data")
        meta: ReviewMeta = await workflow.execute_activity(
            fetch_pr_data_activity,
            FetchPRDataInput(
                team_id=inputs.team_id,
                user_id=inputs.user_id,
                repository=repository,
                owner=inputs.owner,
                repo=inputs.repo,
                pr_number=inputs.pr_number,
                pr_url=inputs.pr_url,
            ),
            start_to_close_timeout=_FETCH_TIMEOUT,
            retry_policy=_RETRY,
        )
        report_id, head_sha, branch = meta.report_id, meta.head_sha, meta.branch
        workflow.logger.info(
            "Captured point-in-time diff snapshot" if meta.snapshotted else "No new diff snapshot this turn"
        )

        # Early-exit: nothing to do this turn. `already_published` means this exact head was already
        # reviewed AND posted, so re-running the pipeline would recompute the same review and publish
        # would self-skip — burning sandbox cost for no output. New inline comments do NOT force a turn
        # yet (logged in fetch); reacting to comments lands with the "fix the issues" capability — see
        # ARCHITECTURE.md (Stage 5b / Action plane). A no-publish eval run is never gated here (it has
        # no published head), so the frozen-PR eval loop still recomputes to measure reviewer changes.
        if meta.already_published:
            workflow.logger.info(
                f"Review already published for {repository}#{inputs.pr_number} at {head_sha[:12]}; "
                f"nothing changed this turn ({meta.new_comment_count} new comment(s), not yet acted on) — skipping"
            )
            return report_id

        # Resolve the acting user whose enabled perspectives apply (the PR author, or the CLI
        # override). Gate here — before any sandbox spend — because an author who isn't a PostHog org
        # user has no perspectives to apply, so there is nothing to review (no fallback).
        acting = await workflow.execute_activity(
            resolve_acting_user_activity,
            ResolveActingUserInput(
                team_id=inputs.team_id, author_login=meta.author_login, override_user_id=inputs.acting_user_id
            ),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )
        if acting.acting_user_id is None:
            workflow.logger.info(
                f"PR author '{meta.author_login}' is not a PostHog org user on team {inputs.team_id}; "
                "skipping review (no perspectives to apply)"
            )
            return report_id
        acting_user_id = acting.acting_user_id

        await workflow.execute_activity(
            sync_review_skills_activity,
            SyncReviewSkillsInput(team_id=inputs.team_id),
            start_to_close_timeout=_FETCH_TIMEOUT,
            retry_policy=_RETRY,
        )
        await workflow.execute_activity(
            generate_schemas_activity,
            GenerateSchemasInput(),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )

        stage = SandboxStageInput(
            team_id=inputs.team_id,
            user_id=inputs.user_id,
            report_id=report_id,
            head_sha=head_sha,
            repository=repository,
            branch=branch,
            run_index=meta.run_index,
        )

        workflow.logger.info("STAGE 2/9 · Split into chunks")
        chunk_ids: list[int] = await workflow.execute_activity(
            split_chunks_activity,
            stage,
            start_to_close_timeout=_SANDBOX_TIMEOUT,
            heartbeat_timeout=_SANDBOX_HEARTBEAT,
            retry_policy=_RETRY,
        )

        parent_id = workflow.info().workflow_id

        workflow.logger.info("STAGE 3/9 · Analyze chunks")
        await workflow.execute_child_workflow(
            AnalyzeChunksWorkflow.run,
            AnalyzeChunksInputs(
                team_id=stage.team_id,
                user_id=stage.user_id,
                report_id=stage.report_id,
                head_sha=stage.head_sha,
                repository=stage.repository,
                branch=stage.branch,
                run_index=stage.run_index,
                chunk_ids=chunk_ids,
            ),
            id=f"{parent_id}/analyze",
            retry_policy=_RETRY,
        )

        workflow.logger.info("STAGE 4/9 · Review chunks (per enabled perspective)")
        await workflow.execute_child_workflow(
            ReviewPerspectivesWorkflow.run,
            ReviewPerspectivesInputs(
                team_id=stage.team_id,
                user_id=stage.user_id,
                report_id=stage.report_id,
                head_sha=stage.head_sha,
                repository=stage.repository,
                branch=stage.branch,
                run_index=stage.run_index,
                chunk_ids=chunk_ids,
                acting_user_id=acting_user_id,
            ),
            id=f"{parent_id}/review",
            retry_policy=_RETRY,
        )

        workflow.logger.info("STAGE 5/9 · Combine & scope-clean issues")
        issues_json: list[str] = await workflow.execute_activity(
            combine_and_clean_activity,
            CombineCleanInput(team_id=inputs.team_id, report_id=report_id, head_sha=head_sha),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )

        workflow.logger.info("STAGE 6/9 · Deduplicate issues")
        dedup: DedupResult = await workflow.execute_activity(
            dedup_activity,
            DedupInput(
                team_id=stage.team_id,
                user_id=stage.user_id,
                report_id=stage.report_id,
                head_sha=stage.head_sha,
                repository=stage.repository,
                branch=stage.branch,
                run_index=stage.run_index,
                issues_json=issues_json,
            ),
            start_to_close_timeout=_SANDBOX_TIMEOUT,
            heartbeat_timeout=_SANDBOX_HEARTBEAT,
            retry_policy=_RETRY,
        )
        workflow.logger.info(f"Persisted {dedup.findings_count} finding(s) to the review report")

        workflow.logger.info("STAGE 7/9 · Validate issues")
        validations_json: dict[str, str] = await workflow.execute_child_workflow(
            ValidateIssuesWorkflow.run,
            ValidateIssuesInputs(
                team_id=stage.team_id,
                user_id=stage.user_id,
                report_id=stage.report_id,
                head_sha=stage.head_sha,
                repository=stage.repository,
                branch=stage.branch,
                run_index=stage.run_index,
                issues_json=dedup.issues_json,
            ),
            id=f"{parent_id}/validate",
            retry_policy=_RETRY,
        )

        workflow.logger.info("STAGE 8/9 · Build report")
        await workflow.execute_activity(
            build_body_activity,
            BuildBodyInput(
                team_id=inputs.team_id,
                report_id=report_id,
                head_sha=head_sha,
                issues_json=dedup.issues_json,
                validations_json=validations_json,
            ),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )

        workflow.logger.info("STAGE 9/9 · Publish review")
        if inputs.publish:
            await workflow.execute_activity(
                publish_review_activity,
                PublishInput(
                    team_id=inputs.team_id,
                    report_id=report_id,
                    head_sha=head_sha,
                    run_index=stage.run_index,
                    owner=inputs.owner,
                    repo=inputs.repo,
                    pr_number=inputs.pr_number,
                ),
                start_to_close_timeout=_QUICK_TIMEOUT,
                retry_policy=_RETRY,
            )
        else:
            workflow.logger.info("Publishing disabled for this run (publish=False)")

        workflow.logger.info(f"ReviewHog complete · report stored on ReviewReport {report_id}")
        return report_id
