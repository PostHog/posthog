"""
Business logic for visual_review.

ORM queries, validation, calculations, business rules.
Called by api/api.py facade. Do not call from outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import (
    connections,
    models as db_models,
    transaction,
)
from django.db.models import Count, F, Q
from django.utils import timezone

import structlog

if TYPE_CHECKING:
    from posthog.models.integration import GitHubIntegration

from posthog.models.integration import GitHubRateLimitError

from .classifier import SnapshotClassifier
from .db import READER_DB, WRITER_DB
from .facade.enums import ReviewDecision, ReviewState, RunPurpose, RunStatus, SnapshotResult, ToleratedReason
from .models import Artifact, QuarantinedIdentifier, Repo, Run, RunSnapshot, ToleratedHash
from .signing import sign_snapshot_hash, verify_signed_hash
from .storage import ArtifactStorage

logger = structlog.get_logger(__name__)


class RepoNotFoundError(Exception):
    pass


class RunNotFoundError(Exception):
    pass


class ArtifactNotFoundError(Exception):
    pass


class GitHubIntegrationNotFoundError(Exception):
    """Team does not have a GitHub integration configured."""

    pass


class GitHubCommitError(Exception):
    """Failed to commit to GitHub."""

    pass


class PRSHAMismatchError(Exception):
    """PR has new commits since this run was created."""

    pass


class HashIntegrityError(Exception):
    """Uploaded image bytes do not match the claimed content hash."""

    pass


class StaleRunError(Exception):
    """Approval blocked because a newer run exists for this PR."""

    pass


class BaselineFilePathNotConfiguredError(Exception):
    """Repo does not have a baseline file path configured for this run type."""

    pass


# --- Repo Operations ---


def get_repo(repo_id: UUID, team_id: int) -> Repo:
    try:
        return Repo.objects.get(id=repo_id, team_id=team_id)
    except Repo.DoesNotExist as e:
        raise RepoNotFoundError(f"Repo {repo_id} not found") from e


def list_repos_for_team(team_id: int) -> list[Repo]:
    return list(Repo.objects.filter(team_id=team_id).order_by("-created_at"))


def create_repo(team_id: int, repo_external_id: int, repo_full_name: str) -> Repo:
    return Repo.objects.create(
        team_id=team_id,
        repo_external_id=repo_external_id,
        repo_full_name=repo_full_name,
    )


def update_repo(
    repo_id: UUID,
    team_id: int,
    baseline_file_paths: dict[str, str] | None = None,
    enable_pr_comments: bool | None = None,
) -> Repo:
    repo = get_repo(repo_id, team_id)
    if baseline_file_paths is not None:
        repo.baseline_file_paths = baseline_file_paths
    if enable_pr_comments is not None:
        repo.enable_pr_comments = enable_pr_comments
    repo.save()
    return repo


# --- Artifact Operations ---


def get_artifact(repo_id: UUID, content_hash: str) -> Artifact | None:
    return Artifact.objects.filter(repo_id=repo_id, content_hash=content_hash).first()


def get_or_create_artifact(
    repo_id: UUID,
    content_hash: str,
    storage_path: str,
    width: int | None = None,
    height: int | None = None,
    size_bytes: int | None = None,
    team_id: int | None = None,
) -> tuple[Artifact, bool]:
    # Resolve team_id from the repo when not provided by the caller.
    if team_id is None:
        # nosemgrep: rules.idor-lookup-without-team — resolving team_id from repo
        team_id = Repo.objects.values_list("team_id", flat=True).get(id=repo_id)

    return Artifact.objects.get_or_create(
        repo_id=repo_id,
        content_hash=content_hash,
        team_id=team_id,
        defaults={
            "storage_path": storage_path,
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
        },
    )


def find_missing_hashes(repo_id: UUID, hashes: list[str]) -> list[str]:
    """Return hashes that don't exist as artifacts in the repo."""
    existing = set(
        Artifact.objects.filter(repo_id=repo_id, content_hash__in=hashes).values_list("content_hash", flat=True)
    )
    return [h for h in hashes if h not in existing]


def get_presigned_upload_url(repo_id: UUID, content_hash: str) -> dict | None:
    storage = ArtifactStorage(str(repo_id))
    return storage.get_presigned_upload_url(content_hash)


def get_presigned_download_url(repo_id: UUID, content_hash: str) -> str | None:
    storage = ArtifactStorage(str(repo_id))
    return storage.get_presigned_download_url(content_hash)


def read_artifact_bytes(repo_id: UUID, content_hash: str) -> bytes | None:
    """Read artifact content from storage."""
    storage = ArtifactStorage(str(repo_id))
    return storage.read(content_hash)


def write_artifact_bytes(
    repo_id: UUID,
    content_hash: str,
    content: bytes,
    width: int | None = None,
    height: int | None = None,
    team_id: int | None = None,
) -> Artifact:
    """
    Write artifact content to storage and create DB record.
    Used for server-generated artifacts like diff images.
    """
    storage = ArtifactStorage(str(repo_id))
    storage_path = storage.write(content_hash, content)

    # Resolve team_id from the repo when not provided by the caller.
    if team_id is None:
        # nosemgrep: rules.idor-lookup-without-team — resolving team_id from repo
        team_id = Repo.objects.values_list("team_id", flat=True).get(id=repo_id)

    artifact, _ = Artifact.objects.get_or_create(
        repo_id=repo_id,
        content_hash=content_hash,
        team_id=team_id,
        defaults={
            "storage_path": storage_path,
            "width": width,
            "height": height,
            "size_bytes": len(content),
        },
    )
    return artifact


# --- Run Operations ---


def is_run_stale(run: Run) -> bool:
    return run.superseded_by_id is not None


_HAS_CHANGES = Q(changed_count__gt=0) | Q(new_count__gt=0) | Q(removed_count__gt=0)
_CURRENT = Q(superseded_by__isnull=True)

_ON_PR = Q(pr_number__isnull=False)

REVIEW_STATE_FILTERS: dict[str, Q] = {
    # Only PR runs need human review — master/branch pushes without a PR are just drift
    "needs_review": Q(status=RunStatus.COMPLETED)
    & _HAS_CHANGES
    & Q(approved=False)
    & _CURRENT
    & _ON_PR
    & Q(purpose=RunPurpose.REVIEW),
    "clean": (Q(status=RunStatus.COMPLETED) & ~_HAS_CHANGES) | Q(approved=True),
    "processing": Q(status=RunStatus.PROCESSING) & _CURRENT,
    "stale": Q(superseded_by__isnull=False) & Q(approved=False) & _HAS_CHANGES,
}


def list_runs_for_team(
    team_id: int, review_state: str | None = None, repo_id: UUID | None = None
) -> db_models.QuerySet[Run]:
    qs = Run.objects.filter(team_id=team_id).select_related("repo").order_by("-created_at")
    if repo_id is not None:
        qs = qs.filter(repo_id=repo_id)
    if review_state and review_state in REVIEW_STATE_FILTERS:
        qs = qs.filter(REVIEW_STATE_FILTERS[review_state])
    return qs


def get_review_state_counts(team_id: int, repo_id: UUID | None = None) -> dict[str, int]:
    qs = Run.objects.filter(team_id=team_id)
    if repo_id is not None:
        qs = qs.filter(repo_id=repo_id)
    return qs.aggregate(
        needs_review=Count("id", filter=REVIEW_STATE_FILTERS["needs_review"]),
        clean=Count("id", filter=REVIEW_STATE_FILTERS["clean"]),
        processing=Count("id", filter=REVIEW_STATE_FILTERS["processing"]),
        stale=Count("id", filter=REVIEW_STATE_FILTERS["stale"]),
    )


def get_run(run_id: UUID, team_id: int | None = None) -> Run:
    try:
        qs = Run.objects.select_related("repo")
        if team_id is not None:
            qs = qs.filter(team_id=team_id)
        return qs.get(id=run_id)
    except Run.DoesNotExist as e:
        raise RunNotFoundError(f"Run {run_id} not found") from e


def _get_run_for_update(run_id: UUID, team_id: int | None = None) -> Run:
    """Get a run with a row-level lock on the writer DB. Must be called inside a transaction."""
    try:
        qs = Run.objects.using(WRITER_DB).select_for_update().select_related("repo")
        if team_id is not None:
            qs = qs.filter(team_id=team_id)
        return qs.get(id=run_id)
    except Run.DoesNotExist as e:
        raise RunNotFoundError(f"Run {run_id} not found") from e


def get_run_with_snapshots(run_id: UUID, team_id: int | None = None) -> Run:
    try:
        qs = Run.objects.prefetch_related(
            "snapshots__current_artifact",
            "snapshots__baseline_artifact",
            "snapshots__diff_artifact",
        )
        if team_id is not None:
            qs = qs.filter(team_id=team_id)
        return qs.get(id=run_id)
    except Run.DoesNotExist as e:
        raise RunNotFoundError(f"Run {run_id} not found") from e


def _verify_baseline_hashes(repo: Repo, raw_hashes: dict[str, str]) -> dict[str, str]:
    """Verify HMAC signatures on baseline hashes from the CLI.

    Accepts a dict of ``{identifier: signed_hash_string}``. Returns a
    dict of ``{identifier: plain_content_hash}`` for entries with valid
    signatures. Invalid or unsigned entries are silently dropped —
    they'll be treated as having no baseline (result = NEW).
    """
    if not raw_hashes:
        return {}

    keys = repo.signing_keys or {}
    if not keys:
        # Legitimate baseline files only exist after the server's approval flow
        # has written one (which populates signing_keys). Reaching here means a
        # .snapshots.yml was committed before any approval — likely hand-crafted.
        # Drop every entry rather than passing it through unsigned. Snapshots
        # will classify NEW, surfacing the situation to a reviewer.
        logger.warning(
            "visual_review.baseline_no_signing_keys",
            repo_id=str(repo.id),
            entry_count=len(raw_hashes),
        )
        return {}

    repo_id = str(repo.id)
    verified: dict[str, str] = {}

    for identifier, signed_hash in raw_hashes.items():
        content_hash = verify_signed_hash(repo_id, identifier, signed_hash, keys)
        if content_hash is not None:
            verified[identifier] = content_hash
        else:
            logger.debug(
                "visual_review.baseline_hash_rejected",
                identifier=identifier,
                reason="invalid_signature",
            )

    return verified


def _resolve_baselines_at_ref(repo: Repo, github: GitHubIntegration, run_type: str, ref: str) -> dict[str, str]:
    """Fetch baseline content hashes from GitHub at a specific ref (branch name or SHA).

    Returns a dict of identifier → content_hash (plain, not signed).
    Returns empty dict when baseline file doesn't exist.
    """
    baseline_paths = repo.baseline_file_paths or {}
    baseline_path = baseline_paths.get(run_type) or baseline_paths.get("default", ".snapshots.yml")

    baselines_signed, _sha = _fetch_baseline_file(github, repo.repo_full_name, baseline_path, ref)

    return _verify_baseline_hashes(
        repo,
        {
            identifier: entry["hash"]
            for identifier, entry in baselines_signed.items()
            if isinstance(entry, dict) and "hash" in entry
        },
    )


def _get_merge_base_sha(github: GitHubIntegration, repo_full_name: str, base: str, head: str) -> str | None:
    """Get the merge-base SHA between two refs via the GitHub Compare API."""
    from urllib.parse import quote

    import requests

    from .github import github_request

    access_token = github.get_access_token()
    try:
        response = github_request(
            "GET",
            f"https://api.github.com/repos/{repo_full_name}/compare/{quote(base, safe='')}...{quote(head, safe='')}",
            access_token=access_token,
            timeout=10,
        )
    except requests.RequestException:
        logger.warning("visual_review.merge_base_fetch_failed", repo=repo_full_name, base=base, head=head)
        return None

    if response.status_code != 200:
        logger.warning(
            "visual_review.merge_base_fetch_failed",
            repo=repo_full_name,
            base=base,
            head=head,
            status=response.status_code,
        )
        return None

    sha = response.json().get("merge_base_commit", {}).get("sha")
    if sha is None:
        logger.warning(
            "visual_review.merge_base_sha_missing_from_response",
            repo=repo_full_name,
            base=base,
            head=head,
        )
    return sha


def _get_default_branch(github: GitHubIntegration, repo_full_name: str) -> str:
    """Get the repo's default branch name via the GitHub API. Falls back to 'master'."""
    import requests

    from .github import github_request

    access_token = github.get_access_token()
    try:
        response = github_request(
            "GET",
            f"https://api.github.com/repos/{repo_full_name}",
            access_token=access_token,
            timeout=10,
        )
    except requests.RequestException:
        logger.warning("visual_review.default_branch_fetch_failed", repo=repo_full_name)
        return "master"

    if response.status_code == 200:
        return response.json().get("default_branch", "master")
    logger.warning(
        "visual_review.default_branch_fetch_failed",
        repo=repo_full_name,
        status=response.status_code,
    )
    return "master"


def _resolve_baselines(repo, run_type: str, branch: str) -> dict[str, str]:
    """Fetch baseline content hashes from GitHub for snapshot comparison.

    Returns a dict of identifier → content_hash (plain, not signed).
    Returns empty dict when no GitHub integration exists or the baseline
    file is missing (first run).
    """
    try:
        github = get_github_integration_for_repo(repo)
        if github.access_token_expired():
            github.refresh_access_token()
    except Exception:
        logger.info("visual_review.no_github_integration", repo_id=str(repo.id))
        return {}

    return _resolve_baselines_at_ref(repo, github, run_type, branch)


def _resolve_baselines_with_merge_base(repo: Repo, run_type: str, branch: str) -> tuple[dict[str, str], int]:
    """Fetch branch baseline merged with merge-base baseline.

    The branch baseline tracks approvals. The merge-base baseline
    fills in entries that were lost during a rebase (the bot commit
    rewrites the full file, and git rebase replays it destructively).

    Branch entries win on conflict so approvals are preserved.
    Identifiers previously approved as REMOVED on this branch are
    tombstoned — healing would otherwise resurrect them from master
    and re-flag them as removed on every subsequent run.
    Returns (merged_baseline, healed_count).
    """
    try:
        github = get_github_integration_for_repo(repo)
        if github.access_token_expired():
            github.refresh_access_token()
    except Exception:
        logger.info("visual_review.no_github_integration", repo_id=str(repo.id))
        return {}, 0

    branch_baseline = _resolve_baselines_at_ref(repo, github, run_type, branch)

    default_branch = _get_default_branch(github, repo.repo_full_name)
    if branch == default_branch:
        return branch_baseline, 0

    merge_base_sha = _get_merge_base_sha(github, repo.repo_full_name, default_branch, branch)
    if not merge_base_sha:
        return branch_baseline, 0

    try:
        merge_base_baseline = _resolve_baselines_at_ref(repo, github, run_type, merge_base_sha)
    except Exception:
        logger.warning(
            "visual_review.merge_base_baseline_fetch_failed",
            repo_id=str(repo.id),
            branch=branch,
            merge_base_sha=merge_base_sha,
        )
        return branch_baseline, 0
    if not merge_base_baseline:
        return branch_baseline, 0

    tombstoned = _tombstoned_identifiers(repo, run_type, branch)
    healable_merge_base = {k: v for k, v in merge_base_baseline.items() if k not in tombstoned}

    healed = set(healable_merge_base) - set(branch_baseline)
    merged = {**healable_merge_base, **branch_baseline}

    if healed or tombstoned:
        logger.info(
            "visual_review.baseline_healed",
            repo_id=str(repo.id),
            branch=branch,
            healed_count=len(healed),
            branch_count=len(branch_baseline),
            merge_base_count=len(merge_base_baseline),
            merged_count=len(merged),
            tombstoned_count=len(tombstoned),
        )

    return merged, len(healed)


def _tombstoned_identifiers(repo: Repo, run_type: str, branch: str) -> set[str]:
    """Identifiers whose latest approved outcome on this branch was REMOVED.

    Healing pulls entries from merge-base back into the baseline when
    they're missing from branch. Without tombstoning, an approved
    removal keeps reappearing: the bot commit drops it from the branch
    file, but the next run's merge-base fetch re-adds it and classifies
    it REMOVED all over again.

    Uses the most recent approved decision per identifier so that a
    later re-addition (approved as NEW/CHANGED) clears the tombstone.
    """
    from django.db.models import OuterRef, Subquery

    latest_approved_run = (
        RunSnapshot.objects.using(WRITER_DB)
        .filter(
            run__repo=repo,
            run__run_type=run_type,
            run__branch=branch,
            run__approved=True,
            review_state=ReviewState.APPROVED,
            identifier=OuterRef("identifier"),
        )
        .order_by("-run__created_at")
        .values("run__created_at")[:1]
    )

    return set(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(
            run__repo=repo,
            run__run_type=run_type,
            run__branch=branch,
            run__approved=True,
            review_state=ReviewState.APPROVED,
            result=SnapshotResult.REMOVED,
        )
        .annotate(latest_approved_at=Subquery(latest_approved_run))
        .filter(run__created_at=F("latest_approved_at"))
        .values_list("identifier", flat=True)
        .distinct()
    )


def create_run(
    repo_id: UUID,
    team_id: int,
    run_type: str,
    commit_sha: str,
    branch: str,
    pr_number: int | None,
    snapshots: list[dict],
    baseline_hashes: dict[str, str] | None = None,
    unchanged_count: int = 0,
    removed_identifiers: list[str] | None = None,
    purpose: str = RunPurpose.REVIEW,
    metadata: dict | None = None,
) -> tuple[Run, list[dict]]:
    """
    Create a new run with its snapshots.

    Returns the run and list of upload targets for missing artifacts.
    Each upload target has: content_hash, url, fields

    baseline_hashes, unchanged_count, removed_identifiers are deprecated —
    the backend fetches baselines from GitHub and computes everything.
    Params kept for backward compat with older CLI versions.
    """
    repo = get_repo(repo_id, team_id)

    return _create_run_inner(
        repo,
        team_id,
        run_type,
        commit_sha,
        branch,
        pr_number,
        snapshots,
        purpose,
        metadata,
    )


@transaction.atomic(using=WRITER_DB)
def _create_run_inner(
    repo,
    team_id,
    run_type,
    commit_sha,
    branch,
    pr_number,
    snapshots,
    purpose,
    metadata,
) -> tuple[Run, list[dict]]:
    # Supersede ALL old runs before inserting the new one. The unique
    # partial index on (repo, branch, run_type) WHERE superseded_by IS NULL
    # requires the slot to be free before the insert. A new CI push always
    # replaces the previous run — approved and clean runs still show up in
    # their respective UI filters via REVIEW_STATE_FILTERS.
    supersede_filter = Run.objects.using(WRITER_DB).filter(
        repo_id=repo.id,
        branch=branch,
        run_type=run_type,
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
        run_type=run_type,
        commit_sha=commit_sha,
        branch=branch,
        pr_number=pr_number,
        purpose=purpose,
        total_snapshots=len(snapshots),
        metadata=metadata or {},
    )

    # Fix up the sentinel pointers to reference the actual new run
    if superseded_ids:
        Run.objects.using(WRITER_DB).filter(id__in=superseded_ids, team_id=team_id).update(superseded_by=run)

    _added, uploads = _register_snapshots(run, repo, snapshots)
    _update_run_counts(run, using=WRITER_DB)

    transaction.on_commit(
        lambda: _post_commit_status(run, repo, "pending", "Visual review in progress"), using=WRITER_DB
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
    missing_hashes = find_missing_hashes(repo_id, list(all_hashes))
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
    run = get_run(run_id, team_id=team_id)

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
    run = get_run(run_id)
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
    run = get_run(run_id)
    if run.status in (RunStatus.COMPLETED, RunStatus.PROCESSING):
        return run

    # Transition to PROCESSING early so late add_snapshots calls are rejected.
    # Atomic update with condition prevents race with concurrent complete calls.
    updated = Run.objects.filter(id=run_id, team_id=run.repo.team_id, status=RunStatus.PENDING).update(
        status=RunStatus.PROCESSING
    )
    if not updated:
        # Another complete_run got here first, or status changed
        return get_run(run_id)

    repo = run.repo

    # Fetch baseline merged with merge-base to heal rebase-induced drift.
    # Branch baseline tracks approvals; merge-base fills entries lost when
    # git rebase replays a full-file bot commit destructively.
    try:
        baseline, healed_count = _resolve_baselines_with_merge_base(repo, run.run_type, run.branch)
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

    classifier = SnapshotClassifier(run, baseline, tolerated_lookup)
    classifier.classify()

    # Update total and counts from actual RunSnapshot rows
    run.total_snapshots = run.snapshots.using(WRITER_DB).count()
    run.save(using=WRITER_DB, update_fields=["total_snapshots"])
    _update_run_counts(run, using=WRITER_DB)

    run = get_run(run_id)

    # No-changes fast path: verify any pending uploads synchronously, then
    # finish. Skipping verify here would silently drop uploads whenever an
    # Artifact row is missing for a hash that the baseline still points at
    # (e.g. DB cleanup removed the row but the GitHub-side baseline file
    # wasn't updated). The CLI re-uploads via find_missing_hashes, the
    # snapshot classifies as UNCHANGED, and the bytes never get checked or
    # recorded — leaving every future run requesting the same upload while
    # CI posts green.
    if run.changed_count == 0 and run.new_count == 0:
        try:
            verify_uploads_and_create_artifacts(run_id)
        except HashIntegrityError as e:
            logger.warning("visual_review.hash_integrity_failed", run_id=str(run_id), error=str(e))
            finish_processing(run_id, error_message=str(e))
            return get_run(run_id)
        finish_processing(run_id)
        return get_run(run_id)

    mark_run_processing(run_id)
    from .tasks.tasks import process_run_diffs

    process_run_diffs.delay(str(run_id))
    return get_run(run_id)


def verify_uploads_and_create_artifacts(run_id: UUID) -> int:
    """
    Verify S3 uploads, check hash integrity, and create Artifact records.

    For each new upload (no existing Artifact), reads the PNG bytes from S3,
    decodes to sRGB RGBA, and computes the BLAKE3 hash. The CLI-claimed hash
    is used only as a lookup key into S3 — once verified, it's discarded and
    the server-computed hash is used everywhere downstream. This ensures the
    CLI cannot (accidentally or maliciously) associate wrong hashes with image
    content.

    Verification runs in two passes so a late failure can't leave a partial
    set of Artifact rows behind: pass 1 reads + hashes all uploads, pass 2
    creates Artifact rows from the verified results.

    Raises HashIntegrityError if any upload fails verification.

    Returns number of artifacts created.
    """
    from .hashing import ImageTooLargeError, hash_image

    run = get_run_with_snapshots(run_id)
    repo_id = run.repo_id
    storage = ArtifactStorage(str(repo_id))

    # Collect all unique hashes we expect, keyed by the CLI-claimed value.
    # The claim is treated as a lookup key only — verification below produces
    # the server-computed hash that becomes authoritative.
    expected_hashes: dict[str, dict] = {}
    for snapshot in run.snapshots.all():
        if snapshot.current_hash and snapshot.current_hash not in expected_hashes:
            expected_hashes[snapshot.current_hash] = {
                "width": snapshot.current_width,
                "height": snapshot.current_height,
            }
        if snapshot.baseline_hash and snapshot.baseline_hash not in expected_hashes:
            expected_hashes[snapshot.baseline_hash] = {
                "width": None,
                "height": None,
            }

    # Pass 1: read + hash all new uploads. Skip existing artifacts. Fail loudly
    # on any hash mismatch, decode error, or missing upload before any Artifact
    # row is written.
    verified: list[tuple[str, bytes, dict]] = []
    for claimed_hash, metadata in expected_hashes.items():
        if get_artifact(repo_id, claimed_hash):
            continue

        png_bytes = storage.read(claimed_hash)
        if png_bytes is None:
            # Race: complete_run fired before the CLI's S3 upload landed, or
            # the upload was never made. Log loudly so we can spot it instead
            # of silently dropping the artifact and forcing the next run to
            # re-upload the same content.
            logger.warning(
                "visual_review.upload_missing_in_s3",
                run_id=str(run_id),
                claimed_hash=claimed_hash,
            )
            continue
        if len(png_bytes) == 0:
            raise HashIntegrityError(f"Upload rejected: empty file for hash {claimed_hash[:16]}…")

        try:
            actual_hash = hash_image(png_bytes)
        except ImageTooLargeError as e:
            logger.exception(
                "visual_review.hash_image_too_large",
                run_id=str(run_id),
                claimed_hash=claimed_hash,
                error=str(e),
            )
            raise HashIntegrityError(f"Upload rejected: {e}") from e
        except Exception as e:
            # Pillow can raise UnidentifiedImageError, DecompressionBombError,
            # OSError, etc. Funnel everything into HashIntegrityError so the
            # task handler routes it through the structured-failure path
            # instead of celery's retry loop.
            logger.exception(
                "visual_review.hash_image_failed",
                run_id=str(run_id),
                claimed_hash=claimed_hash,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise HashIntegrityError(
                f"Upload integrity check failed: could not decode image for hash {claimed_hash[:16]}…"
            ) from e

        if actual_hash != claimed_hash:
            logger.error(
                "visual_review.hash_integrity_failure",
                run_id=str(run_id),
                claimed_hash=claimed_hash,
                actual_hash=actual_hash,
            )
            raise HashIntegrityError(
                f"Upload integrity check failed: claimed {claimed_hash[:16]}… but image hashes to {actual_hash[:16]}…"
            )

        verified.append((actual_hash, png_bytes, metadata))

    # Pass 2: create Artifact rows from verified server-computed hashes only.
    # The claimed hash isn't used past this point.
    created_count = 0
    for actual_hash, png_bytes, metadata in verified:
        storage_path = storage._key(actual_hash)
        artifact, created = get_or_create_artifact(
            repo_id=repo_id,
            content_hash=actual_hash,
            storage_path=storage_path,
            width=metadata.get("width"),
            height=metadata.get("height"),
            size_bytes=len(png_bytes),
            team_id=run.team_id,
        )

        if created:
            created_count += 1
            link_artifact_to_snapshots(repo_id, actual_hash)

    return created_count


def _stamp_quarantine(run: Run) -> None:
    """Evaluate quarantine policy and freeze it on each snapshot."""
    now = timezone.now()
    quarantined_ids = set(
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=run.repo_id, run_type=run.run_type, team_id=run.team_id)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .values_list("identifier", flat=True)
    )

    if not quarantined_ids:
        run.snapshots.using(WRITER_DB).filter(is_quarantined=True).update(is_quarantined=False)
        return

    snapshots = run.snapshots.using(WRITER_DB)
    snapshots.filter(identifier__in=quarantined_ids, is_quarantined=False).update(is_quarantined=True)
    snapshots.filter(is_quarantined=True).exclude(identifier__in=quarantined_ids).update(is_quarantined=False)


def _is_unresolved(s: RunSnapshot) -> bool:
    """A snapshot is unresolved if it represents a change that hasn't been dealt with."""
    if s.result == SnapshotResult.UNCHANGED:
        return False
    if s.is_quarantined:
        return False
    if s.review_state in (ReviewState.TOLERATED, ReviewState.APPROVED):
        return False
    return True


def _update_counts_and_post_status(run: Run) -> int:
    """Re-stamp quarantine, recount snapshots, compute unresolved, and post commit status.

    Counts on the run (changed_count, new_count, removed_count) reflect the raw
    classifier output excluding quarantined snapshots. The unresolved count is
    computed separately for the commit status and CI gate — it further excludes
    tolerated and approved snapshots.

    Returns the unresolved count.
    """
    _stamp_quarantine(run)

    snapshots = list(run.snapshots.using(WRITER_DB).select_related("tolerated_hash_match").all())

    run.changed_count = sum(1 for s in snapshots if s.result == SnapshotResult.CHANGED and not s.is_quarantined)
    run.new_count = sum(1 for s in snapshots if s.result == SnapshotResult.NEW and not s.is_quarantined)
    run.removed_count = sum(1 for s in snapshots if s.result == SnapshotResult.REMOVED and not s.is_quarantined)
    run.tolerated_match_count = sum(
        1
        for s in snapshots
        if s.tolerated_hash_match is not None and s.tolerated_hash_match.reason == ToleratedReason.HUMAN
    )
    run.save(
        update_fields=[
            "changed_count",
            "new_count",
            "removed_count",
            "tolerated_match_count",
        ]
    )

    unresolved = sum(1 for s in snapshots if _is_unresolved(s))

    repo = run.repo
    if run.error_message:
        _post_commit_status(run, repo, "error", f"Visual review failed: {run.error_message[:100]}")
    elif unresolved > 0:
        parts = []
        if run.changed_count:
            parts.append(f"{run.changed_count} changed")
        if run.new_count:
            parts.append(f"{run.new_count} new")
        if run.removed_count:
            parts.append(f"{run.removed_count} removed")
        _post_commit_status(run, repo, "failure", f"Visual changes detected: {', '.join(parts)}")
        _post_review_prompt_comment(run, repo)
    else:
        _post_commit_status(run, repo, "success", "No visual changes")

    return unresolved


def finish_processing(run_id: UUID, error_message: str = "") -> Run:
    run = get_run_with_snapshots(run_id)

    run.status = RunStatus.FAILED if error_message else RunStatus.COMPLETED
    run.error_message = error_message
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "error_message", "completed_at"])

    _update_counts_and_post_status(run)

    return run


@transaction.atomic(using=WRITER_DB)
def recompute_run(run_id: UUID, team_id: int | None = None) -> dict:
    """Re-evaluate quarantine and counts, update commit status, and optionally rerun the CI job.

    Returns a dict with counts_changed, ci_rerun_triggered, and ci_rerun_error.
    """
    run = _get_run_for_update(run_id, team_id=team_id)

    if run.status != RunStatus.COMPLETED:
        raise ValueError(f"Can only recompute completed runs (current status: {run.status})")

    if run.approved:
        raise ValueError("Run is already approved")

    old_counts = (run.changed_count, run.new_count, run.removed_count)
    unresolved = _update_counts_and_post_status(run)
    new_counts = (run.changed_count, run.new_count, run.removed_count)
    counts_changed = old_counts != new_counts

    ci_rerun_triggered = False
    ci_rerun_error: str | None = None

    check_run_id = (run.metadata or {}).get("github_check_run_id")

    if not check_run_id:
        ci_rerun_error = "CI job ID not available (set JOB_CHECK_RUN_ID=${{ job.check_run_id }} in workflow)"
    else:
        ci_rerun_triggered, ci_rerun_error = _rerun_github_job(run, check_run_id)

    return {
        "counts_changed": counts_changed,
        "unresolved": unresolved,
        "ci_rerun_triggered": ci_rerun_triggered,
        "ci_rerun_error": ci_rerun_error,
    }


def _rerun_github_job(run: Run, check_run_id: str) -> tuple[bool, str | None]:
    """Rerun a specific GitHub Actions job by its numeric ID. Returns (success, error_message)."""
    if not check_run_id.isdigit():
        return False, "Invalid check run ID"

    repo = run.repo
    if not repo.repo_full_name:
        return False, "Repo has no GitHub full name configured"

    try:
        response = _github_api_request(
            "POST",
            repo,
            f"actions/jobs/{check_run_id}/rerun",
            timeout=10,
        )
    except Exception:
        return False, "Failed to trigger job rerun"

    if response.status_code == 201:
        logger.info(
            "visual_review.ci_job_rerun_triggered",
            run_id=str(run.id),
            check_run_id=check_run_id,
        )
        return True, None

    return False, f"GitHub API returned {response.status_code} when rerunning job"


def get_github_integration_for_repo(repo: Repo):
    """Get GitHub integration for the repo's team."""
    from posthog.models.integration import GitHubIntegration, Integration

    integration = Integration.objects.filter(team_id=repo.team_id, kind="github").first()

    if not integration:
        raise GitHubIntegrationNotFoundError(f"No GitHub integration found for team {repo.team_id}")

    return GitHubIntegration(integration)


def _resolve_repo_by_id(github, repo_external_id: int) -> str | None:
    """
    Look up the current full_name of a repo by its numeric GitHub ID.

    Used to detect renames: GET /repositories/{id} always returns the
    latest full_name even if the repo was renamed or transferred.
    Returns None if the repo is inaccessible.
    """
    from .github import github_request

    access_token = github.get_access_token()
    response = github_request(
        "GET",
        f"https://api.github.com/repositories/{repo_external_id}",
        access_token=access_token,
        timeout=10,
    )
    if response.status_code == 200:
        return response.json().get("full_name")
    return None


def _github_api_request(
    method: str,
    repo: Repo,
    path: str,
    **kwargs,
):
    """
    Make a GitHub API request, auto-resolving renamed repos on 404.

    If the request returns 404 and the repo has an external ID, looks up
    the current full_name via /repositories/{id}. If it changed, updates
    the stored repo_full_name and retries once.
    """
    from urllib.parse import quote

    from .github import github_request

    # Prevent path traversal — each segment must be safe
    safe_path = "/".join(quote(segment, safe="") for segment in path.split("/"))

    github = get_github_integration_for_repo(repo)
    access_token = github.get_access_token()

    url = f"https://api.github.com/repos/{repo.repo_full_name}/{safe_path}"
    response = github_request(method, url, access_token=access_token, **kwargs)

    if response.status_code == 404 and repo.repo_external_id:
        new_full_name = _resolve_repo_by_id(github, repo.repo_external_id)
        if new_full_name and new_full_name != repo.repo_full_name:
            logger.info(
                "visual_review.repo_renamed",
                repo_id=str(repo.id),
                old_name=repo.repo_full_name,
                new_name=new_full_name,
            )
            repo.repo_full_name = new_full_name
            repo.save(update_fields=["repo_full_name"])

            url = f"https://api.github.com/repos/{new_full_name}/{safe_path}"
            response = github_request(method, url, access_token=access_token, **kwargs)

    return response


def _get_pr_info(github, repo_full_name: str, pr_number: int) -> dict:
    """
    Fetch PR info from GitHub.

    Returns dict with head_ref (branch) and head_sha.
    """
    from .github import github_request

    access_token = github.get_access_token()

    response = github_request(
        "GET",
        f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
        access_token=access_token,
        timeout=10,
    )

    if response.status_code != 200:
        raise GitHubCommitError(f"Failed to fetch PR info: {response.status_code} {response.text}")

    pr_data = response.json()
    return {
        "head_ref": pr_data["head"]["ref"],
        "head_sha": pr_data["head"]["sha"],
    }


def _fetch_baseline_file(
    github, repo_full_name: str, file_path: str, branch: str
) -> tuple[dict[str, dict], str | None]:
    """
    Fetch current baseline file content from GitHub.

    Returns ``(snapshots_dict, file_sha)``. Snapshots dict maps
    identifier to ``{hash: "v1.kid.hash.tag"}`` (the signed format).
    If the file doesn't exist, returns ``({}, None)``.
    """
    import base64

    import yaml

    from .github import github_request

    access_token = github.get_access_token()

    response = github_request(
        "GET",
        f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}",
        access_token=access_token,
        params={"ref": branch},
        timeout=10,
    )

    if response.status_code == 404:
        return {}, None

    if response.status_code != 200:
        raise GitHubCommitError(f"Failed to fetch baseline file: {response.status_code} {response.text}")

    data = response.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    file_sha = data["sha"]

    parsed = yaml.safe_load(content)
    if not parsed or parsed.get("version") != 1:
        return {}, file_sha

    raw_snapshots = parsed.get("snapshots", {})

    normalized: dict[str, dict] = {}
    for identifier, value in raw_snapshots.items():
        if isinstance(value, dict) and "hash" in value:
            normalized[identifier] = value
    return normalized, file_sha


def _build_snapshots_yaml(
    repo: Repo,
    current_baselines: dict[str, dict],
    updates: list[dict],
) -> str:
    """Build updated snapshots.yml with HMAC-signed hashes.

    Each snapshot value is ``{hash: "v1.<kid>.<blake3hex>.<mac>"}``
    where the MAC binds the hash to the repo and identifier.

    *current_baselines* maps identifier to ``{hash: signed_hash_str}``.
    *updates* is a list of ``{identifier, new_hash}`` where ``new_hash``
    is a plain content hash — it gets signed here.
    """
    from django.conf import settings

    import yaml

    kid, secret_hex = repo.get_active_signing_key()
    repo_id = str(repo.id)

    merged = dict(current_baselines)
    for update in updates:
        identifier = update["identifier"]
        content_hash = update["new_hash"]
        signed = sign_snapshot_hash(repo_id, identifier, content_hash, secret_hex, kid)
        merged[identifier] = {"hash": signed}

    sorted_snapshots = dict(sorted(merged.items()))

    data: dict = {
        "version": 1,
        "config": {
            "api": settings.SITE_URL,
            "team": str(repo.team_id),
            "repo": str(repo.id),
        },
        "snapshots": sorted_snapshots,
    }

    return yaml.dump(data, default_flow_style=False, sort_keys=False, indent=4)


def _post_commit_status(
    run: Run,
    repo: Repo,
    state: str,
    description: str,
) -> None:
    """
    Post a commit status to GitHub (best-effort, never raises).

    Uses the GitHub Commit Statuses API:
    POST /repos/{owner}/{repo}/statuses/{sha}

    state: "pending", "success", "failure", "error"
    """
    if not repo.repo_full_name:
        return

    from django.conf import settings

    from .github import github_request

    try:
        github = get_github_integration_for_repo(repo)
        if github.access_token_expired():
            github.refresh_access_token()
    except Exception:
        logger.debug("visual_review.status_check_skipped", run_id=str(run.id), reason="no_github_integration")
        return

    access_token = github.get_access_token()
    target_url = f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/runs/{run.id}"

    try:
        response = github_request(
            "POST",
            f"https://api.github.com/repos/{repo.repo_full_name}/statuses/{run.commit_sha}",
            access_token=access_token,
            json={
                "state": state,
                "description": description[:140],
                "context": f"PostHog Visual Review / {run.run_type}",
                "target_url": target_url,
            },
            timeout=10,
        )

        if response.status_code != 201:
            logger.warning(
                "visual_review.status_check_failed",
                run_id=str(run.id),
                status_code=response.status_code,
                response=response.text[:200],
            )
    except Exception:
        logger.warning("visual_review.status_check_error", run_id=str(run.id), exc_info=True)


def _commit_baseline_to_github(run: Run, repo: Repo, approved_snapshots: list[dict]) -> dict:
    """
    Commit updated baseline file to GitHub.

    Raises:
        GitHubIntegrationNotFoundError: No GitHub integration for team
        PRSHAMismatchError: PR has newer commits than this run
        BaselineFilePathNotConfiguredError: No baseline path for run type
        GitHubCommitError: GitHub API error
    """
    baseline_paths = repo.baseline_file_paths or {}
    baseline_path = baseline_paths.get(run.run_type) or baseline_paths.get("default", ".snapshots.yml")

    if not baseline_path:
        raise BaselineFilePathNotConfiguredError(f"No baseline file path configured for run type {run.run_type}")

    github = get_github_integration_for_repo(repo)

    if github.access_token_expired():
        github.refresh_access_token()

    if run.pr_number is None:
        raise GitHubCommitError("Cannot commit to GitHub: run has no associated PR number")

    pr_info = _get_pr_info(github, repo.repo_full_name, run.pr_number)

    if pr_info["head_sha"] != run.commit_sha:
        raise PRSHAMismatchError(
            f"PR has newer commits. Expected {run.commit_sha}, got {pr_info['head_sha']}. "
            "Please re-run visual tests on the latest commit."
        )

    current_baselines, file_sha = _fetch_baseline_file(github, repo.repo_full_name, baseline_path, pr_info["head_ref"])

    # Remove entries for snapshots detected as removed in this run
    removed_identifiers = set(run.snapshots.filter(result=SnapshotResult.REMOVED).values_list("identifier", flat=True))
    for identifier in removed_identifiers:
        current_baselines.pop(identifier, None)

    updates = [{"identifier": s["identifier"], "new_hash": s["new_hash"]} for s in approved_snapshots]
    new_content = _build_snapshots_yaml(repo, current_baselines, updates)

    # Use GitHubIntegration.update_file() - it expects just the repo name, not full path
    # The org comes from github.organization()
    repo_name = repo.repo_full_name.split("/")[-1] if "/" in repo.repo_full_name else repo.repo_full_name

    updated_count = len(updates)
    removed_count = len(removed_identifiers)
    parts = [f"{updated_count} updated"]
    if removed_count:
        parts.append(f"{removed_count} removed")
    summary = ", ".join(parts)
    commit_message = f"chore(visual): update {run.run_type} baselines\n\n{summary}\nRun: {run.id}"

    result = github.update_file(
        repository=repo_name,
        file_path=baseline_path,
        content=new_content,
        commit_message=commit_message,
        branch=pr_info["head_ref"],
        sha=file_sha,
    )

    if not result.get("success"):
        raise GitHubCommitError(f"Failed to commit baseline: {result.get('error')}")

    run.metadata["baseline_commit_sha"] = result.get("commit_sha")
    run.save(update_fields=["metadata"])

    return result


def _find_existing_comment_id(repo: Repo, pr_number: int, exclude_run_id: UUID) -> int | None:
    """Find the GitHub comment ID from a previous run on the same PR."""
    previous_run = (
        Run.objects.filter(repo=repo, pr_number=pr_number, metadata__has_key="github_comment_id")
        .exclude(id=exclude_run_id)
        .order_by("-created_at")
        .first()
    )
    if previous_run:
        value = previous_run.metadata.get("github_comment_id")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _post_review_prompt_comment(run: Run, repo: Repo) -> None:
    """
    Post or update a PR comment prompting reviewers to approve visual changes.

    One comment per PR — subsequent runs update the existing comment in place.
    Skips non-actionable runs (observe-only, stale/superseded, already commented).
    Best-effort and never raises.
    """
    if not repo.enable_pr_comments:
        return

    if not repo.repo_full_name or run.pr_number is None:
        return

    if run.purpose == RunPurpose.OBSERVE or is_run_stale(run):
        return

    if run.metadata.get("github_comment_id"):
        return

    from django.conf import settings

    run_url = f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/runs/{run.id}"
    comment_body = (
        f"👋 **Visual changes detected** for this PR.\n\n"
        f"[Review and approve in PostHog Visual Review]({run_url})\n\n"
        f"If these changes are unexpected, they may be caused by a flaky test or a "
        f"broken snapshot on master. Don't approve — rerun the job or wait for a fix."
    )

    try:
        existing_comment_id = _find_existing_comment_id(repo, run.pr_number, exclude_run_id=run.id)
        if existing_comment_id:
            response = _github_api_request(
                method="PATCH",
                repo=repo,
                path=f"issues/comments/{existing_comment_id}",
                json={"body": comment_body},
                timeout=10,
            )
            if response.status_code == 200:
                run.metadata["github_comment_id"] = existing_comment_id
                run.save(update_fields=["metadata"])
                return
            # Comment was deleted or inaccessible — fall through to create new one
            logger.info(
                "visual_review.pr_comment_update_failed_will_create",
                run_id=str(run.id),
                comment_id=existing_comment_id,
                status_code=response.status_code,
            )

        response = _github_api_request(
            method="POST",
            repo=repo,
            path=f"issues/{run.pr_number}/comments",
            json={"body": comment_body},
            timeout=10,
        )
        if response.status_code == 201:
            comment_id = response.json().get("id")
            run.metadata["github_comment_id"] = comment_id
            run.save(update_fields=["metadata"])
        else:
            logger.warning(
                "visual_review.pr_comment_failed",
                run_id=str(run.id),
                pr_number=run.pr_number,
                status_code=response.status_code,
                response=response.text[:200],
            )
    except Exception:
        logger.warning("visual_review.pr_comment_error", run_id=str(run.id), pr_number=run.pr_number, exc_info=True)


@transaction.atomic(using=WRITER_DB)
def approve_all(
    run_id: UUID,
    user_id: int,
    team_id: int | None = None,
    review_decision: ReviewDecision = ReviewDecision.HUMAN_APPROVED,
    commit_to_github: bool = True,
) -> tuple[Run, str]:
    """Approve all actionable snapshots and return signed baseline YAML.

    Collects all CHANGED + NEW snapshots, approves them via approve_run,
    and builds a signed baseline YAML. REMOVED snapshots are handled by
    approve_run (marked as approved + pruned from baseline).

    The caller controls review_decision:
    - HUMAN_APPROVED: UI "Approve all changes" button
    - AUTO_APPROVED: CLI --auto-approve during CI

    Set commit_to_github=False for CLI (writes baseline locally).
    """
    run = _get_run_for_update(run_id, team_id=team_id)
    repo = run.repo

    if run.status != RunStatus.COMPLETED:
        raise ValueError(f"Run must be completed before approval (current status: {run.status})")

    if is_run_stale(run):
        raise StaleRunError("This run has been superseded by a newer run.")

    # Collect all actionable snapshots (changed + new have hashes to approve)
    needs_approval = [
        {"identifier": s.identifier, "new_hash": s.current_hash}
        for s in run.snapshots.all()
        if s.result in (SnapshotResult.CHANGED, SnapshotResult.NEW)
    ]

    if not run.approved:
        approve_run(
            run_id=run_id,
            user_id=user_id,
            team_id=team_id,
            approved_snapshots=needs_approval,
            review_decision=review_decision,
            commit_to_github=commit_to_github,
        )
        run = get_run_with_snapshots(run_id)

    snapshots = list(run.snapshots.all().order_by("identifier"))

    # Fetch current baseline from GitHub — the authoritative source.
    # This ensures unchanged entries are preserved even in delta mode
    # where unchanged snapshots have no RunSnapshot rows.
    baseline_paths = repo.baseline_file_paths or {}
    baseline_path = baseline_paths.get(run.run_type) or baseline_paths.get("default", ".snapshots.yml")
    current_baselines: dict[str, dict] = {}

    github = get_github_integration_for_repo(repo)
    if github.access_token_expired():
        github.refresh_access_token()
    current_baselines, _file_sha = _fetch_baseline_file(github, repo.repo_full_name, baseline_path, run.branch)

    # Remove entries that are now REMOVED — they should not persist in the baseline
    removed_identifiers = {s.identifier for s in snapshots if s.result == SnapshotResult.REMOVED}
    for identifier in removed_identifiers:
        current_baselines.pop(identifier, None)

    # Apply changes from this run on top of the baseline
    updates = [
        {"identifier": s.identifier, "new_hash": s.current_hash}
        for s in snapshots
        if s.result in (SnapshotResult.CHANGED, SnapshotResult.NEW)
    ]

    baseline_content = _build_snapshots_yaml(repo, current_baselines=current_baselines, updates=updates)
    return run, baseline_content


@transaction.atomic(using=WRITER_DB)
def approve_snapshots(run_id: UUID, user_id: int, approved_snapshots: list[dict], team_id: int | None = None) -> Run:
    """Approve specific snapshots within a run (DB only, no GitHub commit).

    Used for per-snapshot "Accept change" in the UI. Does not finalize
    the run — that happens via approve_run.
    """
    run = _get_run_for_update(run_id, team_id=team_id)

    if run.purpose == RunPurpose.OBSERVE:
        raise ValueError("Observational runs cannot be approved")

    if is_run_stale(run):
        raise StaleRunError("This run has been superseded by a newer run. Approve the latest run instead.")

    approvals = {s["identifier"]: s["new_hash"] for s in approved_snapshots}
    _validate_approval(run, approvals)

    now = timezone.now()
    for snapshot in run.snapshots.filter(identifier__in=approvals.keys()):
        new_hash = approvals[snapshot.identifier]
        snapshot.review_state = ReviewState.APPROVED
        snapshot.reviewed_at = now
        snapshot.reviewed_by_id = user_id
        snapshot.approved_hash = new_hash
        snapshot.save(update_fields=["review_state", "reviewed_at", "reviewed_by_id", "approved_hash"])

    return run


@transaction.atomic(using=WRITER_DB)
def approve_run(
    run_id: UUID,
    user_id: int,
    approved_snapshots: list[dict],
    team_id: int | None = None,
    review_decision: ReviewDecision = ReviewDecision.HUMAN_APPROVED,
    commit_to_github: bool = True,
) -> Run:
    """Approve snapshots and finalize the run — commit baseline, post status.

    This is the full approval path: validate, commit to GitHub, mark
    snapshots approved, mark removed as approved, mark run approved,
    and post a success commit status.

    Set commit_to_github=False only for CLI auto-approve (writes locally).
    """
    run = _get_run_for_update(run_id, team_id=team_id)
    repo = run.repo

    if run.purpose == RunPurpose.OBSERVE:
        raise ValueError("Observational runs cannot be approved")

    if is_run_stale(run):
        raise StaleRunError("This run has been superseded by a newer run. Approve the latest run instead.")

    approvals = {s["identifier"]: s["new_hash"] for s in approved_snapshots}
    _validate_approval(run, approvals)

    # Commit to GitHub first — do this before DB changes so we can fail cleanly
    if commit_to_github and run.pr_number and repo.repo_full_name:
        _commit_baseline_to_github(run, repo, approved_snapshots)

    # Mark approved snapshots
    now = timezone.now()
    for snapshot in run.snapshots.filter(identifier__in=approvals.keys()):
        new_hash = approvals[snapshot.identifier]
        snapshot.review_state = ReviewState.APPROVED
        snapshot.reviewed_at = now
        snapshot.reviewed_by_id = user_id
        snapshot.approved_hash = new_hash
        snapshot.save(update_fields=["review_state", "reviewed_at", "reviewed_by_id", "approved_hash"])

    # Mark removed snapshots as approved (cleanup, not actionable)
    run.snapshots.filter(result=SnapshotResult.REMOVED).update(
        review_state=ReviewState.APPROVED,
        reviewed_at=now,
        reviewed_by_id=user_id,
    )

    # Re-evaluate quarantine at approval time
    _stamp_quarantine(run)

    # Finalize run
    run.approved = True
    run.review_decision = review_decision
    run.approved_at = now
    run.approved_by_id = user_id
    run.save(update_fields=["approved", "review_decision", "approved_at", "approved_by_id"])

    if commit_to_github:
        _post_commit_status(run, repo, "success", "Visual changes approved")

    return run


def _validate_approval(run: Run, approvals: dict[str, str]) -> None:
    """Validate snapshot identifiers, hash matches, and artifact existence."""
    repo = run.repo

    run_identifiers = set(run.snapshots.values_list("identifier", flat=True))
    unknown = set(approvals.keys()) - run_identifiers
    if unknown:
        raise ValueError(f"Unknown snapshot identifiers: {', '.join(sorted(unknown))}")

    for snapshot in run.snapshots.filter(identifier__in=approvals.keys()):
        expected_hash = approvals[snapshot.identifier]
        if expected_hash != snapshot.current_hash:
            raise ValueError(
                f"Hash mismatch for {snapshot.identifier}: "
                f"approved {expected_hash[:12]} but current is {snapshot.current_hash[:12]}"
            )

    for identifier, new_hash in approvals.items():
        artifact = get_artifact(repo.id, new_hash)
        if not artifact:
            raise ArtifactNotFoundError(f"Artifact not found for hash {new_hash} (snapshot: {identifier})")


# --- Snapshot Operations ---


def get_thumbnail_hash_for_identifier(repo_id: UUID, identifier: str) -> str | None:
    """Look up the thumbnail content hash for a snapshot identifier.

    Finds the most recent artifact with a thumbnail for this identifier
    across all runs. Returns the thumbnail's content_hash or None.
    """
    snapshot = (
        RunSnapshot.objects.filter(
            run__repo_id=repo_id,
            identifier=identifier,
            current_artifact__thumbnail__isnull=False,
        )
        .select_related("current_artifact__thumbnail")
        .order_by("-run__created_at")
        .first()
    )

    if snapshot is None:
        return None

    artifact = snapshot.current_artifact
    if artifact is None or artifact.thumbnail is None:
        return None

    return artifact.thumbnail.content_hash


def read_thumbnail_bytes(repo_id: UUID, content_hash: str) -> bytes | None:
    storage = ArtifactStorage(str(repo_id))
    return storage.read(content_hash)


def get_run_snapshots(run_id: UUID, team_id: int | None = None) -> list[RunSnapshot]:
    run = get_run(run_id, team_id=team_id)
    return list(
        run.snapshots.select_related("current_artifact", "baseline_artifact", "diff_artifact").order_by(
            db_models.Case(
                db_models.When(result=SnapshotResult.UNCHANGED, then=1),
                default=0,
            ),
            "identifier",
        )
    )


# Default-branch fallback. We don't track repos' actual default branch, so we
# include both candidates and assume nobody has both — whichever has rows wins.
# When `trunk`/`develop`-style defaults show up, this becomes a `Repo` field.
_DEFAULT_BRANCHES = ("master", "main")


_SNAPSHOT_HISTORY_DEDUP_SQL = """
WITH ordered AS (
    SELECT rs.id,
           rs.current_artifact_id,
           LAG(rs.current_artifact_id) OVER (ORDER BY r.created_at DESC) AS prev_artifact_id,
           r.created_at
    FROM visual_review_runsnapshot rs
    JOIN visual_review_run r ON r.id = rs.run_id
    WHERE r.repo_id = %s
      AND r.run_type = %s
      AND r.branch = ANY(%s)
      AND r.status = 'completed'
      AND rs.identifier = %s
      AND rs.result IN ('changed', 'removed', 'new')
)
SELECT id
FROM ordered
WHERE prev_artifact_id IS DISTINCT FROM current_artifact_id
ORDER BY created_at DESC
"""


def get_snapshot_history(repo_id: UUID, identifier: str, run_type: str) -> list[RunSnapshot]:
    """Baseline timeline for a snapshot identifier on the default branch.

    Returns one entry per *baseline event* — i.e. each time the committed content
    actually changed. Dedup happens server-side via a `LAG` window function over
    runs ordered by `created_at DESC`: a row is kept only when its
    `current_artifact_id` differs from its predecessor's. Plan stays the same as
    the un-deduped query (verified on prod) — the WindowAgg piggybacks on the
    sort already needed for ORDER BY, so the dedup is essentially free and we
    avoid shipping the full raw history (often 100×–1000× larger) to Python.

    Filters applied at the DB level:
      - branch ∈ master/main, run_type, repo: scope to default-branch runs of this kind
      - status=completed: drop pre-classification rows. `result` defaults to NEW
        on upload and is only finalised when the run completes; runs stuck in
        pending/processing leave noise behind that isn't a real history event.
      - result IN (changed, removed, new): only rows that move the baseline.
        `unchanged` rows must be excluded *before* the LAG window — each capture
        gets its own Artifact row even when the diff says the content matches
        baseline (pixel jitter → different bytes → different content_hash), so
        consecutive `unchanged` rows have differing `current_artifact_id`s and
        would all slip past the dedup as fake "baseline events". For one prod
        identifier we observed 99 fake events behind 2 real baselines.
        Including `new` so first captures (the initial baseline event) appear
        in history; `status=completed` already keeps pre-classification NEW
        out.
    """
    with connections[READER_DB].cursor() as cursor:
        cursor.execute(
            _SNAPSHOT_HISTORY_DEDUP_SQL,
            [str(repo_id), run_type, list(_DEFAULT_BRANCHES), identifier],
        )
        ordered_ids: list[UUID] = [row[0] for row in cursor.fetchall()]

    if not ordered_ids:
        return []

    # `id__in` doesn't preserve order, so look rows up by id and re-emit in the
    # cursor's order. Fetched count equals the deduped baseline-event count
    # (typically <20), so this hydration is cheap regardless of raw history size.
    rows_by_id: dict[UUID, RunSnapshot] = {
        row.id: row for row in RunSnapshot.objects.filter(id__in=ordered_ids).select_related("run", "current_artifact")
    }
    return [rows_by_id[rid] for rid in ordered_ids if rid in rows_by_id]


def get_baselines_overview(repo_id: UUID) -> _BaselineOverviewRaw:
    """Universe of identifiers with a current baseline, plus aggregates.

    The "current baseline" universe is anchored on the latest non-superseded run
    on the default branch (master/main) for each `run_type`. One row per
    `(run_type, identifier)` — the closest thing to "what we'd compare a new
    capture against right now".

    Performance shape:
      - O(run_types) queries to find the universe runs (≤ a handful in practice)
      - 1 query for the universe rows (with thumbnail + artifact prefetch)
      - 3 grouped queries for tolerate counts + active quarantines + sparkline
      - 3 cheap aggregate queries for totals
    """
    from collections import Counter, defaultdict
    from datetime import timedelta

    from .facade.contracts import BASELINE_OVERVIEW_MAX_ENTRIES, BASELINE_SPARKLINE_DAYS

    now = timezone.now()
    # The sparkline shows DAYS dates inclusive of today (see
    # `_build_sparkline_day_keys`). `now - DAYS days` would pull rows from a
    # 31st earlier date that has no day_key — they'd vanish into a bucket
    # that's never read, but their `diff_percentage` would still skew
    # `recent_diff_avg`. `DAYS - 1` aligns with the day-key window.
    sparkline_cutoff = now - timedelta(days=BASELINE_SPARKLINE_DAYS - 1)

    # 1. Find the latest non-superseded run on the default branch for every
    # (repo, run_type). The partial unique index `unique_latest_run_per_group`
    # ensures at most one row per group.
    universe_runs = list(
        Run.objects.filter(
            repo_id=repo_id,
            branch__in=_DEFAULT_BRANCHES,
            superseded_by__isnull=True,
        ).only("id", "run_type", "completed_at", "created_at")
    )
    universe_run_ids = [r.id for r in universe_runs]
    if not universe_run_ids:
        return _BaselineOverviewRaw(
            entries=[],
            tolerate_30d_by_id={},
            tolerate_90d_by_id={},
            quarantined_ids=set(),
            sparkline_by_key={},
            drift_avg_by_key={},
            totals_all=0,
            totals_recent=0,
            totals_frequent=0,
            totals_quarantined=0,
            by_run_type={},
            truncated=False,
            generated_at=now,
        )

    # 2. Pull the universe rows. select_related the chain we need for thumbnails.
    universe_qs = (
        RunSnapshot.objects.filter(run_id__in=universe_run_ids)
        .select_related("run", "current_artifact__thumbnail")
        .only(
            "identifier",
            "metadata",
            "run__id",
            "run__run_type",
            "run__completed_at",
            "run__created_at",
            "current_artifact__width",
            "current_artifact__height",
            "current_artifact__thumbnail__content_hash",
        )
        # Stable ordering so truncation is deterministic; newest baselines first.
        .order_by("-run__completed_at", "identifier")
    )
    total_universe = universe_qs.count()
    truncated = total_universe > BASELINE_OVERVIEW_MAX_ENTRIES
    universe = list(universe_qs[:BASELINE_OVERVIEW_MAX_ENTRIES]) if truncated else list(universe_qs)
    # Per-entry aggregates (tolerate counts, sparklines) only need to cover the
    # entries we'll return. Totals must scope across the *full* universe,
    # otherwise truncation makes them undercount in misleading ways (a 6000-id
    # repo would show 0 frequently-tolerated if all of them sat past the slice).
    universe_identifiers = list({s.identifier for s in universe})
    if truncated:
        full_universe_identifiers = list(universe_qs.values_list("identifier", flat=True).distinct())
    else:
        full_universe_identifiers = universe_identifiers

    # 3a. Tolerate counts in 30d / 90d windows. Single grouped query each.
    tolerate_30d_by_id: dict[str, int] = {}
    tolerate_90d_by_id: dict[str, int] = {}
    if universe_identifiers:
        tol_30d_cutoff = now - timedelta(days=30)
        tol_90d_cutoff = now - timedelta(days=90)
        for identifier, count in (
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=universe_identifiers,
                created_at__gte=tol_30d_cutoff,
            )
            .values_list("identifier")
            .annotate(c=Count("id"))
            .values_list("identifier", "c")
        ):
            tolerate_30d_by_id[identifier] = count
        for identifier, count in (
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=universe_identifiers,
                created_at__gte=tol_90d_cutoff,
            )
            .values_list("identifier")
            .annotate(c=Count("id"))
            .values_list("identifier", "c")
        ):
            tolerate_90d_by_id[identifier] = count

    # 3b. Active quarantines for this repo, scoped to the universe identifiers
    # AND the run_types they live on (quarantine is per (repo, run_type, id)).
    quarantined_pairs: set[tuple[str, str]] = set()
    if universe_identifiers:
        quarantined_pairs = {
            (run_type, identifier)
            for run_type, identifier in QuarantinedIdentifier.objects.filter(
                repo_id=repo_id,
                identifier__in=universe_identifiers,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .values_list("run_type", "identifier")
        }

    # 3c. Sparkline — last 30 days of run results bucketed by classification.
    # One grouped query, then bucket in Python so we keep this portable across
    # SQLite (tests) and Postgres without resorting to TruncDate or SQL CASE.
    # Same loop also accumulates the running drift average so we get
    # `recent_diff_avg` for free in this single pass. Keyed by
    # `(run_type, identifier)` because the universe is one row per pair —
    # same identifier in storybook + playwright are *different* baselines and
    # their sparklines must not bleed into each other.
    sparkline_by_key: dict[tuple[str, str], dict[str, SparkBuckets]] = defaultdict(lambda: defaultdict(SparkBuckets))
    drift_sum_by_key: dict[tuple[str, str], float] = defaultdict(float)
    drift_count_by_key: dict[tuple[str, str], int] = defaultdict(int)
    if universe_identifiers:
        spark_rows = RunSnapshot.objects.filter(
            run__repo_id=repo_id,
            identifier__in=universe_identifiers,
            run__created_at__gte=sparkline_cutoff,
        ).values_list(
            "identifier",
            "run__run_type",
            "run__created_at",
            "result",
            "is_quarantined",
            "tolerated_hash_match_id",
            "diff_percentage",
        )
        for identifier, run_type, run_created_at, result, is_quar, tol_match_id, diff_pct in spark_rows:
            day_key = run_created_at.date().isoformat()
            key = (run_type, identifier)
            buckets = sparkline_by_key[key][day_key]
            # `tolerated_hash_match` is a nullable FK but django-stubs types
            # the `_id` column as a non-optional UUID, so without this widen
            # mypy thinks `is not None` always succeeds → flags every later
            # branch as unreachable.
            tol_match_id_opt: UUID | None = tol_match_id
            if is_quar:
                buckets.quarantined += 1
            elif tol_match_id_opt is not None:
                buckets.tolerated += 1
            elif result == "unchanged":
                buckets.clean += 1
            else:
                buckets.changed += 1
            if diff_pct is not None and diff_pct > 0:
                drift_sum_by_key[key] += diff_pct
                drift_count_by_key[key] += 1

    # 4. Totals computed across the *full* universe (not the truncated slice)
    # so the stat row stays correct when the entries are clipped.
    if truncated:
        # Re-issue a small COUNT-only query for accurate totals across the
        # universe; we already have the truncated list in memory.
        totals_all = total_universe
    else:
        totals_all = len(universe)

    # Recently / frequently tolerated — counts of distinct identifiers with
    # ≥1 (or ≥3) tolerations in the rolling window. Scope across the *full*
    # universe so the stat row stays correct under truncation.
    recent_cutoff = now - timedelta(days=30)
    frequent_cutoff = now - timedelta(days=90)
    recent_ids: set[str] = set()
    frequent_ids: set[str] = set()
    if full_universe_identifiers:
        recent_ids = set(
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=full_universe_identifiers,
                created_at__gte=recent_cutoff,
            )
            .values_list("identifier", flat=True)
            .distinct()
        )
        frequent_grouped = (
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=full_universe_identifiers,
                created_at__gte=frequent_cutoff,
            )
            .values("identifier")
            .annotate(c=Count("id"))
            .filter(c__gte=3)
            .values_list("identifier", flat=True)
        )
        frequent_ids = set(frequent_grouped)

    # `quarantined_pairs` was built from the truncated set above (per-entry
    # attached). Re-query for the totals so they cover the full universe.
    if truncated and full_universe_identifiers:
        quarantined_id_count = (
            QuarantinedIdentifier.objects.filter(
                repo_id=repo_id,
                identifier__in=full_universe_identifiers,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .values("identifier")
            .distinct()
            .count()
        )
    else:
        quarantined_id_count = len({identifier for _, identifier in quarantined_pairs})

    # by_run_type counts every entry in the universe. Aggregate query under
    # truncation so it doesn't undercount; in-memory Counter when not truncated
    # (we already paid for the row hydration).
    if truncated:
        by_run_type = dict(
            universe_qs.values_list("run__run_type")
            .order_by()
            .annotate(c=Count("id"))
            .values_list("run__run_type", "c")
        )
    else:
        by_run_type = dict(Counter(s.run.run_type for s in universe))

    drift_avg_by_key: dict[tuple[str, str], float] = {
        key: drift_sum_by_key[key] / drift_count_by_key[key]
        for key in drift_count_by_key
        if drift_count_by_key[key] > 0
    }

    return _BaselineOverviewRaw(
        entries=universe,
        tolerate_30d_by_id=tolerate_30d_by_id,
        tolerate_90d_by_id=tolerate_90d_by_id,
        quarantined_ids=quarantined_pairs,
        sparkline_by_key=sparkline_by_key,
        drift_avg_by_key=drift_avg_by_key,
        totals_all=totals_all,
        totals_recent=len(recent_ids),
        totals_frequent=len(frequent_ids),
        totals_quarantined=quarantined_id_count,
        by_run_type=by_run_type,
        truncated=truncated,
        generated_at=now,
    )


@dataclass
class SparkBuckets:
    """One day's classification counts on the stability sparkline.

    Public so the facade can construct a zero-default without reaching into
    private symbols of this module. Otherwise an internal-only shape.
    """

    clean: int = 0
    tolerated: int = 0
    changed: int = 0
    quarantined: int = 0


@dataclass
class _BaselineOverviewRaw:
    """Internal raw shape — the facade layer reshapes this into the public DTOs.

    Kept private to logic.py so that contract changes don't ripple through here.
    """

    entries: list[RunSnapshot]
    tolerate_30d_by_id: dict[str, int]
    tolerate_90d_by_id: dict[str, int]
    quarantined_ids: set[tuple[str, str]]
    # Sparkline + drift are keyed by `(run_type, identifier)` because the same
    # identifier in different run types is a different baseline; merging would
    # bleed storybook stability into playwright stability.
    sparkline_by_key: dict[tuple[str, str], dict[str, SparkBuckets]]
    drift_avg_by_key: dict[tuple[str, str], float]
    totals_all: int
    totals_recent: int
    totals_frequent: int
    totals_quarantined: int
    by_run_type: dict[str, int]
    truncated: bool
    generated_at: datetime


@transaction.atomic(using=WRITER_DB)
def mark_snapshot_as_tolerated(run_id: UUID, snapshot_id: UUID, user_id: int, team_id: int) -> RunSnapshot:
    """Mark a changed snapshot as a known tolerated alternate (human decision).

    Creates a ToleratedHash entry tied to the current baseline, reclassifies the
    snapshot as UNCHANGED, and recalculates run summary counts.
    """
    run = _get_run_for_update(run_id, team_id=team_id)
    try:
        snapshot = RunSnapshot.objects.get(id=snapshot_id, run=run, team_id=team_id)
    except RunSnapshot.DoesNotExist:
        raise RunNotFoundError(f"Snapshot {snapshot_id} not found in run {run_id}")

    if snapshot.result != SnapshotResult.CHANGED:
        raise ValueError(f"Can only mark CHANGED snapshots as tolerated (current: {snapshot.result})")

    if not snapshot.current_hash:
        raise ValueError("Snapshot has no current hash")

    tolerated, _ = ToleratedHash.objects.get_or_create(
        repo_id=run.repo_id,
        identifier=snapshot.identifier,
        baseline_hash=snapshot.baseline_hash,
        alternate_hash=snapshot.current_hash,
        defaults={
            "team_id": team_id,
            "reason": ToleratedReason.HUMAN,
            "source_run": run,
            "created_by_id": user_id,
            "diff_percentage": snapshot.diff_percentage,
        },
    )

    # result stays CHANGED — it's the technical truth (hashes differ).
    # review_state captures the human decision to tolerate.
    snapshot.review_state = ReviewState.TOLERATED
    snapshot.reviewed_at = timezone.now()
    snapshot.reviewed_by_id = user_id
    snapshot.tolerated_hash_match = tolerated
    snapshot.save(update_fields=["review_state", "reviewed_at", "reviewed_by_id", "tolerated_hash_match"])

    # Update tolerated_match_count (only human-tolerated, not auto-threshold)
    tolerated_count = (
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run=run, tolerated_hash_match__isnull=False, tolerated_hash_match__reason=ToleratedReason.HUMAN)
        .count()
    )
    Run.objects.using(WRITER_DB).filter(id=run.id).update(tolerated_match_count=tolerated_count)

    return snapshot


def get_tolerated_hashes_for_identifier(repo_id: UUID, identifier: str) -> list[ToleratedHash]:
    """List all tolerated hashes for a snapshot identifier, most recent first."""
    return list(ToleratedHash.objects.filter(repo_id=repo_id, identifier=identifier).order_by("-created_at"))


# --- Quarantine ---


def list_quarantined_identifiers(
    repo_id: UUID, team_id: int, identifier: str | None = None, run_type: str | None = None
) -> list[QuarantinedIdentifier]:
    qs = QuarantinedIdentifier.objects.using(WRITER_DB).filter(repo_id=repo_id, team_id=team_id)
    if run_type:
        qs = qs.filter(run_type=run_type)
    if identifier:
        qs = qs.filter(identifier=identifier)
    else:
        now = timezone.now()
        qs = qs.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    return list(qs.order_by("-created_at"))


@transaction.atomic(using=WRITER_DB)
def quarantine_identifier(
    repo_id: UUID,
    identifier: str,
    run_type: str,
    reason: str,
    user_id: int,
    team_id: int,
    expires_at: datetime | None = None,
) -> QuarantinedIdentifier:
    get_repo(repo_id, team_id)  # raises RepoNotFoundError if repo not owned by team
    now = timezone.now()
    QuarantinedIdentifier.objects.using(WRITER_DB).select_for_update().filter(
        repo_id=repo_id,
        identifier=identifier,
        run_type=run_type,
        team_id=team_id,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).update(expires_at=now)
    return QuarantinedIdentifier.objects.using(WRITER_DB).create(
        repo_id=repo_id,
        identifier=identifier,
        run_type=run_type,
        team_id=team_id,
        reason=reason,
        expires_at=expires_at,
        created_by_id=user_id,
    )


def unquarantine_identifier(repo_id: UUID, identifier: str, run_type: str, team_id: int) -> None:
    get_repo(repo_id, team_id)  # raises RepoNotFoundError if repo not owned by team
    QuarantinedIdentifier.objects.using(WRITER_DB).filter(
        repo_id=repo_id,
        identifier=identifier,
        run_type=run_type,
        team_id=team_id,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())).update(expires_at=timezone.now())


def expire_quarantine_entry(entry_id: UUID, team_id: int) -> None:
    now = timezone.now()
    active = Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    try:
        entry = QuarantinedIdentifier.objects.using(WRITER_DB).filter(active).get(id=entry_id, team_id=team_id)
    except QuarantinedIdentifier.DoesNotExist as e:
        raise RunNotFoundError(f"Quarantine entry {entry_id} not found or already expired") from e

    # Expire all active entries for the same identifier/run_type, not just this one
    QuarantinedIdentifier.objects.using(WRITER_DB).filter(
        repo_id=entry.repo_id,
        identifier=entry.identifier,
        run_type=entry.run_type,
        team_id=team_id,
    ).filter(active).update(expires_at=now)


def update_snapshot_diff(
    snapshot_id: UUID,
    diff_artifact: Artifact,
    diff_percentage: float,
    diff_pixel_count: int,
    team_id: int | None = None,
) -> RunSnapshot:
    qs = RunSnapshot.objects.select_related("run")
    if team_id is not None:
        qs = qs.filter(team_id=team_id)
    snapshot = qs.get(id=snapshot_id)
    if diff_artifact.repo_id != snapshot.run.repo_id:
        raise ValueError(
            f"Cross-repo artifact reference: artifact repo {diff_artifact.repo_id} "
            f"!= snapshot repo {snapshot.run.repo_id}"
        )
    if snapshot.result != SnapshotResult.CHANGED:
        raise ValueError(f"Cannot attach diff to snapshot with result={snapshot.result}, expected 'changed'")
    snapshot.diff_artifact = diff_artifact
    snapshot.diff_percentage = diff_percentage
    snapshot.diff_pixel_count = diff_pixel_count
    snapshot.save(update_fields=["diff_artifact", "diff_percentage", "diff_pixel_count"])
    return snapshot


def link_artifact_to_snapshots(repo_id: UUID, content_hash: str) -> int:
    """
    After an artifact is uploaded, link it to any pending snapshots.

    Returns number of snapshots updated.
    """
    artifact = get_artifact(repo_id, content_hash)
    if not artifact:
        return 0

    # Link as current artifact where hash matches but artifact not linked
    current_updated = RunSnapshot.objects.filter(
        run__repo_id=repo_id,
        current_hash=content_hash,
        current_artifact__isnull=True,
    ).update(current_artifact=artifact)

    # Link as baseline artifact where hash matches but artifact not linked
    baseline_updated = RunSnapshot.objects.filter(
        run__repo_id=repo_id,
        baseline_hash=content_hash,
        baseline_artifact__isnull=True,
    ).update(baseline_artifact=artifact)

    return current_updated + baseline_updated
