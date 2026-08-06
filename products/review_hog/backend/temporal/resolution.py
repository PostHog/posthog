"""The resolution stage as a Temporal workflow: settle a PR's unresolved review threads.

`ResolvePRWorkflow` reuses the review pipeline's setup activities (integration check, skill sync,
schema generation) and then runs ONE long activity, `resolve_threads_activity`, which owns the whole
per-PR resolution session: fetch the PR + its unresolved threads, apply the deterministic gates and
pre-filter, drive one warm writable sandbox session with one thread per turn (priority order:
humans → ReviewHog → other bots), and perform the GitHub side effects (reply, resolve) server-side
from each turn's verdict. The session must live inside a single activity — it is an in-process
handle — so the activity is long (hours-scale ceiling) and heartbeats throughout, exactly like the
validation chunk sessions.

Idempotency is per thread, not per activity: every turn's verdict persists as a `thread_verdict`
artefact before its side effects, so an activity retry re-fetches the threads (cheap), skips the
judged-and-delivered ones via the deterministic pre-filter, redelivers any missing GitHub writes,
and spends LLM turns only on what's genuinely left. One gap: the reply mutation isn't idempotent
and the per-thread watermark only advances once the reply is persisted, so a crash in the window
between posting a reply and recording it re-triages that thread on retry — a fresh turn that posts
a second reply. Reply-first deliberately fails toward a visible duplicate rather than a lost reply.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

import temporalio
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import ThreadVerdictArtefact
from products.review_hog.backend.reviewer.constants import (
    MAX_THREADS_PER_RUN,
    RESOLUTION_INITIAL_PERMISSION_MODE,
    RESOLUTION_MAX_ATTEMPTS,
    RESOLUTION_MODEL,
    RESOLUTION_REASONING_EFFORT,
    RESOLUTION_RUNTIME_ADAPTER,
)
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.thread_resolution import ThreadOutcome, ThreadResolution
from products.review_hog.backend.reviewer.persistence import (
    load_thread_verdicts,
    persist_thread_verdict,
    upsert_review_report,
)
from products.review_hog.backend.reviewer.sandbox.executor import (
    MultiTurnSession,
    continue_sandbox_session,
    end_sandbox_session,
    start_sandbox_session,
)
from products.review_hog.backend.reviewer.skill_loader import load_resolution_skill_for_run
from products.review_hog.backend.reviewer.tools.github_client import github_api_request
from products.review_hog.backend.reviewer.tools.github_meta import PRFetcher
from products.review_hog.backend.reviewer.tools.github_threads import (
    ReviewThread,
    ThreadAction,
    classify_thread,
    fetch_unresolved_threads,
    order_threads,
    reply_to_thread,
    resolve_thread,
    should_resolve,
)
from products.review_hog.backend.reviewer.tools.thread_resolution import (
    RESOLUTION_SYSTEM_PROMPT,
    build_resolution_followup_prompt,
    build_resolution_prompt,
)
from products.review_hog.backend.temporal.activities import (
    GenerateSchemasInput,
    SyncReviewSkillsInput,
    ValidateIntegrationInput,
    _installation_auth,
    _sandbox_workflow_id_prefix,
    generate_schemas_activity,
    sync_review_skills_activity,
    validate_github_integration_activity,
)
from products.review_hog.backend.temporal.types import TRIGGER_MANUAL, ResolvePRWorkflowInputs
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import Commit, NoteArtefact, TaskRunArtefact

logger = logging.getLogger(__name__)

_QUICK_TIMEOUT = timedelta(minutes=2)
_FETCH_TIMEOUT = timedelta(minutes=5)
# The session activity spans up to MAX_THREADS_PER_RUN sandbox turns, several minutes each when a
# turn implements + verifies a fix — hours-scale ceiling; the heartbeat still catches dead sandboxes.
_RESOLUTION_TIMEOUT = timedelta(hours=4)
_RESOLUTION_HEARTBEAT = timedelta(minutes=5)
_RETRY = RetryPolicy(maximum_attempts=2)
# The activity's final-attempt turn fallback keys off the same constant — don't let them drift.
_RESOLUTION_RETRY = RetryPolicy(maximum_attempts=RESOLUTION_MAX_ATTEMPTS)


@dataclass
class ResolveThreadsInput:
    team_id: int
    user_id: int
    # Whose selected resolution-criteria skill applies to this run.
    acting_user_id: int
    owner: str
    repo: str
    pr_number: int
    pr_url: str = ""
    trigger_source: str = TRIGGER_MANUAL


@dataclass
class ResolutionRunResult:
    """The run's summary — the same counts the persisted `note` artefact records."""

    report_id: str | None = None
    # Deterministic no-op runs name their reason ("pr_not_open" / "no_unresolved_threads").
    skipped_reason: str | None = None
    # Threads that got an LLM turn this run, and their outcome counts (keyed by ThreadOutcome value).
    triaged: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    # Threads whose persisted verdict only needed its GitHub writes redelivered (no LLM turn).
    redelivered: int = 0
    # Threads skipped as already judged and delivered.
    skipped: int = 0
    # Work-list overflow beyond MAX_THREADS_PER_RUN — named, never silent; the next run continues.
    overflow: int = 0
    failed_turns: int = 0


@dataclass
class _PreparedRun:
    """In-process fetch/gate output — never crosses the Temporal boundary (threads can be big)."""

    report_id: str
    token: str
    installation_id: str | None
    pr_metadata: PRMetadata
    triage: list[ReviewThread]
    redeliver: list[tuple[ReviewThread, ThreadVerdictArtefact]]
    skipped: int
    overflow: int
    skill_name: str
    skill_version: int


def _fetch_pr_metadata(input: ResolveThreadsInput, token: str, installation_id: str | None) -> PRMetadata:
    pr = github_api_request(
        "GET",
        f"/repos/{input.owner}/{input.repo}/pulls/{input.pr_number}",
        token=token,
        installation_id=installation_id,
        endpoint="/repos/{owner}/{repo}/pulls/{pull_number}",
    ).json()
    return PRFetcher(input.owner, input.repo, input.pr_number, token, installation_id).fetch_pr_metadata(pr)


def _prepare_run(input: ResolveThreadsInput) -> _PreparedRun | ResolutionRunResult:
    """Fetch + gate + pre-filter; returns the prepared work-list, or the run result for a clean no-op."""
    token, installation_id = _installation_auth(input.team_id, f"{input.owner}/{input.repo}")
    pr_metadata = _fetch_pr_metadata(input, token, installation_id)
    if pr_metadata.is_fork:
        # Hard refuse, mirroring the review fetch — this stage WRITES to the head branch, and a fork
        # head is a branch we don't own with an attacker-influenced ref.
        raise ApplicationError(
            f"PR {input.owner}/{input.repo}#{input.pr_number} is from a fork; the resolution stage "
            "cannot push to a fork's branch",
            non_retryable=True,
        )
    if pr_metadata.state != "open":
        return ResolutionRunResult(skipped_reason="pr_not_open")

    pr_url = input.pr_url or f"https://github.com/{input.owner}/{input.repo}/pull/{input.pr_number}"
    report_id = upsert_review_report(
        team_id=input.team_id,
        repository=f"{input.owner}/{input.repo}",
        pr_url=pr_url,
        pr_metadata=pr_metadata,
        trigger_source=input.trigger_source,
    )

    threads = fetch_unresolved_threads(
        token=token, owner=input.owner, repo=input.repo, pr_number=input.pr_number, installation_id=installation_id
    )
    verdicts = load_thread_verdicts(team_id=input.team_id, report_id=report_id)
    triage: list[ReviewThread] = []
    redeliver: list[tuple[ReviewThread, ThreadVerdictArtefact]] = []
    skipped = 0
    for thread in threads:
        action = classify_thread(thread, verdicts.get(thread.thread_id))
        if action == ThreadAction.TRIAGE:
            triage.append(thread)
        elif action == ThreadAction.SIDE_EFFECTS:
            redeliver.append((thread, verdicts[thread.thread_id]))
        else:
            skipped += 1

    triage = order_threads(triage)
    overflow = max(0, len(triage) - MAX_THREADS_PER_RUN)
    triage = triage[:MAX_THREADS_PER_RUN]
    if not triage and not redeliver:
        _idle_report(input.team_id, report_id)
        return ResolutionRunResult(report_id=report_id, skipped_reason="no_unresolved_threads", skipped=skipped)

    skill = load_resolution_skill_for_run(input.team_id, input.acting_user_id)
    return _PreparedRun(
        report_id=report_id,
        token=token,
        installation_id=installation_id,
        pr_metadata=pr_metadata,
        triage=triage,
        redeliver=redeliver,
        skipped=skipped,
        overflow=overflow,
        skill_name=skill.skill_name,
        skill_version=skill.version,
    )


def _deliver_side_effects(
    input: ResolveThreadsInput, report_id: str, token: str, installation_id: str | None, verdict: ThreadVerdictArtefact
) -> ThreadVerdictArtefact:
    """Perform the verdict's undelivered GitHub writes, persisting after each so a crash redoes only
    what's still missing.

    The reply lands first (the outcome must be readable even if resolving then fails); the watermark
    advances to our own posted reply so it doesn't re-open triage. A crash between posting the reply
    and recording it (the persist below) leaves the watermark un-advanced, so the retry re-triages the
    thread and can post a duplicate reply — the reply mutation has no idempotency key (module docstring).
    Resolving is etiquette-gated (`should_resolve`) and best-effort — a failed resolve is redelivered by
    the next run's pre-filter.
    """
    updated = verdict
    if not updated.reply_posted:
        body = updated.reply
        if updated.outcome == ThreadOutcome.FIXED.value and updated.commit_sha:
            body += f"\n\nFix commit: https://github.com/{input.owner}/{input.repo}/commit/{updated.commit_sha}"
        comment_id, comment_url = reply_to_thread(
            token=token, thread_id=updated.thread_id, body=body, installation_id=installation_id
        )
        updated = updated.model_copy(
            update={
                "reply_posted": True,
                "reply_url": comment_url,
                "latest_comment_id": comment_id if comment_id is not None else updated.latest_comment_id,
            }
        )
        persist_thread_verdict(team_id=input.team_id, report_id=report_id, verdict=updated)
    if should_resolve(updated) and not updated.resolved:
        try:
            resolved = resolve_thread(token=token, thread_id=updated.thread_id, installation_id=installation_id)
        except Exception:
            logger.exception("Could not resolve thread %s; the next run will retry it", updated.thread_id)
            return updated
        if resolved:
            updated = updated.model_copy(update={"resolved": True})
            persist_thread_verdict(team_id=input.team_id, report_id=report_id, verdict=updated)
    return updated


def _append_task_run(input: ResolveThreadsInput, report_id: str, session: MultiTurnSession) -> None:
    """Link the resolution session's sandbox Task to the report's work log (best-effort)."""
    try:
        ReviewReportArtefact.add_log(
            team_id=input.team_id,
            report_id=report_id,
            content=TaskRunArtefact(
                task_id=str(session.task_run.task_id),
                run_id=str(session.task_run.id),
                product="review_hog",
                type="resolution",
            ),
            attribution=ArtefactAttribution.system(),
        )
    except Exception:
        logger.exception("Could not append the resolution task_run artefact")


def _append_run_note(input: ResolveThreadsInput, report_id: str, result: ResolutionRunResult) -> None:
    """Persist the run's summary as a `note` artefact — the durable form of the outcome table."""
    outcome_bits = ", ".join(f"{name} {count}" for name, count in sorted(result.outcomes.items())) or "none"
    note = (
        f"Resolution run on PR #{input.pr_number}: {result.triaged} thread(s) triaged ({outcome_bits}); "
        f"{result.redelivered} redelivered, {result.skipped} already settled, {result.failed_turns} failed turn(s)."
    )
    if result.overflow:
        note += f" {result.overflow} thread(s) remain beyond the {MAX_THREADS_PER_RUN}-thread run cap; the next run continues."
    try:
        ReviewReportArtefact.add_log(
            team_id=input.team_id,
            report_id=report_id,
            content=NoteArtefact(note=note, author="review_hog_resolution"),
            attribution=ArtefactAttribution.system(),
        )
    except Exception:
        logger.exception("Could not append the resolution run note")


def _idle_report(team_id: int, report_id: str) -> None:
    """Return the report to IDLE after a resolution run (the upsert marked it ACTIVE)."""
    ReviewReport.objects.for_team(team_id).filter(id=report_id).update(status=ReviewReport.Status.IDLE)


def _append_commit_artefact(
    input: ResolveThreadsInput, report_id: str, branch: str, verdict: ThreadVerdictArtefact
) -> None:
    """One `commit` artefact per FIXED thread — the report-side record of what the stage pushed."""
    try:
        ReviewReportArtefact.add_log(
            team_id=input.team_id,
            report_id=report_id,
            content=Commit(
                repository=f"{input.owner}/{input.repo}",
                branch=branch,
                commit_sha=verdict.commit_sha or "",
                message=f"Resolution fix for review thread on {verdict.path or 'the PR'}",
                note=f"Thread {verdict.thread_id}",
            ),
            attribution=ArtefactAttribution.system(),
        )
    except Exception:
        logger.exception("Could not append the resolution commit artefact")


@activity.defn
@scoped_temporal()
@close_db_connections
async def resolve_threads_activity(input: ResolveThreadsInput) -> ResolutionRunResult:
    """Run the whole per-PR resolution session: fetch, gate, triage one thread per warm turn, deliver.

    One activity because the sandbox session is an in-process handle — it cannot cross activity
    boundaries. Retries are cheap anyway: verdicts persist per thread, so a retry redoes unjudged
    threads and any undelivered GitHub writes (with one crash-window exception that can duplicate a
    reply, per the module docstring). A failed turn fails the activity for that cheap retry; only the
    final attempt skips the thread (continuing on a fresh session), mirroring the validation sessions.
    """
    prepared = await database_sync_to_async(_prepare_run, thread_sensitive=False)(input)
    if isinstance(prepared, ResolutionRunResult):
        return prepared

    result = ResolutionRunResult(report_id=prepared.report_id, skipped=prepared.skipped, overflow=prepared.overflow)
    final_attempt = activity.info().attempt >= RESOLUTION_MAX_ATTEMPTS
    session: MultiTurnSession | None = None
    run_ok = False
    try:
        async with Heartbeater():
            # Redeliveries first: pure GitHub writes, no LLM — a crash mid-session must not leave
            # last run's judged threads undelivered behind this run's new turns.
            for _thread, verdict in prepared.redeliver:
                try:
                    await database_sync_to_async(_deliver_side_effects, thread_sensitive=False)(
                        input, prepared.report_id, prepared.token, prepared.installation_id, verdict
                    )
                    result.redelivered += 1
                except Exception:
                    logger.exception("Redelivery failed for thread %s; the next run will retry", verdict.thread_id)

            for thread in prepared.triage:
                try:
                    if session is None:
                        session, resolution = await start_sandbox_session(
                            team_id=input.team_id,
                            user_id=input.user_id,
                            repository=f"{input.owner}/{input.repo}",
                            branch=prepared.pr_metadata.head_branch,
                            prompt=build_resolution_prompt(
                                threads=prepared.triage,
                                thread=thread,
                                pr_metadata=prepared.pr_metadata,
                                skill_name=prepared.skill_name,
                                skill_version=prepared.skill_version,
                            ),
                            system_prompt=RESOLUTION_SYSTEM_PROMPT,
                            model_to_validate=ThreadResolution,
                            step_name="resolution",
                            workflow_id_prefix=_sandbox_workflow_id_prefix("resolution"),
                            runtime_adapter=RESOLUTION_RUNTIME_ADAPTER,
                            model=RESOLUTION_MODEL,
                            reasoning_effort=RESOLUTION_REASONING_EFFORT,
                            initial_permission_mode=RESOLUTION_INITIAL_PERMISSION_MODE,
                        )
                        await database_sync_to_async(_append_task_run, thread_sensitive=False)(
                            input, prepared.report_id, session
                        )
                    else:
                        resolution = await continue_sandbox_session(
                            session,
                            prompt=build_resolution_followup_prompt(thread=thread),
                            model_to_validate=ThreadResolution,
                            label=thread.thread_id,
                        )
                except Exception:
                    if session is None:
                        # The session never opened (sandbox-level) — raise so Temporal retries the
                        # run and a real outage surfaces instead of reading as zero threads handled.
                        raise
                    if not final_attempt:
                        logger.exception(
                            "Resolution turn failed for thread %s; failing the run to retry it", thread.thread_id
                        )
                        raise
                    logger.exception(
                        "Resolution turn failed for thread %s on the final attempt; skipping it", thread.thread_id
                    )
                    result.failed_turns += 1
                    await end_sandbox_session(
                        session, status="failed", error=f"resolution turn failed for thread {thread.thread_id}"
                    )
                    session = None
                    continue

                if resolution.thread_id != thread.thread_id:
                    # The driver knows which thread it sent; an echo slip must not misfile the verdict.
                    logger.warning(
                        "Turn echoed thread id %s for thread %s; keeping the driver's id",
                        resolution.thread_id,
                        thread.thread_id,
                    )
                    resolution = resolution.model_copy(update={"thread_id": thread.thread_id})

                verdict = await database_sync_to_async(_persist_turn_verdict_row, thread_sensitive=False)(
                    input, prepared.report_id, thread, resolution
                )
                if resolution.outcome == ThreadOutcome.FIXED:
                    await database_sync_to_async(_append_commit_artefact, thread_sensitive=False)(
                        input, prepared.report_id, prepared.pr_metadata.head_branch, verdict
                    )
                result.triaged += 1
                result.outcomes[resolution.outcome.value] = result.outcomes.get(resolution.outcome.value, 0) + 1
                try:
                    await database_sync_to_async(_deliver_side_effects, thread_sensitive=False)(
                        input, prepared.report_id, prepared.token, prepared.installation_id, verdict
                    )
                except Exception:
                    # The verdict row still says reply_posted=False, so the next run redelivers.
                    logger.exception("Side effects failed for thread %s; the next run will retry", thread.thread_id)
        run_ok = True
    finally:
        if session is not None:
            await end_sandbox_session(
                session,
                status="completed" if run_ok else "failed",
                error=None if run_ok else "resolution run failed mid-session",
            )

    await database_sync_to_async(_append_run_note, thread_sensitive=False)(input, prepared.report_id, result)
    await database_sync_to_async(_idle_report, thread_sensitive=False)(input.team_id, prepared.report_id)
    return result


def _persist_turn_verdict_row(
    input: ResolveThreadsInput, report_id: str, thread: ReviewThread, resolution: ThreadResolution
) -> ThreadVerdictArtefact:
    """Persist a turn's judgment as a `thread_verdict` artefact (side effects not yet delivered)."""
    verdict = ThreadVerdictArtefact(
        thread_id=thread.thread_id,
        outcome=resolution.outcome.value,
        path=thread.path,
        author_login=thread.author_login,
        author_is_bot=thread.author_is_bot,
        reasoning=resolution.reasoning,
        reply=resolution.reply,
        commit_sha=resolution.commit_sha,
        verification=resolution.verification,
        latest_comment_id=thread.latest_comment_id,
    )
    persist_thread_verdict(team_id=input.team_id, report_id=report_id, verdict=verdict)
    return verdict


@temporalio.workflow.defn(name="resolve-pr")
class ResolvePRWorkflow:
    """Setup activities → the single long resolution-session activity. Deterministic id per PR."""

    @temporalio.workflow.run
    async def run(self, inputs: ResolvePRWorkflowInputs) -> str | None:
        workflow.logger.info(
            f"Resolution stage starting for {inputs.repository}#{inputs.pr_number} (team {inputs.team_id})"
        )
        await workflow.execute_activity(
            validate_github_integration_activity,
            ValidateIntegrationInput(team_id=inputs.team_id),
            start_to_close_timeout=_QUICK_TIMEOUT,
            retry_policy=_RETRY,
        )
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
        result: ResolutionRunResult = await workflow.execute_activity(
            resolve_threads_activity,
            ResolveThreadsInput(
                team_id=inputs.team_id,
                user_id=inputs.user_id,
                acting_user_id=inputs.acting_user_id or inputs.user_id,
                owner=inputs.owner,
                repo=inputs.repo,
                pr_number=inputs.pr_number,
                pr_url=inputs.pr_url,
                trigger_source=inputs.trigger_source,
            ),
            start_to_close_timeout=_RESOLUTION_TIMEOUT,
            heartbeat_timeout=_RESOLUTION_HEARTBEAT,
            retry_policy=_RESOLUTION_RETRY,
        )
        if result.skipped_reason:
            workflow.logger.info(f"Resolution stage skipped: {result.skipped_reason}")
        else:
            workflow.logger.info(
                f"Resolution stage complete: {result.triaged} triaged {result.outcomes}, "
                f"{result.redelivered} redelivered, {result.skipped} already settled, "
                f"{result.overflow} beyond the run cap, {result.failed_turns} failed turn(s)"
            )
        return result.report_id
