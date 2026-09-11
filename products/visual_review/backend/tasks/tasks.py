"""
Celery tasks for visual_review.

Async entrypoints that call business logic.
Keep task functions thin — only call logic/diffing methods.

NOTE: Imports are done inside functions to avoid circular imports
when Celery loads this module at startup.
"""

import time
from datetime import date
from uuid import UUID

from django.core.cache import cache

import structlog
from celery import shared_task
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from posthog.exceptions_capture import capture_exception
from posthog.models.scoping import with_team_scope
from posthog.scoping_audit import skip_team_scope_audit

from ..db import READER_DB
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
    from posthog.egress.github.transport import GitHubRateLimitError

    from ..diffing import count_processed_diffs, process_diffs
    from ..logic import runs, uploads

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
        except GitHubRateLimitError as e:
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
                countdown = e.retry_after or 60
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
    name="products.visual_review.backend.tasks.sweep_visual_review_retention",
    ignore_result=True,
)
@skip_team_scope_audit  # cross-team housekeeping; sweep_repo scopes every query to the repo's team
def sweep_visual_review_retention() -> None:
    """Apply the retention policy to every repo.

    One repo's failure must not stop the rest, so each repo is swept on its
    own and the next daily run retries whatever failed.
    """
    from ..logic import retention  # noqa: PLC0415 — avoids the logic/tasks circular import

    deadline = time.monotonic() + retention.SWEEP_TIME_BUDGET_SECONDS
    # A handful of rows, materialized so the sweep does not hold a reader cursor
    # open for its whole run.
    # nosemgrep: idor-lookup-without-team — cross-team retention sweep, no user input
    repos = list(Repo.objects.unscoped().using(READER_DB).order_by("created_at"))
    repos = retention.rotate_for_day(repos, date.today())
    for swept, repo in enumerate(repos):
        if time.monotonic() >= deadline:
            logger.warning(
                "visual_review.retention_sweep_budget_exhausted",
                repos_swept=swept,
                repos_total=len(repos),
            )
            break
        started = time.monotonic()
        try:
            result = retention.sweep_repo(repo, deadline=deadline)
        except Exception as e:
            capture_exception(e)
            logger.exception(
                "visual_review.retention_sweep_failed",
                repo_id=str(repo.id),
                team_id=repo.team_id,
            )
            continue

        logger.info(
            "visual_review.retention_sweep_completed",
            repo_id=str(repo.id),
            team_id=repo.team_id,
            runs_deleted=result.runs_deleted,
            artifacts_deleted=result.artifacts_deleted,
            objects_leaked=result.objects_leaked,
            duration_seconds=round(time.monotonic() - started, 1),
        )


@shared_task(
    name="products.visual_review.backend.tasks.send_visual_review_debt_digests",
    ignore_result=True,
)
@skip_team_scope_audit  # cross-team beat sweep; the per-repo task below scopes every query
def send_visual_review_debt_digests() -> None:
    """Fan out to every repo, one task each.

    One repo's failure must not stop the rest, and nothing is stored about what was sent, so the
    next morning's run recomputes and resends whatever is still owed.
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
