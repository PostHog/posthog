"""Run lifecycle: create, ingest snapshots, classify on completion, finish, recompute."""

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

import structlog

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.ph_client import ph_scoped_capture

from ..classifier import SnapshotClassifier
from ..db import WRITER_DB
from ..facade.contracts import CreateRunInput
from ..facade.enums import RunStatus, SnapshotResult
from ..models import Repo, Run, RunSnapshot, ToleratedHash
from ..storage import ArtifactStorage
from . import artifact_store, baselines, ci_status, errors, gating, repos, run_queries, uploads

logger = structlog.get_logger(__name__)


def create_run(input: CreateRunInput, team_id: int) -> tuple[Run, list[dict]]:
    """
    Create a new run with its snapshots.

    Returns the run and list of upload targets for missing artifacts.
    Each upload target has: content_hash, url, fields

    input.baseline_hashes, input.unchanged_count and input.removed_identifiers
    are deprecated and ignored: the backend fetches baselines from GitHub and
    computes everything. The fields are kept for backward compat with older
    CLI versions.

    input.is_partial tags the run as a subset; the classifier then leaves baseline
    identifiers we didn't touch alone instead of marking them as removed.
    """
    repo = repos.get_repo(input.repo_id, team_id)

    return _create_run_inner(repo, team_id, input)


@transaction.atomic(using=WRITER_DB)
def _create_run_inner(repo: Repo, team_id: int, input: CreateRunInput) -> tuple[Run, list[dict]]:
    # Supersede ALL old runs before inserting the new one. The unique
    # partial index on (repo, branch, run_type) WHERE superseded_by IS NULL
    # requires the slot to be free before the insert. A new CI push always
    # replaces the previous run — approved and clean runs still show up in
    # their respective UI filters via REVIEW_STATE_FILTERS.
    supersede_filter = Run.objects.using(WRITER_DB).filter(
        repo_id=repo.id,
        branch=input.branch,
        run_type=input.run_type,
        superseded_by__isnull=True,
    )
    # Collect IDs before mutating, then self-reference to clear the slot
    superseded_ids = list(supersede_filter.values_list("id", flat=True))
    if superseded_ids:
        from django.db.models import F

        Run.objects.using(WRITER_DB).filter(id__in=superseded_ids, team_id=team_id).update(superseded_by=F("id"))

    run = Run.objects.create(
        repo=repo,
        team_id=repo.team_id,
        run_type=input.run_type,
        commit_sha=input.commit_sha,
        branch=input.branch,
        pr_number=input.pr_number,
        purpose=input.purpose,
        total_snapshots=len(input.snapshots),
        metadata=input.metadata or {},
        is_partial=input.is_partial,
    )

    # Fix up the sentinel pointers to reference the actual new run
    if superseded_ids:
        Run.objects.using(WRITER_DB).filter(id__in=superseded_ids, team_id=team_id).update(superseded_by=run)

    snapshots = [
        {
            "identifier": s.identifier,
            "content_hash": s.content_hash,
            "width": s.width,
            "height": s.height,
            "metadata": dict(s.metadata) if s.metadata else {},
        }
        for s in input.snapshots
    ]
    _added, uploads = _register_snapshots(run, repo, snapshots)
    _update_run_counts(run, using=WRITER_DB)

    transaction.on_commit(
        lambda: ci_status._post_commit_status(run, repo, "pending", "Visual review in progress"), using=WRITER_DB
    )

    return run, uploads


def _register_snapshots(
    run: Run,
    repo: Repo,
    snapshots: list[dict],
) -> tuple[int, list[dict]]:
    """Store snapshot rows and generate upload URLs.

    Stores raw identifier + hash pairs. Classification (CHANGED/NEW/UNCHANGED/REMOVED)
    happens at complete_run time when the baseline is fetched once.
    Idempotent per (run, identifier) via unique constraint — safe for retries.
    """
    repo_id = repo.id
    all_hashes: set[str] = set()
    added_count = 0

    for snap in snapshots:
        identifier = snap["identifier"]
        current_hash = snap["content_hash"]
        all_hashes.add(current_hash)

        _snapshot, created = RunSnapshot.objects.get_or_create(
            run=run,
            team_id=repo.team_id,
            identifier=identifier,
            defaults={
                "current_hash": current_hash,
                "baseline_hash": "",
                "result": SnapshotResult.NEW,  # Provisional — reclassified at complete time
                "current_width": snap.get("width"),
                "current_height": snap.get("height"),
                "metadata": snap.get("metadata") or {},
            },
        )
        if created:
            added_count += 1

    # Generate upload URLs for missing artifacts
    missing_hashes = artifact_store.find_missing_hashes(repo_id, list(all_hashes))
    storage = ArtifactStorage(str(repo_id))

    uploads = []
    for content_hash in missing_hashes:
        upload_data = storage.get_presigned_upload_url(content_hash)
        if upload_data:
            uploads.append(
                {
                    "content_hash": content_hash,
                    "url": upload_data["url"],
                    "fields": upload_data["fields"],
                }
            )

    return added_count, uploads


def _update_run_counts(run: Run, using: str | None = None) -> None:
    """Recalculate result counts from RunSnapshot rows."""
    db_alias = using or WRITER_DB
    counts = RunSnapshot.objects.using(db_alias).filter(run_id=run.id).values("result").annotate(n=Count("id"))
    by_result = {row["result"]: row["n"] for row in counts}

    run.changed_count = by_result.get(SnapshotResult.CHANGED, 0)
    run.new_count = by_result.get(SnapshotResult.NEW, 0)
    run.removed_count = by_result.get(SnapshotResult.REMOVED, 0)
    run.save(using=db_alias, update_fields=["changed_count", "new_count", "removed_count"])


def add_snapshots_to_run(
    run_id: UUID,
    team_id: int,
    snapshots: list[dict],
    baseline_hashes: dict[str, str] | None = None,
    unchanged_count: int = 0,
) -> tuple[int, list[dict]]:
    """Add a batch of snapshots to an existing run (shard-based flow).

    Returns (added_count, upload_targets). Idempotent — safe for retries.
    baseline_hashes is deprecated — backend fetches from GitHub.
    """
    run = run_queries.get_run(run_id, team_id=team_id)

    if run.status != RunStatus.PENDING:
        raise ValueError(f"Can only add snapshots to pending runs (current status: {run.status})")

    repo = run.repo

    return _add_snapshots_inner(run, run_id, team_id, repo, snapshots)


@transaction.atomic(using=WRITER_DB)
def _add_snapshots_inner(run, run_id, team_id, repo, snapshots):
    added, uploads = _register_snapshots(run, repo, snapshots)

    # Atomically increment total (safe for concurrent shards)
    Run.objects.using(WRITER_DB).filter(id=run_id, team_id=team_id).update(total_snapshots=F("total_snapshots") + added)
    _update_run_counts(run, using=WRITER_DB)

    return added, uploads


def mark_run_processing(run_id: UUID) -> Run:
    run = run_queries.get_run(run_id)
    run.status = RunStatus.PROCESSING
    run.save(update_fields=["status"])
    return run


def complete_run(run_id: UUID) -> Run:
    """
    Complete a run: detect removals, classify snapshots, hand off to the diff task.

    1. Fetches baseline from GitHub, diffs against RunSnapshot rows to find removed
    2. Creates REMOVED RunSnapshot rows
    3. Classifies snapshots and updates run counts
    4. Either verifies uploads + finishes synchronously (no-change fast path) or
       enqueues process_run_diffs which verifies + diffs + finishes

    Idempotent: returns immediately if already processing or completed.
    """
    run = run_queries.get_run(run_id)
    if run.status in (RunStatus.COMPLETED, RunStatus.PROCESSING):
        return run

    # Transition to PROCESSING early so late add_snapshots calls are rejected.
    # Atomic update with condition prevents race with concurrent complete calls.
    updated = Run.objects.filter(id=run_id, team_id=run.repo.team_id, status=RunStatus.PENDING).update(
        status=RunStatus.PROCESSING
    )
    if not updated:
        # Another complete_run got here first, or status changed
        return run_queries.get_run(run_id)

    repo = run.repo

    # Fetch baseline merged with merge-base to heal rebase-induced drift.
    # Branch baseline tracks approvals; merge-base fills entries lost when
    # git rebase replays a full-file bot commit destructively.
    # Pass commit_sha so default-branch runs fetch the baseline at the
    # exact commit being tested, avoiding races with concurrent pushes.
    try:
        baseline, healed_count = baselines._resolve_baselines_with_merge_base(
            repo, run.run_type, run.branch, commit_sha=run.commit_sha
        )
    except GitHubRateLimitError:
        # Roll back to PENDING so the caller can retry after the limit resets
        Run.objects.filter(id=run_id).update(status=RunStatus.PENDING)
        raise
    if healed_count:
        run.metadata["baseline_healed_from_merge_base"] = healed_count
        run.save(using=WRITER_DB, update_fields=["metadata"])

    # Pre-load tolerated hashes scoped to this run's identifiers and baseline hashes
    run_identifiers = set(run.snapshots.using(WRITER_DB).values_list("identifier", flat=True))
    baseline_hashes_in_use = set(baseline.values())
    tolerated_lookup: dict[tuple[str, str, str], ToleratedHash] = {}
    if run_identifiers and baseline_hashes_in_use:
        now = timezone.now()
        for t in ToleratedHash.objects.filter(
            repo=repo,
            identifier__in=run_identifiers,
            baseline_hash__in=baseline_hashes_in_use,
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)):
            tolerated_lookup[(t.identifier, t.baseline_hash, t.alternate_hash)] = t

    # is_partial is client-supplied and only suppresses removed-baseline
    # detection. Never honor it on the default branch (authoritative full
    # baseline), so a token can't hide deleted snapshots from the gate. Persist
    # the correction so every downstream reader (status posting, UI) sees the
    # effective value rather than the raw client claim.
    #
    # On PR branches honoring the client is deliberate, but a partial run must
    # never satisfy the gating status context: _post_commit_status routes it to
    # a separate non-gating "(partial)" context (see there). Branch protection
    # keys off context + state, not the human-facing description, so a separate
    # context is what actually keeps a one-flag subset run from turning the gate
    # green — the description annotation alone does not.
    if run.is_partial and baselines._run_is_on_default_branch(repo, run.branch):
        logger.warning(
            "visual_review.is_partial_ignored_on_default_branch",
            run_id=str(run.id),
            branch=run.branch,
        )
        run.is_partial = False
        run.save(using=WRITER_DB, update_fields=["is_partial"])

    classifier = SnapshotClassifier(run, baseline, tolerated_lookup, is_partial=run.is_partial)
    classifier.classify()

    # Update total and counts from actual RunSnapshot rows
    run.total_snapshots = run.snapshots.using(WRITER_DB).count()
    run.save(using=WRITER_DB, update_fields=["total_snapshots"])
    _update_run_counts(run, using=WRITER_DB)

    run = run_queries.get_run(run_id)

    # No-changes fast path: verify any pending uploads synchronously, then
    # finish. Skipping verify here would silently drop uploads whenever an
    # Artifact row is missing for a hash that the baseline still points at
    # (e.g. DB cleanup removed the row but the GitHub-side baseline file
    # wasn't updated). The CLI re-uploads via find_missing_hashes, the
    # snapshot classifies as UNCHANGED, and the bytes never get checked or
    # recorded — leaving every future run requesting the same upload while
    # CI posts green.
    if run.changed_count == 0 and run.new_count == 0:
        from ..tasks.tasks import emit_run_processing_metrics  # noqa: PLC0415 — avoids the logic/tasks circular import

        try:
            uploads.verify_uploads_and_create_artifacts(run_id)
        except errors.HashIntegrityError as e:
            logger.warning("visual_review.hash_integrity_failed", run_id=str(run_id), error=str(e))
            finish_processing(run_id, error_message=str(e))
            emit_run_processing_metrics.delay(run.team_id, str(run_id), "hash_integrity_failed", 0)
            return run_queries.get_run(run_id)
        finish_processing(run_id)
        emit_run_processing_metrics.delay(run.team_id, str(run_id), "completed", 0)
        return run_queries.get_run(run_id)

    mark_run_processing(run_id)
    from ..tasks.tasks import process_run_diffs

    process_run_diffs.delay(run.team_id, str(run_id))
    return run_queries.get_run(run_id)


def finish_processing(run_id: UUID, error_message: str = "") -> Run:
    run = run_queries.get_run_with_snapshots(run_id)

    run.status = RunStatus.FAILED if error_message else RunStatus.COMPLETED
    run.error_message = error_message
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "error_message", "completed_at"])

    gating._update_counts_and_post_status(run)

    return run


def capture_run_processing_metrics(run_id: UUID, *, outcome: str, diffed_count: int) -> None:
    """Emit a product-analytics event for a finished diff-processing run.

    Records run volume and how many snapshots actually needed a pixel
    comparison (changed / new / removed vs. unchanged / tolerated). That's the
    signal to tell a snapshot-determinism regression — where the changed rate
    climbs because images stop being byte-stable, so the content-hash dedup and
    tolerance cache stop absorbing work — apart from plain run-volume growth.
    Where the time goes is captured separately as OTel spans in the task.

    Best-effort: instrumentation must never fail or slow the task, so every
    error is swallowed — including so it can't mask a real exception when
    called from the task's ``finally``.
    """
    try:
        try:
            run = Run.objects.using(WRITER_DB).select_related("repo").get(id=run_id)
        except Run.DoesNotExist:
            return

        properties = {
            "run_id": str(run.id),
            "run_type": run.run_type,
            "outcome": outcome,
            "status": run.status,
            "repo": run.repo.repo_full_name,
            "branch": run.branch,
            "pr_number": run.pr_number,
            "team_id": run.team_id,
            "is_partial": run.is_partial,
            "total_snapshots": run.total_snapshots,
            "changed_count": run.changed_count,
            "new_count": run.new_count,
            "removed_count": run.removed_count,
            "tolerated_match_count": run.tolerated_match_count,
            "diffed_count": diffed_count,
            "reviewable_count": run.changed_count + run.new_count + run.removed_count,
        }

        with ph_scoped_capture() as capture_ph_event:
            capture_ph_event(
                distinct_id=run.repo.repo_full_name or str(run.repo_id),
                event="vr_run_processed",
                properties=properties,
                uuid=run.id,
            )
    except Exception:
        logger.warning("visual_review.metrics_capture_failed", run_id=str(run_id), exc_info=True)


@transaction.atomic(using=WRITER_DB)
def recompute_run(run_id: UUID, team_id: int | None = None) -> dict:
    """Re-evaluate quarantine and counts, update commit status, and optionally rerun the CI job.

    Returns a dict with counts_changed, ci_rerun_triggered, and ci_rerun_error.
    """
    run = run_queries._get_run_for_update(run_id, team_id=team_id)

    if run.status != RunStatus.COMPLETED:
        raise ValueError(f"Can only recompute completed runs (current status: {run.status})")

    if run.approved:
        raise ValueError("Run is already approved")

    old_counts = (run.changed_count, run.new_count, run.removed_count)
    unresolved = gating._update_counts_and_post_status(run)
    new_counts = (run.changed_count, run.new_count, run.removed_count)
    counts_changed = old_counts != new_counts

    ci_rerun_triggered = False
    ci_rerun_error: str | None = None

    check_run_id = (run.metadata or {}).get("github_check_run_id")

    if not check_run_id:
        ci_rerun_error = "CI job ID not available (set JOB_CHECK_RUN_ID=${{ job.check_run_id }} in workflow)"
    else:
        # Stored as a string, but coerce defensively — `_rerun_github_job` calls `.isdigit()`.
        ci_rerun_triggered, ci_rerun_error = ci_status._rerun_github_job(run, str(check_run_id))

    return {
        "counts_changed": counts_changed,
        "unresolved": unresolved,
        "ci_rerun_triggered": ci_rerun_triggered,
        "ci_rerun_error": ci_rerun_error,
    }
