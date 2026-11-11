"""Lift a quarantine once the pull request that fixes the story merges.

A reviewer names the picture a pull request renders for a quarantined story. A completed
default-branch run that contains the merge, and renders that picture against a matching
baseline entry, lifts the quarantine. Requesting a lift never approves a picture, and approving
a picture never requests a lift.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from ..db import WRITER_DB
from ..facade.enums import ActorType, QuarantineLiftState, ReviewState, RunPurpose, RunStatus, SnapshotResult
from ..models import QuarantinedIdentifier, QuarantineLiftRequest, Run, RunSnapshot
from . import errors, github_api, run_queries

logger = structlog.get_logger(__name__)

DETAIL_WAITING_FOR_MERGE = "Waiting for the pull request to merge"
DETAIL_WAITING_FOR_RUN = "Waiting for a default branch run that contains the merge"
DETAIL_PULL_REQUEST_UNREADABLE = "Could not read the pull request from GitHub"
DETAIL_CLOSED_WITHOUT_MERGE = "The pull request closed without merging"
DETAIL_QUARANTINE_ENDED = "The quarantine already ended"
DETAIL_NOT_RENDERED = "The default branch run did not render the story"
DETAIL_DIFFERENT_PICTURE = "The default branch rendered a different picture"
DETAIL_BASELINE_MISMATCH = "The baseline entry does not match the requested picture"
DETAIL_APPLIED = "Lifted after the pull request merged"
DETAIL_LIFTED_BY_OTHER_REQUEST = "Another pull request lifted the quarantine"
DETAIL_CANCELLED = "Cancelled by a reviewer"


def _is_active(quarantine: QuarantinedIdentifier, now: datetime) -> bool:
    return quarantine.expires_at is None or quarantine.expires_at > now


def _active_quarantine(run: Run, identifier: str, now: datetime) -> QuarantinedIdentifier | None:
    return (
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=run.repo_id, run_type=run.run_type, identifier=identifier, team_id=run.team_id)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .order_by("-created_at")
        .first()
    )


def _expected_hash(snapshot: RunSnapshot) -> str:
    """The picture the default branch must render for the lift to apply.

    An unchanged snapshot counts only when it rendered its baseline byte for byte: `unchanged`
    also covers tolerated variants and diffs under the threshold, which are other pictures. A
    changed or new picture counts only once a reviewer approved it, because finalize commits the
    approved hash as the baseline entry.
    """
    if snapshot.result == SnapshotResult.UNCHANGED and snapshot.baseline_hash:
        if snapshot.current_hash != snapshot.baseline_hash:
            raise ValueError(
                "This run rendered a tolerated variant, not the baseline itself. "
                "Request the lift from a run that renders the baseline exactly."
            )
        return snapshot.baseline_hash
    if (
        snapshot.result in (SnapshotResult.CHANGED, SnapshotResult.NEW)
        and snapshot.review_state == ReviewState.APPROVED
        and snapshot.approved_hash
    ):
        return snapshot.approved_hash
    raise ValueError(
        "Approve the new picture first. A lift needs a picture the baseline will hold, "
        "and requesting a lift never approves one."
    )


def request_lift_on_merge(
    run_id: UUID, identifier: str, team_id: int, user_id: int, source: ActorType = ActorType.HUMAN
) -> QuarantineLiftRequest:
    run = run_queries.get_run(run_id, team_id=team_id)
    if run.status != RunStatus.COMPLETED:
        raise ValueError("The run has not finished processing yet.")
    if run.purpose != RunPurpose.REVIEW or run.pr_number is None:
        raise ValueError("Only a pull request run can request a lift, because the lift waits for the merge.")
    if run_queries.is_run_stale(run):
        raise errors.StaleRunError(
            "This run has been superseded by a newer run. Request the lift from the latest run instead."
        )

    snapshot = (
        RunSnapshot.objects.using(WRITER_DB).filter(identifier=identifier, run_id=run.id, team_id=team_id).first()
    )
    if snapshot is None:
        raise errors.RunNotFoundError(f"Snapshot {identifier} not found in run {run_id}")
    # Not `snapshot.is_quarantined`: that flag is set when the run is processed, and a reviewer
    # can quarantine the story later from the run scene. The live quarantine row decides.
    quarantine = _active_quarantine(run, snapshot.identifier, timezone.now())
    if quarantine is None:
        raise ValueError("This snapshot has no active quarantine to lift.")
    expected_hash = _expected_hash(snapshot)

    with transaction.atomic(using=WRITER_DB):
        # Lock the quarantine row before reading the pending request, in the same order as `_apply`.
        # Two concurrent requests for one PR then run one after the other, and the second updates
        # the row the first created instead of breaking the one-pending-request constraint.
        locked_quarantine = (
            QuarantinedIdentifier.objects.using(WRITER_DB)
            .select_for_update()
            .filter(id=quarantine.id, team_id=team_id)
            .first()
        )
        # A lift or a re-quarantine can land between the lookup above and the lock.
        if locked_quarantine is None or not _is_active(locked_quarantine, timezone.now()):
            raise ValueError("This snapshot has no active quarantine to lift.")
        request = (
            QuarantineLiftRequest.objects.using(WRITER_DB)
            .select_for_update()
            .filter(
                team_id=team_id,
                quarantine=quarantine,
                pr_number=run.pr_number,
                state=QuarantineLiftState.PENDING,
            )
            .first()
        )
        if request is None:
            request = QuarantineLiftRequest.objects.using(WRITER_DB).create(
                team_id=team_id,
                repo_id=run.repo_id,
                quarantine=quarantine,
                identifier=snapshot.identifier,
                run_type=run.run_type,
                pr_number=run.pr_number,
                expected_hash=expected_hash,
                source_run_id=run.id,
                requested_by_id=user_id,
                source=source,
                detail=DETAIL_WAITING_FOR_MERGE,
            )
        else:
            request.expected_hash = expected_hash
            request.source_run_id = run.id
            request.requested_by_id = user_id
            request.source = source
            request.detail = DETAIL_WAITING_FOR_MERGE
            request.save(
                using=WRITER_DB,
                update_fields=["expected_hash", "source_run_id", "requested_by_id", "source", "detail", "updated_at"],
            )

    logger.info(
        "visual_review.quarantine_lift_requested",
        request_id=str(request.id),
        quarantine_id=str(quarantine.id),
        pr_number=run.pr_number,
        team_id=team_id,
    )
    return request


def cancel_lift_request(request_id: UUID, team_id: int, run_id: UUID) -> None:
    """Withdraw a pending request that belongs to the run's pull request."""
    run = run_queries.get_run(run_id, team_id=team_id)
    if run.pr_number is None:
        raise errors.QuarantineLiftRequestNotFoundError("A run without a pull request has no lift requests")
    cancelled = (
        QuarantineLiftRequest.objects.using(WRITER_DB)
        .filter(
            id=request_id,
            team_id=team_id,
            repo_id=run.repo_id,
            pr_number=run.pr_number,
            state=QuarantineLiftState.PENDING,
        )
        .update(
            state=QuarantineLiftState.CANCELLED,
            detail=DETAIL_CANCELLED,
            resolved_at=timezone.now(),
            updated_at=timezone.now(),
        )
    )
    if not cancelled:
        raise errors.QuarantineLiftRequestNotFoundError(f"No pending lift request {request_id} for this run")


def list_lift_requests_for_pr(repo_id: UUID, team_id: int, pr_number: int) -> list[QuarantineLiftRequest]:
    return list(
        QuarantineLiftRequest.objects.using(WRITER_DB)
        .filter(repo_id=repo_id, team_id=team_id, pr_number=pr_number)
        .order_by("-created_at")
    )


def has_pending_lift_requests(repo_id: UUID, team_id: int, run_type: str) -> bool:
    return (
        QuarantineLiftRequest.objects.using(WRITER_DB)
        .filter(repo_id=repo_id, team_id=team_id, run_type=run_type, state=QuarantineLiftState.PENDING)
        .exists()
    )


def _set_detail(request: QuarantineLiftRequest, detail: str) -> None:
    if request.detail == detail:
        return
    # Filtered on the state so a reviewer's cancel that lands meanwhile stays cancelled.
    QuarantineLiftRequest.objects.using(WRITER_DB).filter(
        id=request.id, team_id=request.team_id, state=QuarantineLiftState.PENDING
    ).update(detail=detail[:255], updated_at=timezone.now())


def _resolve(request: QuarantineLiftRequest, state: QuarantineLiftState, detail: str) -> None:
    now = timezone.now()
    QuarantineLiftRequest.objects.using(WRITER_DB).filter(
        id=request.id, team_id=request.team_id, state=QuarantineLiftState.PENDING
    ).update(state=state, detail=detail[:255], resolved_at=now, updated_at=now)
    logger.info("visual_review.quarantine_lift_resolved", request_id=str(request.id), state=state, detail=detail)


def _apply(request: QuarantineLiftRequest, run: Run, merge_commit_sha: str) -> bool:
    """Lift the quarantine event the request names. False when it already ended."""
    with transaction.atomic(using=WRITER_DB):
        quarantine = (
            QuarantinedIdentifier.objects.using(WRITER_DB)
            .select_for_update()
            .filter(id=request.quarantine_id, team_id=request.team_id)
            .first()
        )
        locked_request = (
            QuarantineLiftRequest.objects.using(WRITER_DB)
            .select_for_update()
            .filter(
                id=request.id,
                team_id=request.team_id,
                state=QuarantineLiftState.PENDING,
                # A reviewer can change the picture after reconcile verified it. Lift only for the verified one.
                expected_hash=request.expected_hash,
            )
            .first()
        )
        if locked_request is None:
            return False
        now = timezone.now()
        if quarantine is None or not _is_active(quarantine, now):
            _resolve(locked_request, QuarantineLiftState.SUPERSEDED, DETAIL_QUARANTINE_ENDED)
            return False

        # The verifying run's commit, not the merge commit: it is where the baseline entry was
        # proven to hold the picture. A branch that forked before it keeps the quarantine.
        quarantine.expires_at = now
        quarantine.lifted_at_sha = run.commit_sha
        quarantine.save(using=WRITER_DB, update_fields=["expires_at", "lifted_at_sha", "updated_at"])

        locked_request.state = QuarantineLiftState.APPLIED
        locked_request.detail = DETAIL_APPLIED
        locked_request.merge_commit_sha = merge_commit_sha
        locked_request.applied_run_id = run.id
        locked_request.lifted_at_sha = run.commit_sha
        locked_request.resolved_at = now
        locked_request.save(
            using=WRITER_DB,
            update_fields=[
                "state",
                "detail",
                "merge_commit_sha",
                "applied_run_id",
                "lifted_at_sha",
                "resolved_at",
                "updated_at",
            ],
        )
        QuarantineLiftRequest.objects.using(WRITER_DB).filter(
            quarantine_id=quarantine.id, team_id=request.team_id, state=QuarantineLiftState.PENDING
        ).exclude(id=request.id).update(
            state=QuarantineLiftState.SUPERSEDED,
            detail=DETAIL_LIFTED_BY_OTHER_REQUEST,
            resolved_at=now,
            updated_at=now,
        )

    logger.info(
        "visual_review.quarantine_lift_applied",
        request_id=str(request.id),
        quarantine_id=str(request.quarantine_id),
        run_id=str(run.id),
        lifted_at_sha=run.commit_sha,
    )
    return True


class _LiftReconciler:
    """Checks the pending requests of one repo and run type against one default-branch run."""

    def __init__(self, run: Run) -> None:
        self.run = run
        self.pull_requests: dict[int, github_api.PullRequestState | None] = {}
        self.lifted_quarantine_ids: set[UUID] = set()

    def _pull_request(self, pr_number: int) -> github_api.PullRequestState | None:
        if pr_number not in self.pull_requests:
            self.pull_requests[pr_number] = github_api.pull_request_state(self.run.repo, pr_number)
        return self.pull_requests[pr_number]

    def reconcile(self, request: QuarantineLiftRequest, snapshot: RunSnapshot | None) -> None:
        run = self.run
        if request.quarantine_id in self.lifted_quarantine_ids:
            # `_apply` already marked this request superseded in the database.
            return
        if not _is_active(request.quarantine, timezone.now()):
            _resolve(request, QuarantineLiftState.SUPERSEDED, DETAIL_QUARANTINE_ENDED)
            return

        pull_request = self._pull_request(request.pr_number)
        if pull_request is None:
            _set_detail(request, DETAIL_PULL_REQUEST_UNREADABLE)
            return
        if not pull_request.merged:
            if pull_request.state == "closed":
                _resolve(request, QuarantineLiftState.CANCELLED, DETAIL_CLOSED_WITHOUT_MERGE)
            else:
                _set_detail(request, DETAIL_WAITING_FOR_MERGE)
            return
        if pull_request.base_ref != run.branch:
            _resolve(
                request,
                QuarantineLiftState.CANCELLED,
                f"The pull request merged into {pull_request.base_ref}, not {run.branch}",
            )
            return
        # A run that does not contain the merge predates it, or GitHub cannot tell. A later run retries.
        merge_commit_sha = pull_request.merge_commit_sha
        if not merge_commit_sha or not github_api.commit_contains(run.repo, merge_commit_sha, run.commit_sha):
            _set_detail(request, DETAIL_WAITING_FOR_RUN)
            return

        if snapshot is None:
            _set_detail(request, DETAIL_NOT_RENDERED)
            return
        # Exact on purpose: a stale or missing baseline entry never gets a lift, and a later run retries.
        if snapshot.current_hash != request.expected_hash:
            _set_detail(request, DETAIL_DIFFERENT_PICTURE)
            return
        if snapshot.baseline_hash != request.expected_hash:
            _set_detail(request, DETAIL_BASELINE_MISMATCH)
            return

        if _apply(request, run, merge_commit_sha):
            self.lifted_quarantine_ids.add(request.quarantine_id)


def reconcile_lift_requests(run_id: UUID) -> None:
    """Apply the pending lift requests that a completed default-branch run proves ready."""
    run = Run.objects.using(WRITER_DB).select_related("repo").get(id=run_id)
    if run.status != RunStatus.COMPLETED or run.is_partial or run.pr_number is not None:
        return

    if not has_pending_lift_requests(run.repo_id, run.team_id, run.run_type):
        return
    if github_api.default_branch_name(run.repo) != run.branch:
        return

    pending = list(
        QuarantineLiftRequest.objects.using(WRITER_DB)
        .filter(
            repo_id=run.repo_id,
            team_id=run.team_id,
            run_type=run.run_type,
            state=QuarantineLiftState.PENDING,
        )
        .select_related("quarantine")
        .order_by("created_at")
    )
    if not pending:
        return

    snapshots_by_identifier = {
        snapshot.identifier: snapshot
        for snapshot in RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=run.id, team_id=run.team_id, identifier__in={request.identifier for request in pending})
        .only("id", "identifier", "current_hash", "baseline_hash")
    }
    reconciler = _LiftReconciler(run)
    for request in pending:
        reconciler.reconcile(request, snapshots_by_identifier.get(request.identifier))
