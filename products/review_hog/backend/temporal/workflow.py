"""Single-turn ReviewHog PR review as a Temporal workflow.

`ReviewPRWorkflow` is pure orchestration mirroring the former `run.py main()`: setup activities →
two fan-out child workflows (perspective review / validate) → finishing activities. Only small,
serializable values cross boundaries — `report_id` + `head_sha` + unit keys / issue ids — and every
consumer reloads its inputs from the persisted artefact rows (`pr_snapshot`, findings), so no
unbounded payload hits Temporal's ~2 MiB cap. Stage progress is logged via `workflow.logger` so it
streams in the worker log (the former stdout banners).

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
from temporalio.exceptions import ActivityError, ApplicationError

from products.review_hog.backend.reviewer.constants import (
    BLIND_SPOT_PASS_NUMBER,
    FAN_OUT_FAILURE_FLOOR,
    MAX_CONCURRENT_SANDBOXES,
    VALIDATION_MAX_ATTEMPTS,
)
from products.review_hog.backend.reviewer.tools.select_perspectives import PerspectiveSelectionDTO, apply_selection
from products.review_hog.backend.temporal.activities import (
    AppendCodeReviewArtefactInput,
    BuildBodyInput,
    DedupResult,
    FetchPRDataInput,
    GenerateSchemasInput,
    LoadBlindSpotsInput,
    LoadedBlindSpotsSkillDTO,
    LoadedPerspectiveDTO,
    LoadedValidationSkillDTO,
    LoadPerspectivesInput,
    LoadValidationInput,
    PublishInput,
    PublishResult,
    ResolveActingUserInput,
    ReviewChunkInput,
    ReviewMeta,
    SandboxStageInput,
    SelectPerspectivesInput,
    SyncReviewSkillsInput,
    ValidateChunkInput,
    ValidateChunkResult,
    ValidateIntegrationInput,
    append_code_review_artefact_activity,
    build_body_activity,
    dedup_activity,
    fetch_pr_data_activity,
    generate_schemas_activity,
    load_blind_spots_skill_activity,
    load_perspectives_activity,
    load_validation_skill_activity,
    publish_review_activity,
    resolve_acting_user_activity,
    review_chunk_activity,
    select_perspectives_activity,
    split_chunks_activity,
    sync_review_skills_activity,
    validate_chunk_activity,
    validate_github_integration_activity,
)
from products.review_hog.backend.temporal.types import TRIGGER_INBOX, TRIGGER_LABEL, ReviewPRWorkflowInputs

# Timeouts: sandbox turns can legitimately run long (a heavy validation chunk measured 34m — one
# opus verdict per issue), so 60m start-to-close; the 5m heartbeat still catches dead sandboxes
# fast, start-to-close is only the ceiling for live work. Local (non-sandbox) activities are quick.
_SANDBOX_TIMEOUT = timedelta(minutes=60)
_SANDBOX_HEARTBEAT = timedelta(minutes=5)
_QUICK_TIMEOUT = timedelta(minutes=2)
_FETCH_TIMEOUT = timedelta(minutes=5)
_RETRY = RetryPolicy(maximum_attempts=2)
# The validate activity's final-attempt fallback keys off the same constant — don't let them drift.
_VALIDATE_RETRY = RetryPolicy(maximum_attempts=VALIDATION_MAX_ATTEMPTS)


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
class ReviewPerspectivesInputs(SandboxStageInput):
    chunk_ids: list[int]
    # The user whose enabled perspectives this review fans out over (the PR author, or the CLI override).
    acting_user_id: int


@dataclass
class ValidateIssuesInputs(SandboxStageInput):
    # The survivors' issue ids (`DedupResult.issue_ids`); the chunk activities reload the content
    # from the finding rows, so only ids cross the child-workflow payload boundary.
    issue_ids: list[str]
    # The user whose selected validator validates this review (the PR author, or the CLI override).
    acting_user_id: int


@temporalio.workflow.defn(name="review-perspectives")
class ReviewPerspectivesWorkflow:
    """Select lenses per chunk, fan out the wave, then one blind-spot check per chunk (best-effort).

    Perspectives are resolved (and version-pinned) once via an activity; a cheap one-shot selection
    then decides which lenses each chunk actually needs, and only the selected (perspective, chunk)
    pairs run concurrently with no cross-perspective context — overlap is resolved by the downstream
    dedup stage. Selection is fail-open: any failure means the dense product (every perspective on
    every chunk). After the wave, the blind-spot check (a customizable single-active skill, like the
    validator) runs once per EVERY chunk — selection never touches it, so a chunk with zero selected
    lenses still gets reviewed: it reads its chunk's wave findings (told which lenses ran on that
    chunk) and hunts for what they missed, under the reserved `BLIND_SPOT_PASS_NUMBER`.
    """

    @temporalio.workflow.run
    async def run(self, inputs: ReviewPerspectivesInputs) -> int:
        perspectives: list[LoadedPerspectiveDTO] = await workflow.execute_activity(
            load_perspectives_activity,
            LoadPerspectivesInput(team_id=inputs.team_id, acting_user_id=inputs.acting_user_id),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )
        # Ascending pass_number keeps the blind-spot check's injected lens list deterministic; it's a
        # no-op ordering for the parallel fan-out itself.
        ordered = sorted(perspectives, key=lambda p: p.pass_number)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)

        selection: PerspectiveSelectionDTO | None = None
        if inputs.chunk_ids:
            try:
                selection = await workflow.execute_activity(
                    select_perspectives_activity,
                    SelectPerspectivesInput(
                        team_id=inputs.team_id,
                        user_id=inputs.user_id,
                        report_id=inputs.report_id,
                        head_sha=inputs.head_sha,
                        repository=inputs.repository,
                        branch=inputs.branch,
                        run_index=inputs.run_index,
                        perspectives=ordered,
                    ),
                    start_to_close_timeout=_SANDBOX_TIMEOUT,
                    heartbeat_timeout=_SANDBOX_HEARTBEAT,
                    retry_policy=_RETRY,
                )
            except ActivityError:
                # Selection is an optimization; failing it must never cost the review.
                workflow.logger.warning("Perspective selection failed; running all perspectives on all chunks")

        async def _review(
            pass_number: int,
            skill_name: str,
            skill_version: int,
            chunk_id: int,
            blind_spot_check: bool,
            wave_perspectives: list[LoadedPerspectiveDTO],
        ) -> bool:
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
                        pass_number=pass_number,
                        skill_name=skill_name,
                        skill_version=skill_version,
                        blind_spot_check=blind_spot_check,
                        wave_perspectives=wave_perspectives,
                    ),
                    start_to_close_timeout=_SANDBOX_TIMEOUT,
                    heartbeat_timeout=_SANDBOX_HEARTBEAT,
                    retry_policy=_RETRY,
                )

        units = apply_selection(ordered, inputs.chunk_ids, selection, blind_spot_runs=True)
        dense_total = len(ordered) * len(inputs.chunk_ids)
        if len(units) < dense_total:
            workflow.logger.info(f"Perspective selection kept {len(units)}/{dense_total} (perspective, chunk) pair(s)")
        results = await asyncio.gather(
            *(_review(p.pass_number, p.skill_name, p.version, c, False, []) for p, c in units),
            return_exceptions=True,
        )

        total = len(units)
        failed = sum(1 for r in results if isinstance(r, BaseException))
        _enforce_failure_floor("Review", failed, total)
        reviewed = total - failed
        if failed:
            workflow.logger.warning(
                f"Reviewed {reviewed}/{total} (perspective, chunk) pair(s); {failed} failed best-effort"
            )
        # The lenses that actually SUCCEEDED per chunk — built from the gather results, not the plan,
        # so a failed perspective's ground isn't reported to the blind-spot sweep as spoken for.
        ran_by_chunk: dict[int, list[LoadedPerspectiveDTO]] = {c: [] for c in inputs.chunk_ids}
        for (p, c), result in zip(units, results):
            if not isinstance(result, BaseException):
                ran_by_chunk[c].append(p)

        # Blind-spot check: after the perspective wave, one broad "what did everyone miss?" unit per
        # chunk reads every wave finding and sweeps for what none of the lenses surfaced.
        blind_spots: LoadedBlindSpotsSkillDTO = await workflow.execute_activity(
            load_blind_spots_skill_activity,
            LoadBlindSpotsInput(team_id=inputs.team_id, acting_user_id=inputs.acting_user_id),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )
        spot_results = await asyncio.gather(
            *(
                _review(BLIND_SPOT_PASS_NUMBER, blind_spots.skill_name, blind_spots.version, c, True, ran_by_chunk[c])
                for c in inputs.chunk_ids
            ),
            return_exceptions=True,
        )
        spot_total = len(inputs.chunk_ids)
        spot_failed = sum(1 for r in spot_results if isinstance(r, BaseException))
        _enforce_failure_floor("Blind spots", spot_failed, spot_total)
        reviewed += spot_total - spot_failed
        if spot_failed:
            workflow.logger.warning(
                f"Blind-spot check reviewed {spot_total - spot_failed}/{spot_total} chunk(s); {spot_failed} failed"
            )

        return reviewed


def _chunk_id_of(issue_id: str) -> int | None:
    """The chunk id encoded in an issue's id (`{pass}-{chunk}-{issue}`), or None if malformed."""
    parts = issue_id.split("-")
    if len(parts) != 3:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


@temporalio.workflow.defn(name="review-validate-issues")
class ValidateIssuesWorkflow:
    """Fan out one warm validation session per chunk (bounded, concurrent); return the validated count.

    Survivors are grouped by chunk; each chunk's session validates its issues (one verdict per turn).
    Verdicts persist per issue, so body + publish read them from the DB — this return is informational
    (logging / failure floor only).
    """

    @temporalio.workflow.run
    async def run(self, inputs: ValidateIssuesInputs) -> int:
        if not inputs.issue_ids:
            return 0
        skill: LoadedValidationSkillDTO = await workflow.execute_activity(
            load_validation_skill_activity,
            LoadValidationInput(team_id=inputs.team_id, acting_user_id=inputs.acting_user_id),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )
        # Group survivors by their chunk so one warm session validates each chunk's issues together.
        by_chunk: dict[int, list[str]] = {}
        for issue_id in inputs.issue_ids:
            chunk_id = _chunk_id_of(issue_id)
            if chunk_id is None:
                workflow.logger.warning(f"Skipping validation for an issue with a malformed id: {issue_id}")
                continue
            by_chunk.setdefault(chunk_id, []).append(issue_id)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)

        async def _validate(chunk_id: int, chunk_issue_ids: list[str]) -> ValidateChunkResult:
            async with semaphore:
                return await workflow.execute_activity(
                    validate_chunk_activity,
                    ValidateChunkInput(
                        team_id=inputs.team_id,
                        user_id=inputs.user_id,
                        report_id=inputs.report_id,
                        head_sha=inputs.head_sha,
                        repository=inputs.repository,
                        branch=inputs.branch,
                        run_index=inputs.run_index,
                        chunk_id=chunk_id,
                        issue_ids=chunk_issue_ids,
                        skill_name=skill.skill_name,
                        skill_version=skill.version,
                    ),
                    start_to_close_timeout=_SANDBOX_TIMEOUT,
                    heartbeat_timeout=_SANDBOX_HEARTBEAT,
                    retry_policy=_VALIDATE_RETRY,
                )

        results = await asyncio.gather(*(_validate(c, ids) for c, ids in by_chunk.items()), return_exceptions=True)
        total = len(by_chunk)
        failed = sum(1 for r in results if isinstance(r, BaseException))
        _enforce_failure_floor("Validate", failed, total)
        validated = sum(r.validated_count for r in results if isinstance(r, ValidateChunkResult))
        if failed:
            workflow.logger.warning(f"Validated {total - failed}/{total} chunk(s); {failed} failed best-effort")
        return validated


@temporalio.workflow.defn(name="review-pr")
class ReviewPRWorkflow:
    """Single-turn PR review: setup → split → review → dedup (incl. combine) → validate → build → publish."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ReviewPRWorkflowInputs:
        return ReviewPRWorkflowInputs(**json.loads(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: ReviewPRWorkflowInputs) -> str:
        repository = inputs.repository
        target = f"PR #{inputs.pr_number}" if inputs.pr_number is not None else f"branch '{inputs.head_branch}'"
        workflow.logger.info(f"ReviewHog · reviewing {target} · {repository}")

        await workflow.execute_activity(
            validate_github_integration_activity,
            ValidateIntegrationInput(team_id=inputs.team_id),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )

        workflow.logger.info("STAGE 1/7 · Fetch PR data")
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
                head_branch=inputs.head_branch,
                signal_report_id=inputs.signal_report_id,
                trigger_source=inputs.trigger_source,
            ),
            start_to_close_timeout=_FETCH_TIMEOUT,
            retry_policy=_RETRY,
        )
        report_id, head_sha, branch = meta.report_id, meta.head_sha, meta.branch
        workflow.logger.info(
            "Captured point-in-time diff snapshot" if meta.snapshotted else "No new diff snapshot this turn"
        )

        # Early-exits: nothing to do this turn — no receipt is appended for these (nothing was done).
        # `already_published` means this exact head was already reviewed AND posted, so re-running the
        # pipeline would recompute the same review and publish would self-skip — burning sandbox cost
        # for no output. New inline comments do NOT force a turn yet (logged in fetch); reacting to
        # comments lands with the "fix the issues" capability — see ARCHITECTURE.md (Stage 5b / Action
        # plane). A no-publish eval run is never gated here (it has no published head), so the
        # frozen-PR eval loop still recomputes to measure reviewer changes. `empty_diff` is the
        # "pushed nothing → do nothing" rule for branch targets.
        if meta.already_published:
            workflow.logger.info(
                f"Review already published for {repository} {target} at {head_sha[:12]}; "
                f"nothing changed this turn ({meta.new_comment_count} new comment(s), not yet acted on) — skipping"
            )
            return report_id
        if meta.empty_diff:
            workflow.logger.info(
                f"Branch '{branch}' has no reviewable diff against its base (pushed nothing); skipping"
            )
            return report_id

        # Resolve the acting user whose enabled perspectives apply (PR author, or the explicit
        # override the CLI and inbox triggers set). Gate here, before any sandbox spend: a non-PostHog
        # author has no perspectives, so skip the review.
        acting = await workflow.execute_activity(
            resolve_acting_user_activity,
            ResolveActingUserInput(
                team_id=inputs.team_id,
                author_login=meta.author_login,
                override_user_id=inputs.acting_user_id,
                report_id=report_id,
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
        # Trigger-aware opt-outs, read off the resolve-time settings snapshot (mid-run edits can't
        # flip gates). Label gates only the cloud path (no explicit acting-user override) — an
        # explicit CLI/eval invocation always runs. Inbox re-checks the receiver-side gate here for
        # snapshot-at-resolve consistency. Manual stays ungated.
        if inputs.trigger_source == TRIGGER_LABEL and inputs.acting_user_id is None and not acting.review_labeled_prs:
            workflow.logger.info(
                f"PR author '{meta.author_login}' (user {acting.acting_user_id}) has labeled-PR reviews "
                "turned off; skipping review"
            )
            return report_id
        if inputs.trigger_source == TRIGGER_INBOX and not acting.review_inbox_prs:
            workflow.logger.info(f"Acting user {acting.acting_user_id} has inbox reviews turned off; skipping review")
            return report_id
        acting_user_id = acting.acting_user_id

        publish_result: PublishResult | None = None
        try:
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

            workflow.logger.info("STAGE 2/7 · Split into chunks")
            chunk_ids: list[int] = await workflow.execute_activity(
                split_chunks_activity,
                stage,
                start_to_close_timeout=_SANDBOX_TIMEOUT,
                heartbeat_timeout=_SANDBOX_HEARTBEAT,
                retry_policy=_RETRY,
            )

            parent_id = workflow.info().workflow_id

            workflow.logger.info("STAGE 3/7 · Review chunks (perspective wave + blind-spot check)")
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

            # Combine + scope-clean run inside the dedup activity (local flatten over the persisted
            # perspective results) — only the survivors' ids come back, never the issue JSON.
            workflow.logger.info("STAGE 4/7 · Combine, scope-clean & deduplicate issues")
            dedup: DedupResult = await workflow.execute_activity(
                dedup_activity,
                stage,
                start_to_close_timeout=_SANDBOX_TIMEOUT,
                heartbeat_timeout=_SANDBOX_HEARTBEAT,
                retry_policy=_RETRY,
            )
            workflow.logger.info(f"Persisted {len(dedup.issue_ids)} finding(s) to the review report")

            workflow.logger.info("STAGE 5/7 · Validate issues")
            await workflow.execute_child_workflow(
                ValidateIssuesWorkflow.run,
                ValidateIssuesInputs(
                    team_id=stage.team_id,
                    user_id=stage.user_id,
                    report_id=stage.report_id,
                    head_sha=stage.head_sha,
                    repository=stage.repository,
                    branch=stage.branch,
                    run_index=stage.run_index,
                    issue_ids=dedup.issue_ids,
                    acting_user_id=acting_user_id,
                ),
                id=f"{parent_id}/validate",
                retry_policy=_RETRY,
            )

            workflow.logger.info("STAGE 6/7 · Build report")
            await workflow.execute_activity(
                build_body_activity,
                BuildBodyInput(
                    team_id=inputs.team_id,
                    report_id=report_id,
                    head_sha=head_sha,
                    run_index=stage.run_index,
                    issue_ids=dedup.issue_ids,
                    urgency_threshold=acting.urgency_threshold,
                ),
                start_to_close_timeout=_QUICK_TIMEOUT,
                retry_policy=_RETRY,
            )

            workflow.logger.info("STAGE 7/7 · Publish review")
            if inputs.publish and meta.pr_number is not None:
                publish_result = await workflow.execute_activity(
                    publish_review_activity,
                    PublishInput(
                        team_id=inputs.team_id,
                        report_id=report_id,
                        head_sha=head_sha,
                        run_index=stage.run_index,
                        owner=inputs.owner,
                        repo=inputs.repo,
                        # The resolved destination: the input PR, or the open PR fetch discovered
                        # for a branch target.
                        pr_number=meta.pr_number,
                        urgency_threshold=acting.urgency_threshold,
                    ),
                    start_to_close_timeout=_QUICK_TIMEOUT,
                    retry_policy=_RETRY,
                )
            elif inputs.publish:
                workflow.logger.info("No PR to publish to (branch target); the review is stored only")
            else:
                workflow.logger.info("Publishing disabled for this run (publish=False)")
        except Exception:
            # The signal report's log records a failed turn too (a receipt per executed turn,
            # completion or failure); best-effort so it can never mask the original error.
            await self._append_code_review_receipt(
                inputs, report_id=report_id, run_index=meta.run_index, outcome="failed", best_effort=True
            )
            raise

        posted = publish_result is not None and publish_result.posted
        # Best-effort like the failed path: the receipt is bookkeeping, and failing (+ retrying) an
        # already-published review over it buys nothing — the retry's already-published early-exit
        # returns before this append anyway, so the receipt would stay lost either way.
        await self._append_code_review_receipt(
            inputs,
            report_id=report_id,
            run_index=meta.run_index,
            outcome="published" if posted else "stored",
            review_url=publish_result.review_url if publish_result is not None else None,
            best_effort=True,
        )

        workflow.logger.info(f"ReviewHog complete · report stored on ReviewReport {report_id}")
        return report_id

    @staticmethod
    async def _append_code_review_receipt(
        inputs: ReviewPRWorkflowInputs,
        *,
        report_id: str,
        run_index: int,
        outcome: str,
        review_url: str | None = None,
        best_effort: bool = False,
    ) -> None:
        """Append the turn's `code_review` receipt to the signal report's artefact log, when linked."""
        if inputs.signal_report_id is None:
            return
        try:
            await workflow.execute_activity(
                append_code_review_artefact_activity,
                AppendCodeReviewArtefactInput(
                    team_id=inputs.team_id,
                    signal_report_id=inputs.signal_report_id,
                    review_report_id=report_id,
                    run_index=run_index,
                    outcome=outcome,
                    review_url=review_url,
                ),
                start_to_close_timeout=_QUICK_TIMEOUT,
                retry_policy=_RETRY,
            )
        except Exception:
            if not best_effort:
                raise
            workflow.logger.warning("Could not append the code_review receipt; continuing without it")
