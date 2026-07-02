"""
Business logic for visual_review.

ORM queries, validation, calculations, business rules.
Called by api/api.py facade. Do not call from outside this module.
"""

from __future__ import annotations

import re
import html
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings
from django.db import (
    connections,
    models as db_models,
    transaction,
)
from django.db.models import Avg, Count, F, Q
from django.utils import timezone

import structlog

if TYPE_CHECKING:
    from posthog.models.integration import GitHubIntegration

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.helpers.trigram_search import TrigramSearchField, apply_trigram_search, normalize_search_term

from .classifier import SnapshotClassifier
from .db import READER_DB, WRITER_DB
from .diff_metadata import DiffMetadata
from .facade.enums import (
    ChangeKind,
    ReviewDecision,
    ReviewState,
    RunPurpose,
    RunStatus,
    SnapshotResult,
    ToleratedReason,
)
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


class RunNotFullyResolvedError(Exception):
    """Finalize blocked because some changed/new snapshots are still unreviewed.

    Visual review is all-or-nothing: the baseline is only committed once every
    changed/new snapshot is approved or tolerated. Committing a subset is pointless
    (CI re-detects the rest on the next run) and would green the gate over unreviewed
    changes.
    """

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
        # nosemgrep: idor-lookup-without-team — resolving team_id from repo
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
        # nosemgrep: idor-lookup-without-team — resolving team_id from repo
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


# Free-text search over the runs list uses the shared trigram helper for the
# prose-like fields (branch, run type), where fuzzy/typo matching helps. Commit
# SHA and PR number are matched exactly (prefix / numeric id) via extra_exact_q —
# fuzzy matching a hex SHA or an integer is meaningless.
RUN_SEARCH_FIELDS = (TrigramSearchField("branch"), TrigramSearchField("run_type"))


def list_runs_for_team(
    team_id: int,
    review_state: str | None = None,
    repo_id: UUID | None = None,
    pr_number: int | None = None,
    commit_sha: str | None = None,
    branch: str | None = None,
    search: str | None = None,
) -> db_models.QuerySet[Run]:
    qs = Run.objects.filter(team_id=team_id).select_related("repo")
    if repo_id is not None:
        qs = qs.filter(repo_id=repo_id)
    if review_state and review_state in REVIEW_STATE_FILTERS:
        qs = qs.filter(REVIEW_STATE_FILTERS[review_state])
    if pr_number is not None:
        qs = qs.filter(pr_number=pr_number)
    if commit_sha:
        qs = qs.filter(commit_sha=commit_sha)
    if branch:
        qs = qs.filter(branch=branch)
    if search and (term := normalize_search_term(search)):
        # Commit SHA matches by prefix (reviewers paste the short SHA); PR number by exact id.
        extra_exact_q = Q(commit_sha__istartswith=term)
        if term.isdigit():
            extra_exact_q |= Q(pr_number=int(term))
        return apply_trigram_search(
            qs,
            term,
            span_prefix="visual_review.runs.search",
            fields=RUN_SEARCH_FIELDS,
            extra_exact_q=extra_exact_q,
            tiebreakers=("-created_at",),
        )
    return qs.order_by("-created_at")


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
            installation_id=github.github_installation_id,
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
            installation_id=github.github_installation_id,
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


def _run_is_on_default_branch(repo: Repo, branch: str) -> bool:
    """Whether this run targets the repo's GitHub default branch.

    Fences the client-supplied ``is_partial`` flag: the default branch holds
    the authoritative full baseline, so a partial run there must not skip
    removed-baseline detection. Resolves the default branch server-side from
    GitHub. Returns ``False`` when it can't be determined (no integration) —
    harmless, since the baseline fetch then returns empty and removal
    detection short-circuits regardless.
    """
    try:
        github = get_github_integration_for_repo(repo)
        if github.access_token_expired():
            github.refresh_access_token()
    except Exception:
        logger.info("visual_review.no_github_integration", repo_id=str(repo.id))
        return False
    return branch == _get_default_branch(github, repo.repo_full_name)


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


def _resolve_baselines_with_merge_base(
    repo: Repo, run_type: str, branch: str, commit_sha: str | None = None
) -> tuple[dict[str, str], int]:
    """Fetch branch baseline merged with merge-base baseline.

    The branch baseline tracks approvals. The merge-base baseline
    fills in entries that were lost during a rebase (the bot commit
    rewrites the full file, and git rebase replays it destructively).

    Branch entries win on conflict so approvals are preserved.
    Identifiers previously approved as REMOVED on this branch are
    tombstoned — healing would otherwise resurrect them from master
    and re-flag them as removed on every subsequent run.

    When *commit_sha* is provided and the run is on the default branch,
    the baseline is fetched at that exact commit instead of the branch
    tip.  This prevents a race where a newer commit updates the
    baseline file before an older commit's VR run completes.

    Returns (merged_baseline, healed_count).
    """
    try:
        github = get_github_integration_for_repo(repo)
        if github.access_token_expired():
            github.refresh_access_token()
    except Exception:
        logger.info("visual_review.no_github_integration", repo_id=str(repo.id))
        return {}, 0

    default_branch = _get_default_branch(github, repo.repo_full_name)

    # On the default branch, pin the baseline to the exact commit so
    # that back-to-back pushes don't race against each other.
    baseline_ref = commit_sha if (commit_sha and branch == default_branch) else branch
    branch_baseline = _resolve_baselines_at_ref(repo, github, run_type, baseline_ref)

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
    is_partial: bool = False,
) -> tuple[Run, list[dict]]:
    """
    Create a new run with its snapshots.

    Returns the run and list of upload targets for missing artifacts.
    Each upload target has: content_hash, url, fields

    baseline_hashes, unchanged_count, removed_identifiers are deprecated —
    the backend fetches baselines from GitHub and computes everything.
    Params kept for backward compat with older CLI versions.

    is_partial tags the run as a subset; the classifier then leaves baseline
    identifiers we didn't touch alone instead of marking them as removed.
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
        is_partial,
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
    is_partial: bool = False,
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
        is_partial=is_partial,
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
    # Pass commit_sha so default-branch runs fetch the baseline at the
    # exact commit being tested, avoiding races with concurrent pushes.
    try:
        baseline, healed_count = _resolve_baselines_with_merge_base(
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
    if run.is_partial and _run_is_on_default_branch(repo, run.branch):
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

    process_run_diffs.delay(run.team_id, str(run_id))
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


def _approved_baseline_updates(snapshots: Iterable[RunSnapshot]) -> list[dict]:
    """The committed-baseline update set: approved changed/new snapshots, by approved hash.

    Derived from DB state so the commit always reflects every approval regardless of how
    many calls it took. Tolerated snapshots are excluded — toleration never updates the baseline.
    """
    return [
        {"identifier": s.identifier, "new_hash": s.approved_hash}
        for s in snapshots
        if s.result in (SnapshotResult.CHANGED, SnapshotResult.NEW)
        and not s.is_quarantined
        and s.review_state == ReviewState.APPROVED
    ]


def _format_change_counts(changed: int, new: int, removed: int) -> str:
    """'N changed, M new, K removed', omitting zero counts; '' when all are zero."""
    parts = []
    if changed:
        parts.append(f"{changed} changed")
    if new:
        parts.append(f"{new} new")
    if removed:
        parts.append(f"{removed} removed")
    return ", ".join(parts)


def _changes_summary(run: Run) -> str:
    """Change summary from the run's denormalized (quarantine-excluded) counts."""
    return _format_change_counts(run.changed_count, run.new_count, run.removed_count)


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

    # Approved-but-uncommitted changes still block the gate: the baseline on the PR branch
    # doesn't reflect them yet, so re-running CI would re-detect them. Only finalize commits
    # the baseline (and posts success directly), so until then the gate must stay red.
    pending_commit = 0 if run.approved else len(_approved_baseline_updates(snapshots))

    repo = run.repo
    if run.error_message:
        _post_commit_status(run, repo, "error", f"Visual review failed: {run.error_message[:100]}")
    elif run.purpose == RunPurpose.OBSERVE:
        # Default-branch (tracking-only) runs never gate — there's no PR to approve.
        # Report any changes as a green, informational status instead of a blocking
        # failure; the per-snapshot detail lives in the VR UI (linked via target_url).
        summary = _changes_summary(run)
        description = f"Tracking only: {summary} recorded" if summary else "Tracking only: no visual changes"
        _post_commit_status(run, repo, "success", description)
    elif unresolved > 0:
        _post_commit_status(run, repo, "failure", f"Visual changes detected: {_changes_summary(run)}")
        _post_review_prompt_comment(run, repo)
    elif pending_commit > 0:
        _post_commit_status(
            run,
            repo,
            "failure",
            f"{pending_commit} approved change(s) awaiting commit — finalize the run to update the baseline",
        )
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
        # Stored as a string, but coerce defensively — `_rerun_github_job` calls `.isdigit()`.
        ci_rerun_triggered, ci_rerun_error = _rerun_github_job(run, str(check_run_id))

    return {
        "counts_changed": counts_changed,
        "unresolved": unresolved,
        "ci_rerun_triggered": ci_rerun_triggered,
        "ci_rerun_error": ci_rerun_error,
    }


def _rerun_github_job(run: Run, check_run_id: str) -> tuple[bool, str | None]:
    """Rerun the visual-review CI job by its numeric ID. Returns (success, error_message).

    The job ID and workflow run ID both come from client-supplied run metadata
    (the CI runner has no server-verified channel today), so before calling
    GitHub we bind the rerun two ways: the job must run on this run's commit
    (``head_sha``) and must belong to the workflow run recorded at creation
    (``github_run_id``). That pins recompute to the workflow run that produced
    this visual-review run instead of letting it re-trigger any job on the
    commit. It is defense-in-depth, not an identity proof — a caller who forges
    a self-consistent metadata set can still reach sibling jobs of that run.
    """
    if not check_run_id.isdigit():
        return False, "Invalid check run ID"

    repo = run.repo
    if not repo.repo_full_name:
        return False, "Repo has no GitHub full name configured"

    expected_run_id = (run.metadata or {}).get("github_run_id")
    if not expected_run_id:
        return False, "Workflow run ID not recorded for this run"

    # `${{ job.check_run_id }}` doubles as the Actions job ID, so the jobs API
    # gives us head_sha and the owning workflow run (run_id) in one call.
    try:
        job_response = _github_api_request(
            "GET",
            repo,
            f"actions/jobs/{check_run_id}",
            timeout=10,
        )
    except Exception:
        return False, "Failed to verify CI job ownership"

    if job_response.status_code != 200:
        return False, f"Could not fetch CI job details (status {job_response.status_code})"

    try:
        job_data = job_response.json()
    except Exception:
        return False, "Failed to parse CI job response"

    if job_data.get("head_sha") != run.commit_sha:
        logger.warning(
            "visual_review.ci_rerun_sha_mismatch",
            run_id=str(run.id),
            check_run_id=check_run_id,
            expected_sha=run.commit_sha,
            actual_sha=job_data.get("head_sha"),
        )
        return False, "Check run does not belong to this commit"

    if str(job_data.get("run_id")) != str(expected_run_id):
        logger.warning(
            "visual_review.ci_rerun_workflow_mismatch",
            run_id=str(run.id),
            check_run_id=check_run_id,
            expected_workflow_run=str(expected_run_id),
            actual_workflow_run=str(job_data.get("run_id")),
        )
        return False, "CI job does not belong to this run's workflow"

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
        installation_id=github.github_installation_id,
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
    response = github_request(
        method, url, access_token=access_token, installation_id=github.github_installation_id, **kwargs
    )

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
            response = github_request(
                method, url, access_token=access_token, installation_id=github.github_installation_id, **kwargs
            )

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
        installation_id=github.github_installation_id,
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
        installation_id=github.github_installation_id,
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

    Partial runs (is_partial, client-supplied) suppress removed-baseline
    detection on PR branches, so they must not be able to satisfy the gating
    status context that branch protection evaluates. Branch protection keys off
    the (context, state) pair, not the human-facing description, so a partial
    run is posted to a separate "PostHog Visual Review / {run_type} (partial)"
    context rather than the gating "PostHog Visual Review / {run_type}" one.
    A subset run therefore can never turn the gated context green; a reviewer
    must require the partial context explicitly to gate on partial runs. The
    description is also annotated so the disclosure is visible to humans.
    """
    if not repo.repo_full_name:
        return

    from .github import github_request

    context = f"PostHog Visual Review / {run.run_type}"
    # Tracking-only (observe) and partial runs must never satisfy the gating context that
    # branch protection evaluates. Both purpose and is_partial are client-supplied, so an
    # observe run posted to the gating context could green a PR head SHA's required check
    # without review. Route them to a distinct, non-gating context instead.
    if run.purpose == RunPurpose.OBSERVE:
        context = f"{context} (tracking)"
    elif run.is_partial:
        context = f"{context} (partial)"
        description = f"{description} (partial run)"

    try:
        github = get_github_integration_for_repo(repo)
        if github.access_token_expired():
            github.refresh_access_token()
    except Exception:
        logger.debug("visual_review.status_check_skipped", run_id=str(run.id), reason="no_github_integration")
        return

    access_token = github.get_access_token()
    target_url = _run_url(run, repo)

    try:
        response = github_request(
            "POST",
            f"https://api.github.com/repos/{repo.repo_full_name}/statuses/{run.commit_sha}",
            access_token=access_token,
            installation_id=github.github_installation_id,
            json={
                "state": state,
                "description": description[:140],
                "context": context,
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


def _get_coauthor_trailer(user_id: int, installation_id: str) -> str | None:
    """Return a `Co-authored-by` trailer for the approver, if they have a personal
    GitHub integration for the same installation. Returns None when no match exists.
    """
    from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

    user_integration = UserIntegration.objects.filter(
        user_id=user_id,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id=installation_id,
    ).first()
    if user_integration is None:
        return None
    return UserGitHubIntegration(user_integration).coauthor_trailer


def _commit_baseline_to_github(
    run: Run, repo: Repo, approved_snapshots: list[dict], approver_user_id: int | None = None
) -> dict:
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

    installation_id = github.integration.integration_id
    if approver_user_id is not None and isinstance(installation_id, str) and installation_id:
        trailer = _get_coauthor_trailer(approver_user_id, installation_id)
        if trailer:
            commit_message = f"{commit_message}\n\n{trailer}"

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

    run_url = _run_url(run, repo)
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


_MARKDOWN_ESCAPE_CHARS = r"\`*_{}[]()#+-.!|<>~"


def _escape_markdown(value: str) -> str:
    """Escape GitHub-flavored markdown control characters in user-supplied text."""
    return "".join(f"\\{c}" if c in _MARKDOWN_ESCAPE_CHARS else c for c in value)


@dataclass(frozen=True)
class _Approver:
    label: str
    is_github_login: bool


# A reviewer should be able to eyeball the approved snapshots straight from the PR.
# GitHub can't render base64 data URIs (its markdown sanitizer strips them) and the
# user-attachments upload path needs a browser session we don't have, so we embed
# presigned object-storage URLs and let GitHub's image proxy (camo) fetch + cache
# them. That proxy fetch can happen well after the comment is posted, so the URL
# must outlive the default hour — use the S3 SigV4 maximum.
_COMMENT_IMAGE_URL_EXPIRATION = 60 * 60 * 24 * 7  # 7 days
_COMMENT_IMAGE_WIDTH = 320
# Keep the comment readable: show the first N snapshots and link out for the rest.
_MAX_COMMENT_IMAGES = 8


def _comment_image_url(repo: Repo, artifact: Artifact | None) -> str | None:
    """Presigned URL for the full-resolution snapshot image in a PR comment.

    Serves the original artifact (not the thumbnail) so the embedded image opens at full
    resolution when clicked — GitHub constrains the rendered size via the ``<img width>``
    attribute but links the original. Returns None when the artifact is missing or object
    storage is disabled — the caller renders an empty cell in that case.
    """
    if artifact is None:
        return None
    storage = ArtifactStorage(str(repo.id))
    return storage.get_presigned_download_url(artifact.content_hash, expiration=_COMMENT_IMAGE_URL_EXPIRATION)


_TABLE_BREAKING_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _run_url(run: Run, repo: Repo) -> str:
    """Link to the run page in PostHog."""
    return f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/runs/{run.id}"


def _snapshot_url(run: Run, repo: Repo, snapshot: RunSnapshot) -> str:
    """Deep link straight to a single snapshot on the run page."""
    return f"{_run_url(run, repo)}?snapshot={snapshot.id}"


def _snapshot_name_cell(identifier: str, suffix: str = "") -> str:
    """Render a snapshot identifier as a single-line table cell (code span, pipe-safe).

    Identifiers come from the run manifest without newline validation, so collapse
    control characters (newlines, tabs, etc.) to spaces first — otherwise a
    malformed or user-controlled story name could break out of the table row and
    inject markdown/HTML into the comment. Then strip backticks and escape pipes so
    it stays inside the code span and the cell.
    """
    safe = _TABLE_BREAKING_CHARS_RE.sub(" ", identifier).replace("`", "").replace("|", "\\|")
    return f"`{safe}`{suffix}"


def _snapshot_link_cell(run: Run, repo: Repo, snapshot: RunSnapshot, suffix: str = "") -> str:
    """Snapshot identifier linked to its deep link on the run page, so a reviewer can jump
    straight to that snapshot rather than the run as a whole."""
    return f"[{_snapshot_name_cell(snapshot.identifier)}]({_snapshot_url(run, repo, snapshot)}){suffix}"


def _image_cell(url: str | None, alt: str) -> str:
    """Render an image (or an empty placeholder) for a before/after table cell.

    The image is constrained to ``_COMMENT_IMAGE_WIDTH`` so the table stays compact, but
    ``src`` points at the full-resolution original — GitHub opens that original when the
    image is clicked.
    """
    if not url:
        return "_(none)_"
    # Escape both attributes — a URL containing a quote would otherwise break out of src.
    src = html.escape(url, quote=True)
    return f'<img src="{src}" width="{_COMMENT_IMAGE_WIDTH}" alt="{html.escape(alt, quote=True)}">'


_IMAGE_TABLE_HEADER = "| Snapshot | Before | After |\n| --- | --- | --- |"


_REVIEWABLE_RESULTS = (SnapshotResult.CHANGED, SnapshotResult.NEW, SnapshotResult.REMOVED)


def _reviewable_snapshot_qs(run: Run) -> db_models.QuerySet[RunSnapshot]:
    return run.snapshots.using(READER_DB).filter(result__in=_REVIEWABLE_RESULTS)


def _postable_snapshot_qs(run: Run) -> db_models.QuerySet[RunSnapshot]:
    """Reviewable snapshots minus the ones an approval comment should not surface.

    Quarantined snapshots are suppressed by policy and tolerated ones are
    intentional known drift, so neither belongs in the comment.
    """
    return _reviewable_snapshot_qs(run).exclude(is_quarantined=True).exclude(review_state=ReviewState.TOLERATED)


def _build_snapshot_image_tables(run: Run, repo: Repo) -> str:
    """Before/after image tables for the approved snapshots.

    Changed and removed snapshots share one table (removed ones leave the *after*
    cell empty); new snapshots get their own table (empty *before* cell). Capped
    at ``_MAX_COMMENT_IMAGES`` rows total, prioritizing changed/removed diffs;
    anything beyond links back to PostHog. Returns "" when no image could be
    resolved (e.g. object storage disabled) so the comment stays text-only.
    """
    snapshots = list(
        _postable_snapshot_qs(run)
        .select_related(
            "current_artifact",
            "baseline_artifact",
        )
        .order_by("identifier")
    )
    if not snapshots:
        return ""

    # Changed/removed first — they carry a baseline diff a reviewer most needs to
    # see — then new snapshots fill whatever's left of the image budget.
    changed = [s for s in snapshots if s.result in (SnapshotResult.CHANGED, SnapshotResult.REMOVED)]
    new = [s for s in snapshots if s.result == SnapshotResult.NEW]

    total = len(changed) + len(new)
    shown_changed = changed[:_MAX_COMMENT_IMAGES]
    shown_new = new[: max(0, _MAX_COMMENT_IMAGES - len(shown_changed))]
    shown = len(shown_changed) + len(shown_new)

    any_image = False

    def cell(artifact: Artifact | None, alt: str) -> str:
        nonlocal any_image
        url = _comment_image_url(repo, artifact)
        if url:
            any_image = True
        return _image_cell(url, alt)

    def row(s: RunSnapshot, before: Artifact | None) -> str:
        suffix = " _(removed)_" if s.result == SnapshotResult.REMOVED else ""
        name = _snapshot_link_cell(run, repo, s, suffix)
        return f"| {name} | {cell(before, 'before')} | {cell(s.current_artifact, 'after')} |"

    changed_rows = [row(s, s.baseline_artifact) for s in shown_changed]
    new_rows = [row(s, None) for s in shown_new]

    if not any_image:
        return ""

    def table(heading: str, rows: list[str]) -> str:
        return "\n".join((f"**{heading}**", "", _IMAGE_TABLE_HEADER, *rows))

    sections = [table(heading, rows) for heading, rows in (("Changed", changed_rows), ("New", new_rows)) if rows]
    if shown < total:
        sections.append(f"…and {total - shown} more — [view all in PostHog]({_run_url(run, repo)}).")

    return "\n\n".join(sections)


def _build_approval_comment_body(run: Run, repo: Repo, approver: _Approver | None, add_images: bool = False) -> str:
    """Build the markdown body of the post-approval PR comment.

    Always a textual summary of what changed. When ``add_images`` is set, a
    before/after table of the approved snapshot images is appended so another
    reviewer can eyeball them without leaving the PR (omitted when no image can
    be resolved).
    """
    counts = Counter(_postable_snapshot_qs(run).values_list("result", flat=True))
    suppressed_only = not counts and _reviewable_snapshot_qs(run).exists()

    if approver is None:
        approver_text = "a reviewer"
    elif approver.is_github_login:
        approver_text = f"@{approver.label}"
    else:
        approver_text = _escape_markdown(approver.label)
    baseline_sha = run.metadata.get("baseline_commit_sha")
    sha_text = f" — baseline updated in `{baseline_sha[:7]}`" if isinstance(baseline_sha, str) and baseline_sha else ""

    summary = _format_change_counts(
        counts[SnapshotResult.CHANGED], counts[SnapshotResult.NEW], counts[SnapshotResult.REMOVED]
    )

    sections = [
        f"✅ **Visual changes approved** by {approver_text}{sha_text}.",
        f"[View this run in PostHog]({_run_url(run, repo)})",
    ]
    if summary:
        sections.append(f"{summary}.")
    elif suppressed_only:
        sections.append("All visual changes in this run were quarantined or tolerated.")
    if add_images:
        tables = _build_snapshot_image_tables(run, repo)
        if tables:
            sections.append(tables)

    return "\n\n".join(sections) + "\n"


def _resolve_approver(user_id: int | None) -> _Approver | None:
    """Resolve the approver's identity for the PR comment.

    Prefers a verified GitHub login (safe to mention with `@`); otherwise
    falls back to email local-part or first name, which the caller must
    treat as untrusted markdown.
    """
    if user_id is None:
        return None

    from posthog.models.user import User
    from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

    gh = (
        UserIntegration.objects.filter(user_id=user_id, kind=UserIntegration.IntegrationKind.GITHUB)
        .order_by("-created_at")
        .first()
    )
    if gh is not None:
        github_login = UserGitHubIntegration(gh).github_login
        if github_login:
            return _Approver(label=github_login, is_github_login=True)

    user = User.objects.filter(id=user_id).only("email", "first_name").first()
    if user is None:
        return None
    if user.email and "@" in user.email:
        return _Approver(label=user.email.split("@", 1)[0], is_github_login=False)
    if user.first_name:
        return _Approver(label=user.first_name, is_github_login=False)
    return None


def _post_approval_comment(run: Run, repo: Repo, add_images: bool = False) -> None:
    """Update the existing PR comment in place with the approved-changes summary.

    Best-effort and never raises. Skips silently when the original review-prompt
    comment was never posted (no `github_comment_id` in run.metadata) — i.e.,
    when the review wasn't initiated by a human. ``add_images`` embeds the
    before/after snapshot images in the comment when the reviewer opted in.
    """
    if not repo.enable_pr_comments:
        return

    if not repo.repo_full_name or run.pr_number is None:
        return

    if run.review_decision != ReviewDecision.HUMAN_APPROVED:
        return

    comment_id = run.metadata.get("github_comment_id")
    if not comment_id:
        return
    if isinstance(comment_id, str) and comment_id.isdigit():
        comment_id = int(comment_id)
    if not isinstance(comment_id, int):
        return

    approver = _resolve_approver(run.approved_by_id)
    body = _build_approval_comment_body(run, repo, approver, add_images=add_images)

    try:
        response = _github_api_request(
            method="PATCH",
            repo=repo,
            path=f"issues/comments/{comment_id}",
            json={"body": body},
            timeout=15,
        )
        if response.status_code == 200:
            return

        # Comment was deleted or inaccessible — fall back to creating a new one
        if response.status_code == 404:
            create_response = _github_api_request(
                method="POST",
                repo=repo,
                path=f"issues/{run.pr_number}/comments",
                json={"body": body},
                timeout=15,
            )
            if create_response.status_code == 201:
                new_comment_id = create_response.json().get("id")
                if isinstance(new_comment_id, int):
                    run.metadata["github_comment_id"] = new_comment_id
                    run.save(update_fields=["metadata"], using=WRITER_DB)
                return
            logger.warning(
                "visual_review.approval_comment_create_failed",
                run_id=str(run.id),
                pr_number=run.pr_number,
                status_code=create_response.status_code,
                response=create_response.text[:200],
            )
            return

        logger.warning(
            "visual_review.approval_comment_update_failed",
            run_id=str(run.id),
            comment_id=comment_id,
            status_code=response.status_code,
            response=response.text[:200],
        )
    except GitHubRateLimitError:
        # Bubble up so the Celery task can retry with the suggested countdown.
        raise
    except Exception:
        logger.warning(
            "visual_review.approval_comment_error",
            run_id=str(run.id),
            pr_number=run.pr_number,
            exc_info=True,
        )


def post_approval_comment_for_run(run_id: UUID, team_id: int | None = None, add_images: bool = False) -> None:
    """Public entrypoint for the Celery task to update a PR comment after approval."""
    run = (
        Run.objects.select_related("repo")
        .using(READER_DB)
        .filter(id=run_id, **({"team_id": team_id} if team_id is not None else {}))
        .first()
    )
    if run is None:
        return
    _post_approval_comment(run, run.repo, add_images=add_images)


@transaction.atomic(using=WRITER_DB)
def finalize_run(
    run_id: UUID,
    user_id: int,
    team_id: int | None = None,
    approve_all: bool = False,
    review_decision: ReviewDecision = ReviewDecision.HUMAN_APPROVED,
    commit_to_github: bool = True,
    add_images_to_comment_on_pr: bool = False,
) -> Run:
    """Finalize a fully-reviewed run: commit the approved baseline and green the gate.

    All-or-nothing by design — a run finalizes only once every changed/new snapshot is
    resolved (approved, tolerated, quarantined, or removed). The committed baseline is
    derived from DB state — exactly the snapshots with ``review_state == APPROVED``, by
    their approved hash — so a tolerated snapshot keeps its existing baseline and is
    never silently overwritten, and the commit always contains the full approved set
    regardless of how many calls it took to review them.

    With ``approve_all=True`` every still-pending changed/new snapshot is approved first
    (tolerated ones are left untouched) — the "approve everything and ship" path. Without
    it, the run must already be fully resolved or this raises RunNotFullyResolvedError.

    Set ``commit_to_github=False`` for CLI auto-approve, which writes the baseline locally
    instead of pushing it to the PR branch.

    The post-approval PR comment is always posted (subject to the existing conditions: repo
    PR comments enabled, run initiated from a GitHub review prompt). ``add_images_to_comment_on_pr``
    only controls whether the before/after snapshot images are embedded in that comment;
    defaults false so the comment stays a text summary unless the reviewer opts in.
    """
    run = _get_run_for_update(run_id, team_id=team_id)
    repo = run.repo

    if run.purpose == RunPurpose.OBSERVE:
        raise ValueError("Observational runs cannot be approved")

    # Idempotent: a finalized run already committed and posted status — don't redo the work
    # (a second commit, status, and approval comment) on a repeat call.
    if run.approved:
        return run

    if run.status != RunStatus.COMPLETED:
        raise ValueError(f"Run must be completed before approval (current status: {run.status})")

    if is_run_stale(run):
        raise StaleRunError("This run has been superseded by a newer run. Approve the latest run instead.")

    # Re-evaluate quarantine so resolution accounting reflects the current policy.
    _stamp_quarantine(run)
    now = timezone.now()

    actionable = [
        s
        for s in run.snapshots.using(WRITER_DB).all()
        if s.result in (SnapshotResult.CHANGED, SnapshotResult.NEW) and not s.is_quarantined
    ]

    if approve_all:
        pending = [s for s in actionable if s.review_state not in (ReviewState.APPROVED, ReviewState.TOLERATED)]
        _validate_approval(run, {s.identifier: s.current_hash for s in pending})
        for snapshot in pending:
            snapshot.review_state = ReviewState.APPROVED
            snapshot.reviewed_at = now
            snapshot.reviewed_by_id = user_id
            snapshot.approved_hash = snapshot.current_hash
            snapshot.save(update_fields=["review_state", "reviewed_at", "reviewed_by_id", "approved_hash"])

    # All-or-nothing: refuse to commit while any actionable snapshot is still unreviewed.
    unresolved = [
        s.identifier for s in actionable if s.review_state not in (ReviewState.APPROVED, ReviewState.TOLERATED)
    ]
    if unresolved:
        raise RunNotFullyResolvedError(
            f"Cannot finalize: {len(unresolved)} snapshot(s) still need review — approve or tolerate them first: "
            f"{', '.join(sorted(unresolved)[:10])}"
        )

    # Commit set is derived from DB state, not a caller-supplied list, so it always reflects
    # the full approved set however many calls reviewed it.
    approved_updates = _approved_baseline_updates(actionable)
    has_removed = run.snapshots.using(WRITER_DB).filter(result=SnapshotResult.REMOVED).exists()

    # Commit first — before DB writes — so a GitHub failure aborts cleanly. Removed snapshots
    # also need a commit, to prune them from the baseline, even when nothing was approved.
    if commit_to_github and (approved_updates or has_removed) and run.pr_number and repo.repo_full_name:
        _commit_baseline_to_github(run, repo, approved_updates, approver_user_id=user_id)

    # Removed snapshots are pruned from the baseline on commit; mark them approved for cleanup.
    run.snapshots.filter(result=SnapshotResult.REMOVED).update(
        review_state=ReviewState.APPROVED,
        reviewed_at=now,
        reviewed_by_id=user_id,
    )

    run.approved = True
    run.review_decision = review_decision
    run.approved_at = now
    run.approved_by_id = user_id
    run.save(update_fields=["approved", "review_decision", "approved_at", "approved_by_id"])

    if commit_to_github:
        _post_commit_status(run, repo, "success", "Visual changes approved")

    if commit_to_github and review_decision == ReviewDecision.HUMAN_APPROVED:
        from .tasks.tasks import post_approval_comment

        run_id_str = str(run.id)
        run_team_id = run.team_id
        add_images = add_images_to_comment_on_pr
        transaction.on_commit(
            lambda: post_approval_comment.delay(run_team_id, run_id_str, add_images),
            using=WRITER_DB,
        )

    return run


def build_signed_baseline(run_id: UUID, team_id: int | None = None) -> str:
    """Build the signed baseline YAML for a finalized run, without committing it.

    For callers that commit the baseline themselves (the CLI's auto-approve, which writes
    the file and commits via git rather than the GitHub App). Mirrors the committed set:
    the current baseline merged with the approved changed/new hashes, removed entries pruned.
    """
    run = get_run_with_snapshots(run_id, team_id=team_id)
    repo = run.repo

    baseline_paths = repo.baseline_file_paths or {}
    baseline_path = baseline_paths.get(run.run_type) or baseline_paths.get("default", ".snapshots.yml")

    github = get_github_integration_for_repo(repo)
    if github.access_token_expired():
        github.refresh_access_token()
    current_baselines, _file_sha = _fetch_baseline_file(github, repo.repo_full_name, baseline_path, run.branch)

    snapshots = list(run.snapshots.all())
    for s in snapshots:
        if s.result == SnapshotResult.REMOVED:
            current_baselines.pop(s.identifier, None)

    return _build_snapshots_yaml(
        repo, current_baselines=current_baselines, updates=_approved_baseline_updates(snapshots)
    )


@transaction.atomic(using=WRITER_DB)
def approve_snapshots(run_id: UUID, user_id: int, approved_snapshots: list[dict], team_id: int | None = None) -> Run:
    """Approve specific snapshots within a run (DB only, no GitHub commit).

    Used for per-snapshot "Accept change" in the UI. Does not finalize
    the run — that happens via finalize_run.
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
           rs.baseline_artifact_id,
           LAG(rs.baseline_artifact_id) OVER (ORDER BY r.created_at) AS prev_baseline_id,
           r.created_at
    FROM visual_review_runsnapshot rs
    JOIN visual_review_run r ON r.id = rs.run_id
    WHERE r.repo_id = %s
      AND r.run_type = %s
      AND r.branch = ANY(%s)
      AND r.status = 'completed'
      AND rs.identifier = %s
)
SELECT id
FROM ordered
WHERE prev_baseline_id IS DISTINCT FROM baseline_artifact_id
ORDER BY created_at DESC
"""


def get_snapshot_history(repo_id: UUID, identifier: str, run_type: str) -> list[RunSnapshot]:
    """Baseline timeline for a snapshot identifier on the default branch.

    Returns one entry per *baseline transition* — every time the committed
    `.snapshots.yml` baseline actually moved. LAG-on-`baseline_artifact_id`
    (over ASC ordering) keeps the FIRST run of each baseline period, so the
    user sees the inception event plus every change since.

    Why LAG on `baseline_artifact_id` and not `current_artifact_id`:
      - `current_artifact_id` is the bytes captured by THIS run. Pixel jitter
        and tolerated drift produce different content_hash → different Artifact
        rows even though the *baseline* didn't move. Keying on current_ caused
        a prod regression (252 fake history events on a single tolerated-drift
        story) because the artifact alternated between near-identical hashes
        the matcher kept absorbing. LAG-on-current-with-result-filter (the
        prior fix) hid those false events but also hid genuine first-appearance
        rows whose `result=unchanged` against an existing YAML baseline.
      - `baseline_artifact_id` reflects the YAML state at run time. It only
        changes when a baseline-update PR merges. Pixel jitter and tolerated
        drift leave it untouched, so LAG dedup naturally collapses noise while
        catching every real baseline flip — without needing a `result` filter.

    DB-level filters:
      - branch ∈ master/main, run_type, repo: scope to default-branch runs of
        this kind
      - status=completed: drop pre-classification rows where the baseline FK
        hasn't been hydrated yet (pending/processing leave NULL baseline_artifact)
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
      - 1 query for the universe runs (one row per run_type, indexed)
      - 1 query for the universe rows (with thumbnail + artifact prefetch)
      - 2 grouped queries for tolerate counts (30d + 90d)
      - 1 grouped query for active quarantines
      - 1 grouped query for lifetime baseline-flip count
      - 2 queries for the recent-drift average (resolve last-N runs, aggregate)
      - 3 cheap aggregate queries for totals
    """
    from datetime import timedelta

    from .facade.contracts import BASELINE_DRIFT_RECENT_RUN_COUNT, BASELINE_OVERVIEW_MAX_ENTRIES

    now = timezone.now()

    # 1. Find the latest *completed* run on the default branch per (repo,
    # branch, run_type). Filtering on `superseded_by IS NULL` looks tempting
    # but is wrong here: a freshly started PENDING/PROCESSING master run is
    # un-superseded yet has zero (or sparse) RunSnapshots ingested, and would
    # collapse the universe to whatever it has loaded so far. `status=completed`
    # makes the universe fall through to the most recent fully-ingested run.
    universe_runs = list(
        Run.objects.filter(
            repo_id=repo_id,
            branch__in=_DEFAULT_BRANCHES,
            status=RunStatus.COMPLETED,
        )
        .order_by("repo_id", "branch", "run_type", "-created_at")
        .distinct("repo_id", "branch", "run_type")
        .only("id", "run_type", "completed_at", "created_at")
    )
    universe_run_ids = [r.id for r in universe_runs]
    if not universe_run_ids:
        return _BaselineOverviewRaw(
            entries=[],
            tolerate_30d_by_id={},
            tolerate_90d_by_id={},
            active_quarantines_by_key={},
            change_count_by_key={},
            recent_drift_by_key={},
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
    # Scope to HUMAN/AGENT reasons only — AUTO_THRESHOLD rows are auto-minted
    # by the diff pipeline as a tolerated-hash cache for sub-threshold pixel
    # jitter and don't represent a deliberate "we accept this drift" decision.
    # Including them inflated the "Tolerated drift" tile with rendering noise.
    intentional_tolerate_reasons = (ToleratedReason.HUMAN, ToleratedReason.AGENT)
    tolerate_30d_by_id: dict[str, int] = {}
    tolerate_90d_by_id: dict[str, int] = {}
    if universe_identifiers:
        tol_30d_cutoff = now - timedelta(days=30)
        tol_90d_cutoff = now - timedelta(days=90)
        for identifier, count in (
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=universe_identifiers,
                reason__in=intentional_tolerate_reasons,
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
                reason__in=intentional_tolerate_reasons,
                created_at__gte=tol_90d_cutoff,
            )
            .values_list("identifier")
            .annotate(c=Count("id"))
            .values_list("identifier", "c")
        ):
            tolerate_90d_by_id[identifier] = count

    # 3b. Active quarantines for this repo, scoped to the universe identifiers
    # AND the run_types they live on (quarantine is per (repo, run_type, id)).
    # We hydrate the full row (not just identity) so the overview can render
    # reason / expiry / who / source-run inline without a per-card fetch.
    # `select_related("source_run")` is a single JOIN, capped by
    # `BASELINE_OVERVIEW_MAX_ENTRIES`. `Run.metadata` (JSONField) and
    # `Run.error_message` (TextField) can be large and aren't needed by the
    # summary — defer them to keep the response light.
    active_quarantines_by_key: dict[tuple[str, str], QuarantinedIdentifier] = {}
    if universe_identifiers:
        for q in (
            QuarantinedIdentifier.objects.filter(
                repo_id=repo_id,
                identifier__in=universe_identifiers,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .select_related("source_run")
            .defer("source_run__metadata", "source_run__error_message")
            .order_by("-created_at")
        ):
            key = (q.run_type, q.identifier)
            # Multiple active rows for the same key shouldn't happen — create
            # auto-supersedes prior — but if it does, keep the latest (sorted
            # above) and ignore the rest.
            if key not in active_quarantines_by_key:
                active_quarantines_by_key[key] = q

    # 3c. Per-baseline stability signals: a lifetime baseline-flip count and a
    # smoothed recent-drift average. Replaces a daily-bucket sparkline that
    # had to scan millions of RunSnapshot rows on every request (~7s, OOMed on
    # the web pod for repos with thousands of identifiers — see git history).
    # Both queries here are scoped tightly enough to finish in tens of ms:
    #
    #   change_count_by_key: COUNT(*) WHERE result IN ('changed','removed')
    #     across all completed master/main runs ever. Real baseline flips on
    #     master leave a CHANGED/REMOVED row in the run that introduced them
    #     (subsequent runs see UNCHANGED against the new YAML baseline), so
    #     this count IS the number of times the YAML moved. Postgres uses
    #     the `snapshot_run_result` index on (run_id, result) to bitmap-scan
    #     straight to the rare event rows (~1k of millions). No window
    #     function, no per-row LAG comparison.
    #
    #   recent_drift_by_key: AVG(diff_percentage) over the last 10 master/
    #     main completed runs per (run_type). Bounded by run count, not by
    #     time window — caps the scanned set regardless of CI cadence. We
    #     resolve the run IDs first (sub-ms) and aggregate via PK-indexed
    #     run_id__in, otherwise the planner inlines a CTE that produces a
    #     ROW_NUMBER plan over the full RunSnapshot table.
    change_count_by_key: dict[tuple[str, str], int] = {}
    recent_drift_by_key: dict[tuple[str, str], float] = {}
    if universe_identifiers:
        for identifier, run_type, c in (
            RunSnapshot.objects.filter(
                run__repo_id=repo_id,
                run__branch__in=_DEFAULT_BRANCHES,
                run__status=RunStatus.COMPLETED,
                result__in=(SnapshotResult.CHANGED, SnapshotResult.REMOVED),
            )
            .values("identifier", "run__run_type")
            .annotate(c=Count("id"))
            .values_list("identifier", "run__run_type", "c")
        ):
            change_count_by_key[(run_type, identifier)] = c

        # Top-N per run_type via window function. There's no pure-ORM
        # equivalent: Postgres doesn't allow filtering on a window result,
        # and a per-run_type loop balloons to thousands of queries on repos
        # where each Storybook story registers as its own run_type
        # (benchmarked: 4ms raw vs 5.6s loop on a 30k-run repo with 2154
        # run_types). The query is parameterized — every dynamic value
        # passes through %s binding, no string concatenation, table name
        # comes from the model. nosemgrep is required because the rule
        # blanket-flags any .raw() use.
        recent_run_sql = f"""
            SELECT id, run_type FROM (
                SELECT id, run_type,
                       ROW_NUMBER() OVER (PARTITION BY run_type ORDER BY created_at DESC) AS rn
                FROM {Run._meta.db_table}
                WHERE repo_id = %s AND branch = ANY(%s) AND status = %s
            ) ranked WHERE rn <= %s
        """  # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql
        recent_run_ids = list(
            Run.objects.raw(  # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql
                recent_run_sql,
                [str(repo_id), list(_DEFAULT_BRANCHES), RunStatus.COMPLETED, BASELINE_DRIFT_RECENT_RUN_COUNT],
            )
        )
        if recent_run_ids:
            for identifier, run_type, drift_avg in (
                RunSnapshot.objects.filter(run_id__in=[r.id for r in recent_run_ids])
                .values("identifier", "run__run_type")
                .annotate(drift_avg=Avg("diff_percentage", filter=Q(diff_percentage__gt=0)))
                .values_list("identifier", "run__run_type", "drift_avg")
            ):
                if drift_avg is not None:
                    recent_drift_by_key[(run_type, identifier)] = drift_avg

    # 4. Totals computed across the *full* universe (not the truncated slice)
    # so the stat row stays correct when the entries are clipped.
    if truncated:
        # Re-issue a small COUNT-only query for accurate totals across the
        # universe; we already have the truncated list in memory.
        totals_all = total_universe
    else:
        totals_all = len(universe)

    # Recently / frequently tolerated — counts of distinct identifiers with
    # ≥1 (or ≥3) intentional tolerations in the rolling window. Scope across
    # the *full* universe so the stat row stays correct under truncation, and
    # match the per-entry counts above by excluding AUTO_THRESHOLD.
    recent_cutoff = now - timedelta(days=30)
    frequent_cutoff = now - timedelta(days=90)
    recent_ids: set[str] = set()
    frequent_ids: set[str] = set()
    if full_universe_identifiers:
        recent_ids = set(
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=full_universe_identifiers,
                reason__in=intentional_tolerate_reasons,
                created_at__gte=recent_cutoff,
            )
            .values_list("identifier", flat=True)
            .distinct()
        )
        frequent_grouped = (
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=full_universe_identifiers,
                reason__in=intentional_tolerate_reasons,
                created_at__gte=frequent_cutoff,
            )
            .values("identifier")
            .annotate(c=Count("id"))
            .filter(c__gte=3)
            .values_list("identifier", flat=True)
        )
        frequent_ids = set(frequent_grouped)

    # `active_quarantines_by_key` was built from the truncated set above (per-entry
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
        quarantined_id_count = len({identifier for _, identifier in active_quarantines_by_key})

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

    return _BaselineOverviewRaw(
        entries=universe,
        tolerate_30d_by_id=tolerate_30d_by_id,
        tolerate_90d_by_id=tolerate_90d_by_id,
        active_quarantines_by_key=active_quarantines_by_key,
        change_count_by_key=change_count_by_key,
        recent_drift_by_key=recent_drift_by_key,
        totals_all=totals_all,
        totals_recent=len(recent_ids),
        totals_frequent=len(frequent_ids),
        totals_quarantined=quarantined_id_count,
        by_run_type=by_run_type,
        truncated=truncated,
        generated_at=now,
    )


@dataclass
class _BaselineOverviewRaw:
    """Internal raw shape — the facade layer reshapes this into the public DTOs.

    Kept private to logic.py so that contract changes don't ripple through here.
    """

    entries: list[RunSnapshot]
    tolerate_30d_by_id: dict[str, int]
    tolerate_90d_by_id: dict[str, int]
    # Latest active QuarantinedIdentifier (with `source_run` preloaded) for each
    # `(run_type, identifier)` in the universe — lets the facade build the rich
    # quarantine summary embedded on each BaselineEntry. Membership doubles as
    # the "is_quarantined" signal — no separate set needed.
    active_quarantines_by_key: dict[tuple[str, str], QuarantinedIdentifier]
    # Stability signals keyed by `(run_type, identifier)` because the same
    # identifier in different run types is a different baseline; merging would
    # bleed storybook stability into playwright stability.
    change_count_by_key: dict[tuple[str, str], int]
    recent_drift_by_key: dict[tuple[str, str], float]
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

    # Explicit team_id in the lookup (not just defaults) so the IDOR audit
    # rule sees the scope; ProductTeamManager also auto-filters by canonical
    # team — both belt and suspenders.
    tolerated, _ = ToleratedHash.objects.get_or_create(
        team_id=team_id,
        repo_id=run.repo_id,
        identifier=snapshot.identifier,
        baseline_hash=snapshot.baseline_hash,
        alternate_hash=snapshot.current_hash,
        defaults={
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
    qs = (
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=repo_id, team_id=team_id)
        # Preload `source_run` so the facade can render the "what was wrong"
        # link without an extra fetch per row. `Run.metadata` (JSONField) and
        # `Run.error_message` (TextField) can be large and aren't needed for
        # the summary — defer to keep response payloads tight.
        .select_related("source_run")
        .defer("source_run__metadata", "source_run__error_message")
    )
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
    source_run_id: UUID | None = None,
) -> QuarantinedIdentifier:
    get_repo(repo_id, team_id)  # raises RepoNotFoundError if repo not owned by team
    now = timezone.now()
    # Resolve the source run inside the team scope so a malicious caller can't
    # attach a quarantine to an unrelated run. Silently drop on mismatch — the
    # quarantine itself still wins; we just lose the "what was wrong" pointer.
    # We fetch (not just .exists()) so the facade can serialize source_run
    # without a lazy-load on the freshly-created row.
    source_run: Run | None = None
    if source_run_id is not None:
        source_run = Run.objects.using(WRITER_DB).filter(id=source_run_id, repo_id=repo_id, team_id=team_id).first()
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
        source_run=source_run,
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
    ssim_score: float,
    change_kind: ChangeKind,
    diff_metadata: DiffMetadata,
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
    snapshot.ssim_score = ssim_score
    snapshot.change_kind = change_kind.value
    # The Pydantic dump is the only legal write path into this column; reads
    # go through DiffMetadata.model_validate. Storage is JSONB; the schema
    # lives in diff_metadata.py.
    snapshot.diff_metadata = diff_metadata.model_dump(mode="json")
    snapshot.save(
        update_fields=[
            "diff_artifact",
            "diff_percentage",
            "diff_pixel_count",
            "ssim_score",
            "change_kind",
            "diff_metadata",
        ]
    )
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
