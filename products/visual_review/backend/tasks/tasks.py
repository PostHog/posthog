"""
Celery tasks for visual_review.

Async entrypoints that call business logic.
Keep task functions thin — only call logic/diffing methods.

NOTE: Imports are done inside functions to avoid circular imports
when Celery loads this module at startup.
"""

from uuid import UUID, uuid4

from django.core.cache import cache

import structlog
from celery import shared_task
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from posthog.models.scoping import with_team_scope
from posthog.scoping_audit import skip_team_scope_audit

from ..logic.errors import HashIntegrityError
from ..models import Repo

logger = structlog.get_logger(__name__)
TRACER = trace.get_tracer(__name__)

# Long enough that a slow repo's Slack round trips finish inside it, short enough that a worker
# killed mid-run does not hold the next scheduled run out. A held lock costs one day of reminders,
# which the next run resends.
_DEBT_DIGEST_LOCK_SECONDS = 900

# A child task worth running is a child task worth running today. A worker draining a backlog past
# this drops it, and the next morning's run recomputes what is still owed.
_DEBT_DIGEST_EXPIRY_SECONDS = 60 * 60
# The next scheduled run does the same work, so a child that waited past it is dropped.
_BASELINE_ADVANCE_EXPIRY_SECONDS = 5 * 60
_BASELINE_APPROVALS_EXPIRY_SECONDS = 60 * 60
# Long enough for a repo's GitHub reads, short enough that a killed worker does not block the next run.
_BASELINE_LEDGER_LOCK_SECONDS = 15 * 60
# Right after a merge GitHub can still show the pull request as open, which leaves its commit
# unresolved. A push pass asks again after each of these, then the periodic task takes over.
_BASELINE_LEDGER_FOLLOW_UP_COUNTDOWNS = (5, 15, 45)
# A notice that sat in a backed-up queue no longer reports something that just happened.
QUARANTINE_NOTICE_EXPIRY_SECONDS = 15 * 60

# Past the sweep budget in logic/retention.py and below the grace period a deploy gives a busy
# worker. A sweep that overruns its budget then fails with a logged error. Without the limit the
# deploy kills the worker, and nothing records that the sweep stopped.
_RETENTION_SWEEP_SOFT_TIME_LIMIT_SECONDS = 18 * 60


@shared_task(
    name="products.visual_review.backend.tasks.emit_run_processing_metrics",
    ignore_result=True,
)
@with_team_scope()
def emit_run_processing_metrics(team_id: int, run_id: str, outcome: str, diffed_count: int) -> None:
    from ..logic import runs  # noqa: PLC0415 — avoids the logic/tasks circular import

    runs.capture_run_processing_metrics(UUID(run_id), outcome=outcome, diffed_count=diffed_count)


@shared_task(
    name="products.visual_review.backend.tasks.process_run_diffs",
    bind=True,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
@with_team_scope()
def process_run_diffs(self, team_id: int, run_id: str) -> None:
    """
    Verify uploads, create artifacts, and process diffs for a run.

    Called after CI signals that all artifacts have been uploaded.
    Verifies hash integrity of new uploads before creating Artifact
    records and computing diffs.
    """
    from ..diffing import count_processed_diffs, process_diffs
    from ..logic import runs, uploads
    from ..logic.github_api import GITHUB_READ_REFUSED

    run_uuid = UUID(run_id)
    outcome = "completed"
    diffed_count = 0
    retrying = False

    # Phase timings go to OTel spans (where is time spent); counts go to the
    # vr_run_processed event (how many runs, how many diffs).
    with TRACER.start_as_current_span("visual_review.process_run_diffs") as span:
        span.set_attribute("visual_review.run_id", run_id)
        span.set_attribute("visual_review.team_id", team_id)
        try:
            logger.info("visual_review.diff_processing_started", run_id=run_id, team_id=team_id)

            with TRACER.start_as_current_span("visual_review.verify_uploads"):
                uploads.verify_uploads_and_create_artifacts(run_uuid)
            with TRACER.start_as_current_span("visual_review.process_diffs") as diff_span:
                diffed_count = process_diffs(run_uuid)
                diff_span.set_attribute("visual_review.attempt_diffed_count", diffed_count)
            with TRACER.start_as_current_span("visual_review.finish_processing"):
                runs.finish_processing(run_uuid)

            logger.info("visual_review.diff_processing_completed", run_id=run_id, team_id=team_id)
        except HashIntegrityError as e:
            outcome = "hash_integrity_failed"
            logger.warning("visual_review.hash_integrity_failed", run_id=run_id, error=str(e))
            runs.finish_processing(run_uuid, error_message=str(e))
        except GITHUB_READ_REFUSED as e:
            outcome = "rate_limited"
            logger.warning(
                "visual_review.diff_processing_rate_limited",
                run_id=run_id,
                retry=self.request.retries,
                max_retries=self.max_retries,
            )
            if self.max_retries is not None and self.request.retries >= self.max_retries:
                outcome = "rate_limit_exhausted"
                runs.finish_processing(run_uuid, error_message="GitHub API rate limit exceeded after retries")
            else:
                retrying = True
                countdown = getattr(e, "retry_after", None) or 60
                self.retry(countdown=min(countdown, 600), exc=e)
        except Exception as e:
            outcome = "failed"
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.exception("visual_review.diff_processing_failed", run_id=run_id, team_id=team_id, error=str(e))
            runs.finish_processing(run_uuid, error_message=str(e))
            raise
        finally:
            span.set_attribute("visual_review.outcome", outcome)
            # Skip on retry: the run isn't terminal yet and will emit on its next attempt.
            if not retrying:
                try:
                    cumulative_diffed_count = count_processed_diffs(run_uuid)
                except Exception:
                    logger.warning("visual_review.diff_count_failed", run_id=run_id, exc_info=True)
                    cumulative_diffed_count = diffed_count
                runs.capture_run_processing_metrics(run_uuid, outcome=outcome, diffed_count=cumulative_diffed_count)


@shared_task(
    name="products.visual_review.backend.tasks.post_approval_comment",
    bind=True,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
@with_team_scope()
def post_approval_comment(self, team_id: int, run_id: str, add_images: bool = False) -> None:
    """Update the PR comment in place with the approved-changes summary.

    Best-effort: failures don't block the approval flow. Retries on GitHub
    rate-limit errors only. ``add_images`` embeds the before/after snapshot
    images when the reviewer opted in at finalize time.
    """
    from posthog.egress.github.transport import GitHubRateLimitError

    from ..logic import comments

    run_uuid = UUID(run_id)

    try:
        comments.post_approval_comment_for_run(run_uuid, team_id=team_id, add_images=add_images)
    except GitHubRateLimitError as e:
        logger.warning(
            "visual_review.approval_comment_rate_limited",
            run_id=run_id,
            retry=self.request.retries,
            max_retries=self.max_retries,
        )
        try:
            countdown = e.retry_after or 60
            self.retry(countdown=min(countdown, 600), exc=e)
        except self.MaxRetriesExceededError:
            logger.warning("visual_review.approval_comment_giving_up", run_id=run_id)
    except Exception:
        logger.exception("visual_review.approval_comment_task_failed", run_id=run_id, team_id=team_id)


@shared_task(
    name="products.visual_review.backend.tasks.sweep_visual_review_runs",
    ignore_result=True,
    soft_time_limit=_RETENTION_SWEEP_SOFT_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit  # cross-team housekeeping; sweep_repo_runs scopes every query to the repo's team
def sweep_visual_review_runs() -> None:
    from ..logic import retention  # noqa: PLC0415 — avoids the logic/tasks circular import

    retention.sweep_every_repo("runs", retention.sweep_repo_runs)


@shared_task(
    name="products.visual_review.backend.tasks.sweep_visual_review_artifacts",
    ignore_result=True,
    soft_time_limit=_RETENTION_SWEEP_SOFT_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit  # cross-team housekeeping; sweep_repo_artifacts scopes every query to the repo's team
def sweep_visual_review_artifacts() -> None:
    from ..logic import retention  # noqa: PLC0415 — avoids the logic/tasks circular import

    retention.sweep_every_repo("artifacts", retention.sweep_repo_artifacts)


@shared_task(
    name="products.visual_review.backend.tasks.send_visual_review_debt_digests",
    ignore_result=True,
)
@skip_team_scope_audit  # cross-team beat sweep; the per-repo task below scopes every query
def send_visual_review_debt_digests() -> None:
    """Fan out to every repo, one task each.

    One repo's failure must not stop the rest, and nothing is stored about what was sent, so next
    Monday's run recomputes and resends whatever is still owed.
    """
    from ..logic import debt_digest  # noqa: PLC0415 — avoids the logic/tasks circular import

    for repo in debt_digest.repos_in_scope():
        send_visual_review_debt_digest.apply_async(
            args=(repo.team_id, str(repo.id)), expires=_DEBT_DIGEST_EXPIRY_SECONDS
        )


@shared_task(
    name="products.visual_review.backend.tasks.send_visual_review_debt_digest",
    ignore_result=True,
)
@with_team_scope()
def send_visual_review_debt_digest(team_id: int, repo_id: str) -> None:
    """Post one repo's digest.

    The lock is what stops a retried or double-scheduled run from posting the same reminders twice.
    Nothing records what was sent, so an overlapping run has no other way to tell.
    """
    from ..logic import debt_digest  # noqa: PLC0415 — avoids the logic/tasks circular import

    lock_key = f"visual_review_debt_digest:{repo_id}"
    if not cache.add(lock_key, "locked", timeout=_DEBT_DIGEST_LOCK_SECONDS):
        logger.info("visual_review.debt_digest_already_running", repo_id=repo_id, team_id=team_id)
        return

    repo = Repo.objects.filter(id=UUID(repo_id), team_id=team_id).first()
    if repo is None:
        logger.warning("visual_review.debt_digest_repo_missing", repo_id=repo_id, team_id=team_id)
        return

    debt_digest.send_debt_digest(repo, mode=debt_digest.MODE_LIVE)


@shared_task(
    name="products.visual_review.backend.tasks.notify_quarantine_owners",
    ignore_result=True,
)
@with_team_scope()
def notify_quarantine_owners(team_id: int, entry_id: str) -> None:
    """Tell the team that owns a just-quarantined story, in its Slack channel."""
    from ..logic import quarantine_notice  # noqa: PLC0415 — avoids the logic/tasks circular import

    try:
        quarantine_notice.send_quarantine_notice(UUID(entry_id), team_id)
    except Exception:
        # Nothing retries a notice: a late one no longer reports something that just happened.
        logger.warning("visual_review.quarantine_notice_failed", entry_id=entry_id, team_id=team_id, exc_info=True)


@shared_task(
    name="products.visual_review.backend.tasks.notify_auto_quarantine_limit",
    ignore_result=True,
)
@with_team_scope()
def notify_auto_quarantine_limit(team_id: int, repo_id: str, automatic_count: int) -> None:
    """Tell the visual review maintainers that the daily limit stopped automatic quarantines."""
    from ..logic import quarantine_notice  # noqa: PLC0415 — avoids the logic/tasks circular import

    try:
        quarantine_notice.send_daily_limit_notice(UUID(repo_id), team_id, automatic_count)
    except Exception:
        # Nothing retries: the limit warning is also in the logs and in every capped proof event.
        logger.warning("visual_review.auto_quarantine_limit_notice_failed", repo_id=repo_id, exc_info=True)


@shared_task(
    name="products.visual_review.backend.tasks.reconcile_quarantine_lifts",
    bind=True,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
@with_team_scope()
def reconcile_quarantine_lifts(self, team_id: int, run_id: str) -> None:
    """Apply the pending lift requests that a completed default-branch run proves ready."""
    from posthog.egress.github.transport import GitHubRateLimitError

    from ..logic import quarantine_lifts  # noqa: PLC0415 — avoids the logic/tasks circular import

    try:
        quarantine_lifts.reconcile_lift_requests(UUID(run_id))
    except GitHubRateLimitError as e:
        logger.warning(
            "visual_review.quarantine_lift_rate_limited",
            run_id=run_id,
            retry=self.request.retries,
            max_retries=self.max_retries,
        )
        # `retry(exc=e)` re-raises `e` once the budget is spent, so check the budget first.
        if self.max_retries is not None and self.request.retries >= self.max_retries:
            # The next default-branch run checks the same requests again.
            logger.warning("visual_review.quarantine_lift_giving_up", run_id=run_id)
            return
        raise self.retry(countdown=min(e.retry_after or 60, 600), exc=e)


@shared_task(
    name="products.visual_review.backend.tasks.release_clean_quarantines",
    ignore_result=True,
)
@with_team_scope()
def release_clean_quarantines(team_id: int, run_id: str) -> None:
    """Lift the quarantines that a clean week of trusted runs covers, as the repo's mode says."""
    from posthog.egress.github.transport import GitHubRateLimitError

    from ..logic import auto_lift  # noqa: PLC0415 — avoids the logic/tasks circular import

    try:
        auto_lift.release_clean_quarantines(UUID(run_id))
    except GitHubRateLimitError:
        # Nothing retries: a later default-branch run checks the same quarantines again.
        logger.warning("visual_review.release_clean_quarantines_rate_limited", run_id=run_id, team_id=team_id)


@shared_task(
    name="products.visual_review.backend.tasks.reconcile_visual_review_baseline_ledgers",
    ignore_result=True,
)
@skip_team_scope_audit  # cross-team beat sweep; the per-repo task below scopes every query
def reconcile_visual_review_baseline_ledgers(reconcile_approvals: bool = False) -> None:
    """Fan out to every repo in shadow or ledger mode, one task each, so one repo's failure stops no other.

    Without `reconcile_approvals` each child moves the ledger forward. With it, each child
    reconciles the open approvals with their pull requests instead.
    """
    from ..logic import ledger_advance  # noqa: PLC0415 — avoids the logic/tasks circular import

    expires = _BASELINE_APPROVALS_EXPIRY_SECONDS if reconcile_approvals else _BASELINE_ADVANCE_EXPIRY_SECONDS
    for repo in ledger_advance.repos_with_ledger():
        reconcile_visual_review_baseline_ledger.apply_async(
            args=(repo.team_id, str(repo.id)), kwargs={"reconcile_approvals": reconcile_approvals}, expires=expires
        )


def _reconcile_baseline_ledger(repo: Repo, reconcile_approvals: bool) -> None:
    from posthog.egress.limiter.policies import Priority

    from ..logic import ledger_advance  # noqa: PLC0415 — avoids the logic/tasks circular import

    if reconcile_approvals:
        ledger_advance.reconcile_open_approvals(repo, Priority.BATCH)
        logger.info("visual_review.baseline_approvals_reconciled", repo_id=str(repo.id), team_id=repo.team_id)
        return
    result = ledger_advance.advance(repo, Priority.BATCH)
    logger.info(
        "visual_review.baseline_ledger_advanced",
        repo_id=str(repo.id),
        team_id=repo.team_id,
        commits_added=result.commits_added,
        commits_resolved_late=result.commits_resolved_late,
        approvals_landed=result.approvals_landed,
    )


@shared_task(
    name="products.visual_review.backend.tasks.reconcile_visual_review_baseline_ledger",
    ignore_result=True,
)
@with_team_scope()
def reconcile_visual_review_baseline_ledger(team_id: int, repo_id: str, reconcile_approvals: bool = False) -> None:
    """Move one repo's ledger forward, or reconcile its open approvals with their pull requests."""
    from ..logic.github_api import GITHUB_READ_REFUSED  # noqa: PLC0415 — avoids the logic/tasks circular import

    # The ledger lock already keeps the writes apart. This lock saves the GitHub reads of a run
    # that overlaps one still in progress. Each kind has its own key, so a slow advance never
    # skips the hourly reconcile.
    kind = "approvals" if reconcile_approvals else "advance"
    lock_key = f"visual_review_baseline_ledger:{repo_id}:{kind}"
    token = uuid4().hex
    if not cache.add(lock_key, token, timeout=_BASELINE_LEDGER_LOCK_SECONDS):
        logger.info("visual_review.baseline_ledger_already_running", repo_id=repo_id, team_id=team_id, kind=kind)
        return
    try:
        repo = Repo.objects.filter(id=UUID(repo_id), team_id=team_id).first()
        if repo is None:
            logger.warning("visual_review.baseline_ledger_repo_missing", repo_id=repo_id, team_id=team_id)
            return
        _reconcile_baseline_ledger(repo, reconcile_approvals)
    except GITHUB_READ_REFUSED as e:
        # The next scheduled run reads the same commits and pull requests again.
        logger.warning(
            "visual_review.baseline_ledger_read_refused",
            repo_id=repo_id,
            team_id=team_id,
            kind=kind,
            refusal=type(e).__name__,
        )
    finally:
        if cache.get(lock_key) == token:
            cache.delete(lock_key)


def enqueue_baseline_ledger_advance_after_push(team_id: int, repo_id: str) -> None:
    advance_visual_review_baseline_ledger_after_push.apply_async(
        args=(team_id, repo_id), expires=_BASELINE_ADVANCE_EXPIRY_SECONDS
    )


@shared_task(
    name="products.visual_review.backend.tasks.advance_visual_review_baseline_ledger_after_push",
    bind=True,
    ignore_result=True,
    max_retries=len(_BASELINE_LEDGER_FOLLOW_UP_COUNTDOWNS),
)
@with_team_scope()
def advance_visual_review_baseline_ledger_after_push(self, team_id: int, repo_id: str) -> None:
    """Move one repo's ledger forward after a push to its default branch.

    It takes no cache lock. `advance` is safe for concurrent callers, and the periodic task's lock
    only saves duplicate GitHub reads. A push that skipped on that lock would be lost when the pass
    holding it read the branch before the merge.
    """
    from posthog.egress.limiter.policies import Priority

    from ..logic import ledger_advance  # noqa: PLC0415 — avoids the logic/tasks circular import
    from ..logic.github_api import GITHUB_READ_REFUSED  # noqa: PLC0415 — avoids the logic/tasks circular import

    repo = Repo.objects.filter(id=UUID(repo_id), team_id=team_id).first()
    if repo is None:
        logger.warning("visual_review.baseline_ledger_repo_missing", repo_id=repo_id, team_id=team_id)
        return
    try:
        # The merge gate waits on this pass, so it is not shed with the periodic reads at BATCH.
        result = ledger_advance.advance(repo, Priority.NORMAL)
    except GITHUB_READ_REFUSED as e:
        # The next scheduled run reads the same commits again.
        logger.warning(
            "visual_review.baseline_ledger_read_refused",
            repo_id=repo_id,
            team_id=team_id,
            kind="advance",
            trigger="push",
            refusal=type(e).__name__,
        )
        return
    logger.info(
        "visual_review.baseline_ledger_advanced",
        repo_id=repo_id,
        team_id=team_id,
        trigger="push",
        retries=self.request.retries,
        commits_added=result.commits_added,
        commits_resolved_late=result.commits_resolved_late,
        commits_unresolved_recently=result.commits_unresolved_recently,
        approvals_landed=result.approvals_landed,
    )
    if not result.commits_unresolved_recently:
        return
    if self.max_retries is not None and self.request.retries >= self.max_retries:
        return
    countdown = _BASELINE_LEDGER_FOLLOW_UP_COUNTDOWNS[self.request.retries]
    # Several pushes inside the window would each start a follow-up. The mark lives until this
    # one runs, so a repo has at most one waiting at a time.
    if not cache.add(f"visual_review_baseline_ledger:{repo_id}:advance:follow_up", "1", timeout=countdown):
        return
    raise self.retry(countdown=countdown)
