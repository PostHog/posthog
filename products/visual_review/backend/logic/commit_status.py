"""The commit status of a commit and run type when the repo's commit status gate is on, as ledger mode needs.

The status is the verdict of the newest run of the commit and run type, read from the database
when it is posted. Whatever triggers a publish, it posts that verdict, so a late finish of an older
run cannot overwrite a newer one. A publish reads again after each post and posts again when the
newest run or its verdict changed in between, so two actions at the same moment end on the newer
verdict without a lock around a GitHub request.
"""

from __future__ import annotations

from django.db import transaction

import structlog

from posthog.dataclasses import frozen

from ..db import WRITER_DB
from ..facade.contracts import NoRunNeededInput
from ..facade.enums import NoRunNeededOutcome, RunGate, RunPurpose, RunStatus
from ..models import Repo, Run
from . import app_urls, baseline_approvals, baselines, ci_status, errors, gating

logger = structlog.get_logger(__name__)

# Posts per publish before the retry task takes over a verdict that keeps changing.
MAX_ROUNDS = 3

NO_RUN_NEEDED_DESCRIPTION = "No visual run needed"


@frozen
class _Status:
    context: str
    state: str
    description: str
    target_url: str


def publishes_by_commit(repo: Repo) -> bool:
    return repo.commit_status_gate_enabled


def _newest_run(repo: Repo, commit_sha: str, run_type: str) -> Run | None:
    return (
        Run.objects.using(WRITER_DB)
        .filter(repo_id=repo.id, team_id=repo.team_id, commit_sha=commit_sha, run_type=run_type)
        .order_by("-created_at", "-id")
        .first()
    )


def _guards_stale_approvals(run: Run) -> bool:
    """Whether a stale approval can fail the run: a pull request run whose gate is this commit status.

    A run with the `ci_job` gate keeps the verdict of its own mode, and a queue run fails on drift by itself.
    """
    return run.gate == RunGate.COMMIT_STATUS and run.purpose != RunPurpose.OBSERVE and run.pr_number is not None


def stale_approval_count(run: Run) -> int:
    """How many approvals the run's verdict rests on are stale, or 0 when the rule does not apply to the run.

    A superseded run counts 0, because only the newest run of a commit decides its status.
    """
    if run.superseded_by_id is not None or not _guards_stale_approvals(run) or not publishes_by_commit(run.repo):
        return 0
    return len(baseline_approvals.stale_approvals(run))


@frozen
class RunFacts:
    """What the commit status of one run depends on, read before `status_verdict` decides.

    A count that the verdict does not reach for the run stays 0, so its query is not made.
    """

    status: RunStatus
    error_message: str
    purpose: RunPurpose
    approved: bool
    is_partial: bool
    # A finished default-branch run gates nothing, so it reports on its own context and never fails.
    tracking: bool
    changes_summary: str
    unresolved: int = 0
    awaiting_finalize: int = 0
    hidden_by_quarantine: int = 0
    # 0 also when the stale-approval rule does not apply to the run.
    stale_approvals: int = 0


@frozen
class StatusVerdict:
    """The state and description of a commit status."""

    state: str
    description: str


def _review_verdict(facts: RunFacts) -> StatusVerdict:
    if facts.purpose == RunPurpose.OBSERVE:
        if facts.changes_summary:
            return StatusVerdict(
                state="failure", description=f"Visual changes nobody approved: {facts.changes_summary}"
            )
        return StatusVerdict(state="success", description=gating.success_text(facts.hidden_by_quarantine))
    if facts.approved:
        return StatusVerdict(state="success", description="Visual changes approved")
    if facts.unresolved > 0:
        return StatusVerdict(state="failure", description=f"Visual changes detected: {facts.changes_summary}")
    if facts.awaiting_finalize > 0:
        return StatusVerdict(
            state="failure",
            description=f"{facts.awaiting_finalize} approved change(s) not finalized. Finalize the run to pass this check",
        )
    return StatusVerdict(state="success", description=gating.success_text(facts.hidden_by_quarantine))


def _gating_verdict(facts: RunFacts) -> StatusVerdict:
    """The review verdict, failed when a passing pull request run rests on an approval the ledger has moved past.

    A re-run on the same commit resolves at the same merge-base and passes again, so only this
    check keeps such a run red until the branch is updated.
    """
    verdict = _review_verdict(facts)
    if verdict.state != "success" or facts.stale_approvals == 0:
        return verdict
    noun = "snapshot" if facts.stale_approvals == 1 else "snapshots"
    return StatusVerdict(
        state="failure",
        description=f"Baseline changed after approval: {facts.stale_approvals} {noun}. Update the branch and review again",
    )


def _verdict_without_partial_note(facts: RunFacts) -> StatusVerdict:
    if facts.status in (RunStatus.PENDING, RunStatus.PROCESSING):
        return StatusVerdict(state="pending", description="Visual review in progress")
    if facts.status == RunStatus.FAILED or facts.error_message:
        return StatusVerdict(state="error", description=f"Visual review failed: {facts.error_message[:100]}")
    if facts.tracking:
        summary = facts.changes_summary
        description = f"Tracking only: {summary} recorded" if summary else "Tracking only: no visual changes"
        return StatusVerdict(state="success", description=description)
    return _gating_verdict(facts)


def status_verdict(facts: RunFacts) -> StatusVerdict:
    """The state and description of the commit status for one run."""
    verdict = _verdict_without_partial_note(facts)
    if facts.is_partial and not facts.tracking:
        return StatusVerdict(state=verdict.state, description=f"{verdict.description} (partial run)")
    return verdict


def _run_facts(run: Run, repo: Repo) -> RunFacts:
    """Read what the verdict of the run needs, in the order the verdict reads it.

    Counts go to the writer, because a publish has to see the write that triggered it.
    """
    tracking = run.purpose == RunPurpose.OBSERVE and baselines._run_is_on_default_branch(repo, run.branch)
    summary = gating._changes_summary(run)
    decided_without_counts = (
        run.status in (RunStatus.PENDING, RunStatus.PROCESSING, RunStatus.FAILED) or bool(run.error_message) or tracking
    )
    unresolved = awaiting = hidden = stale = 0
    if not decided_without_counts:
        if run.purpose == RunPurpose.OBSERVE:
            # Drift fails a queue run before the quarantine count matters.
            hidden = 0 if summary else gating.count_hidden_by_quarantine(run, WRITER_DB)
        elif not run.approved:
            unresolved = gating.count_unresolved(run, WRITER_DB)
            awaiting = 0 if unresolved else gating.count_awaiting_finalize(run, WRITER_DB)
            hidden = 0 if unresolved or awaiting else gating.count_hidden_by_quarantine(run, WRITER_DB)
        # A run that already fails on its review needs no stale count.
        if _guards_stale_approvals(run) and unresolved == 0 and awaiting == 0:
            stale = len(baseline_approvals.stale_approvals(run))
    return RunFacts(
        status=RunStatus(run.status),
        error_message=run.error_message,
        purpose=RunPurpose(run.purpose),
        approved=run.approved,
        is_partial=run.is_partial,
        tracking=tracking,
        changes_summary=summary,
        unresolved=unresolved,
        awaiting_finalize=awaiting,
        hidden_by_quarantine=hidden,
        stale_approvals=stale,
    )


def _status_of(run: Run, repo: Repo) -> _Status:
    facts = _run_facts(run, repo)
    context = ci_status.gating_context(run.run_type)
    if facts.tracking:
        context = f"{context} (tracking)"
    verdict = status_verdict(facts)
    return _Status(
        context=context, state=verdict.state, description=verdict.description, target_url=app_urls.run_url(run, repo)
    )


def _current_status(repo: Repo, commit_sha: str, run_type: str) -> _Status | None:
    run = _newest_run(repo, commit_sha, run_type)
    if run is None:
        return None
    return _status_of(run, repo)


def _send(repo: Repo, commit_sha: str, status: _Status) -> ci_status.StatusPost:
    return ci_status._send_commit_status(
        repo,
        commit_sha,
        context=status.context,
        state=status.state,
        description=status.description,
        target_url=status.target_url,
    )


def publish_rounds(repo: Repo, commit_sha: str, run_type: str) -> bool:
    """Post the verdict of the newest run until a read after the post finds it unchanged.

    Returns False when the status may not be settled: GitHub refused a post, a read raised, or
    the verdict still changed after the last round. The caller then retries later.
    """
    try:
        status = _current_status(repo, commit_sha, run_type)
        for _round in range(MAX_ROUNDS):
            if status is None:
                return True
            posted = _send(repo, commit_sha, status)
            if posted == ci_status.StatusPost.REFUSED:
                return False
            if posted == ci_status.StatusPost.SKIPPED:
                return True
            newer = _current_status(repo, commit_sha, run_type)
            if newer == status:
                return True
            status = newer
    except Exception:
        logger.warning(
            "visual_review.commit_status_publish_failed", repo_id=str(repo.id), commit_sha=commit_sha, exc_info=True
        )
        return False
    logger.info("visual_review.commit_status_kept_changing", repo_id=str(repo.id), commit_sha=commit_sha)
    return False


def schedule_publish(repo: Repo, commit_sha: str, run_type: str) -> None:
    """Publish through the task once the caller's transaction commits, so a refused post is retried."""
    from ..tasks.tasks import (
        publish_visual_review_commit_status,  # noqa: PLC0415 — avoids the logic/tasks circular import
    )

    team_id, repo_id = repo.team_id, str(repo.id)
    try:
        # After the commit, so the task never reads the state from before the write that triggered it.
        transaction.on_commit(
            lambda: publish_visual_review_commit_status.delay(team_id, repo_id, commit_sha, run_type),
            using=WRITER_DB,
            robust=True,
        )
    except Exception:
        logger.warning(
            "visual_review.commit_status_publish_enqueue_failed",
            repo_id=str(repo.id),
            commit_sha=commit_sha,
            exc_info=True,
        )


def publish_for_pull_requests(repo: Repo, pull_requests: set[tuple[int, str]]) -> None:
    """Publish again, through the task, for the newest run of each (pull request number, run type).

    Only runs that `_guards_stale_approvals` accepts and no newer run superseded are looked up. A
    merge-queue run can carry the pull request's number too, and a stale approval never changes its verdict.
    """
    if not pull_requests:
        return
    newest_runs = (
        Run.objects.using(WRITER_DB)
        .filter(
            repo_id=repo.id,
            pr_number__in={pr_number for pr_number, _run_type in pull_requests},
            run_type__in={run_type for _pr_number, run_type in pull_requests},
            gate=RunGate.COMMIT_STATUS,
            superseded_by__isnull=True,
        )
        .exclude(purpose=RunPurpose.OBSERVE)
        .order_by("pr_number", "run_type", "-created_at", "-id")
        .distinct("pr_number", "run_type")
        .values_list("pr_number", "run_type", "commit_sha")
    )
    commits = {
        (commit_sha, run_type)
        for pr_number, run_type, commit_sha in newest_runs
        if (pr_number, run_type) in pull_requests
    }
    for commit_sha, run_type in sorted(commits):
        schedule_publish(repo, commit_sha, run_type)


def publish(repo: Repo, commit_sha: str, run_type: str) -> None:
    """Publish the commit status of a commit and run type. Every status that comes from a run goes through here.

    A post that does not settle is retried by a task, which carries no verdict and publishes what
    holds when it runs.
    """
    if not publish_rounds(repo, commit_sha, run_type):
        schedule_publish(repo, commit_sha, run_type)


def publish_for_run(run: Run) -> None:
    """Publish the status of a run's commit once the caller's transaction commits. Does nothing with the gate off.

    Inside the transaction a publish would hold its row locks during the GitHub requests, and could
    read state that a publisher in another transaction overtakes.
    """
    repo = run.repo
    if not publishes_by_commit(repo):
        return
    commit_sha, run_type = run.commit_sha, run.run_type
    transaction.on_commit(lambda: publish(repo, commit_sha, run_type), using=WRITER_DB)


def no_run_needed_detail(outcome: NoRunNeededOutcome, run_type: str) -> str:
    context = ci_status.gating_context(run_type)
    if outcome == NoRunNeededOutcome.POSTED:
        return f'Posted "{NO_RUN_NEEDED_DESCRIPTION}" to {context}.'
    if outcome == NoRunNeededOutcome.RUN_EXISTS:
        return f"A {run_type} run exists for this commit and sets {context}. Nothing posted."
    return "This repo does not use the commit status as its gate, so the CI job is the check. Nothing posted."


def report_no_run_needed(repo: Repo, report: NoRunNeededInput) -> NoRunNeededOutcome:
    """Post a passing status for a commit that CI decided needs no visual run. Stores nothing.

    Raises `CommitStatusNotPostedError` when GitHub does not take the post, so the CI job that
    reported fails and its re-run repairs the miss.
    """
    if not publishes_by_commit(repo):
        return NoRunNeededOutcome.STATUS_GATE_OFF
    if _newest_run(repo, report.commit_sha, report.run_type) is not None:
        return NoRunNeededOutcome.RUN_EXISTS

    context = ci_status.gating_context(report.run_type)
    posted = ci_status._send_commit_status(
        repo,
        report.commit_sha,
        context=context,
        state="success",
        description=NO_RUN_NEEDED_DESCRIPTION,
        target_url=None,
    )
    if posted != ci_status.StatusPost.POSTED:
        raise errors.CommitStatusNotPostedError(
            f"GitHub did not accept the status {context} for commit {report.commit_sha[:12]}. "
            "Re-run this job to report it again."
        )
    logger.info(
        "visual_review.no_run_needed_reported",
        repo_id=str(repo.id),
        commit_sha=report.commit_sha,
        run_type=report.run_type,
        branch=report.branch,
        pr_number=report.pr_number,
    )
    # A run created while the report posted owns the status, and the report must not keep it green.
    if _newest_run(repo, report.commit_sha, report.run_type) is not None:
        publish(repo, report.commit_sha, report.run_type)
    return NoRunNeededOutcome.POSTED
