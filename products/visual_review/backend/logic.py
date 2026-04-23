"""
Business logic for visual_review.

ORM queries, validation, calculations, business rules.
Called by api/api.py facade. Do not call from outside this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import (
    models as db_models,
    transaction,
)
from django.db.models import Count, F, Q
from django.utils import timezone

import structlog

if TYPE_CHECKING:
    from posthog.models.integration import GitHubIntegration

from .classifier import SnapshotClassifier
from .db import WRITER_DB
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


def list_runs_for_team(team_id: int, review_state: str | None = None) -> db_models.QuerySet[Run]:
    qs = Run.objects.filter(team_id=team_id).select_related("repo").order_by("-created_at")
    if review_state and review_state in REVIEW_STATE_FILTERS:
        qs = qs.filter(REVIEW_STATE_FILTERS[review_state])
    return qs


def get_review_state_counts(team_id: int) -> dict[str, int]:
    qs = Run.objects.filter(team_id=team_id)
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
        # No signing keys configured yet — pass through as unsigned baselines.
        # Once the repo's signing keys are generated (on first baseline fetch),
        # all subsequent baselines must be signed.
        return dict(raw_hashes)

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

    access_token = github.integration.sensitive_config["access_token"]
    try:
        response = requests.get(
            f"https://api.github.com/repos/{repo_full_name}/compare/{quote(base, safe='')}...{quote(head, safe='')}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
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

    access_token = github.integration.sensitive_config["access_token"]
    try:
        response = requests.get(
            f"https://api.github.com/repos/{repo_full_name}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
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

    healed = set(merge_base_baseline) - set(branch_baseline)
    merged = {**merge_base_baseline, **branch_baseline}

    if healed:
        logger.info(
            "visual_review.baseline_healed",
            repo_id=str(repo.id),
            branch=branch,
            healed_count=len(healed),
            branch_count=len(branch_baseline),
            merge_base_count=len(merge_base_baseline),
            merged_count=len(merged),
        )

    return merged, len(healed)


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
    Complete a run: detect removals, verify uploads, trigger diff processing.

    1. Fetches baseline from GitHub, diffs against RunSnapshot rows to find removed
    2. Creates REMOVED RunSnapshot rows
    3. Verifies all expected uploads exist in S3
    4. Creates Artifact records for verified uploads
    5. Links artifacts to snapshots
    6. Triggers async diff processing (only if there are changes to diff)

    Idempotent: returns immediately if already processing or completed.
    """
    run = get_run(run_id)
    if run.status in (RunStatus.PROCESSING, RunStatus.COMPLETED):
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
    baseline, healed_count = _resolve_baselines_with_merge_base(repo, run.run_type, run.branch)
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

    verify_uploads_and_create_artifacts(run_id)

    run = get_run(run_id)

    # Optimization: if no changes, skip diff processing entirely
    if run.changed_count == 0 and run.new_count == 0:
        finalize_run(run_id)
        return get_run(run_id)

    # Mark as processing and trigger diff task
    mark_run_processing(run_id)
    from .tasks.tasks import process_run_diffs

    process_run_diffs.delay(str(run_id))
    return get_run(run_id)


def verify_uploads_and_create_artifacts(run_id: UUID) -> int:
    """
    Verify S3 uploads exist and create Artifact records.

    Called when run is completed. Checks S3 for each expected hash,
    creates Artifact if present, and links to snapshots.

    Returns number of artifacts created.
    """
    run = get_run_with_snapshots(run_id)
    repo_id = run.repo_id
    storage = ArtifactStorage(str(repo_id))

    # Collect all unique hashes we expect
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

    created_count = 0
    for content_hash, metadata in expected_hashes.items():
        # Check if artifact already exists
        if get_artifact(repo_id, content_hash):
            continue

        # Check if file exists in S3
        if not storage.exists(content_hash):
            continue

        # Create artifact record
        storage_path = storage._key(content_hash)
        artifact, created = get_or_create_artifact(
            repo_id=repo_id,
            content_hash=content_hash,
            storage_path=storage_path,
            width=metadata.get("width"),
            height=metadata.get("height"),
            team_id=run.team_id,
        )

        if created:
            created_count += 1
            link_artifact_to_snapshots(repo_id, content_hash)

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


def finalize_run(run_id: UUID, error_message: str = "") -> Run:
    run = get_run_with_snapshots(run_id)

    # Stamp quarantine state — evaluated now and frozen on each snapshot
    _stamp_quarantine(run)

    snapshots = list(run.snapshots.using(WRITER_DB).select_related("tolerated_hash_match").all())

    # Gating counts exclude quarantined identifiers — they don't block PRs
    changed_count = sum(1 for s in snapshots if s.result == SnapshotResult.CHANGED and not s.is_quarantined)
    new_count = sum(1 for s in snapshots if s.result == SnapshotResult.NEW and not s.is_quarantined)
    removed_count = sum(1 for s in snapshots if s.result == SnapshotResult.REMOVED and not s.is_quarantined)
    tolerated_match_count = sum(
        1
        for s in snapshots
        if s.tolerated_hash_match is not None and s.tolerated_hash_match.reason == ToleratedReason.HUMAN
    )

    run.status = RunStatus.FAILED if error_message else RunStatus.COMPLETED
    run.error_message = error_message
    run.completed_at = timezone.now()
    run.changed_count = changed_count
    run.new_count = new_count
    run.removed_count = removed_count
    run.tolerated_match_count = tolerated_match_count
    run.save(
        update_fields=[
            "status",
            "error_message",
            "completed_at",
            "changed_count",
            "new_count",
            "removed_count",
            "tolerated_match_count",
        ]
    )

    repo = run.repo
    if error_message:
        _post_commit_status(run, repo, "error", f"Visual review failed: {error_message[:100]}")
    elif changed_count > 0 or new_count > 0 or removed_count > 0:
        parts = []
        if changed_count:
            parts.append(f"{changed_count} changed")
        if new_count:
            parts.append(f"{new_count} new")
        if removed_count:
            parts.append(f"{removed_count} removed")
        # During migration VR is observational — always green so drift doesn't block PRs.
        # Flip to "failure" when VR becomes the gate.
        _post_commit_status(run, repo, "failure", f"Visual changes detected: {', '.join(parts)}")
        _post_review_prompt_comment(run, repo)
    else:
        _post_commit_status(run, repo, "success", "No visual changes")

    return run


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
    import requests

    access_token = github.integration.sensitive_config["access_token"]
    response = requests.get(
        f"https://api.github.com/repositories/{repo_external_id}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
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
    import requests

    github = get_github_integration_for_repo(repo)
    if github.access_token_expired():
        github.refresh_access_token()

    access_token = github.integration.sensitive_config["access_token"]
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
        **(kwargs.pop("headers", {})),
    }

    url = f"https://api.github.com/repos/{repo.repo_full_name}/{path}"
    response = requests.request(method, url, headers=headers, **kwargs)

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

            url = f"https://api.github.com/repos/{new_full_name}/{path}"
            response = requests.request(method, url, headers=headers, **kwargs)

    return response


def _get_pr_info(github, repo_full_name: str, pr_number: int) -> dict:
    """
    Fetch PR info from GitHub.

    Returns dict with head_ref (branch) and head_sha.
    """
    import requests

    access_token = github.integration.sensitive_config["access_token"]

    response = requests.get(
        f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
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
    import requests

    access_token = github.integration.sensitive_config["access_token"]

    response = requests.get(
        f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}",
        params={"ref": branch},
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
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

    import requests

    try:
        github = get_github_integration_for_repo(repo)
        if github.access_token_expired():
            github.refresh_access_token()
    except Exception:
        logger.debug("visual_review.status_check_skipped", run_id=str(run.id), reason="no_github_integration")
        return

    access_token = github.integration.sensitive_config["access_token"]
    target_url = f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/runs/{run.id}"

    try:
        response = requests.post(
            f"https://api.github.com/repos/{repo.repo_full_name}/statuses/{run.commit_sha}",
            json={
                "state": state,
                "description": description[:140],
                "context": f"PostHog Visual Review / {run.run_type}",
                "target_url": target_url,
            },
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
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
        return previous_run.metadata.get("github_comment_id")
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


def get_snapshot_history(repo_id: UUID, identifier: str, limit: int = 15) -> list[dict]:
    """Recent runs where this snapshot identifier appeared, most recent first."""
    entries = (
        RunSnapshot.objects.filter(
            run__repo_id=repo_id,
            identifier=identifier,
        )
        .select_related("run")
        .order_by("-run__created_at")[:limit]
    )
    return [
        {
            "run_id": entry.run_id,
            "result": entry.result,
            "branch": entry.run.branch,
            "commit_sha": entry.run.commit_sha,
            "created_at": entry.run.created_at,
        }
        for entry in entries
    ]


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
