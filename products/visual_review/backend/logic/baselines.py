"""Baseline resolution, signing, and committing the approved baseline back to GitHub."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings
from django.db.models import F, Q

import structlog

if TYPE_CHECKING:
    from posthog.models.integration import GitHubIntegration


from ..db import WRITER_DB
from ..facade.enums import ReviewState, SnapshotResult
from ..models import Repo, Run, RunSnapshot
from ..signing import sign_snapshot_hash, verify_signed_hash
from . import errors, github_api, run_queries

logger = structlog.get_logger(__name__)


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

    baselines_signed, _sha = github_api._fetch_baseline_file(github, repo.repo_full_name, baseline_path, ref)

    return _verify_baseline_hashes(
        repo,
        {
            identifier: entry["hash"]
            for identifier, entry in baselines_signed.items()
            if isinstance(entry, dict) and "hash" in entry
        },
    )


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
        github = github_api.get_github_integration_for_repo(repo)
    except Exception:
        logger.info("visual_review.no_github_integration", repo_id=str(repo.id))
        return False
    return branch == github_api._get_default_branch(github, repo.repo_full_name)


def _resolve_baselines(repo, run_type: str, branch: str) -> dict[str, str]:
    """Fetch baseline content hashes from GitHub for snapshot comparison.

    Returns a dict of identifier → content_hash (plain, not signed).
    Returns empty dict when no GitHub integration exists or the baseline
    file is missing (first run).
    """
    try:
        github = github_api.get_github_integration_for_repo(repo)
    except Exception:
        logger.info("visual_review.no_github_integration", repo_id=str(repo.id))
        return {}

    return _resolve_baselines_at_ref(repo, github, run_type, branch)


def _resolve_baselines_with_merge_base(
    repo: Repo,
    run_type: str,
    branch: str,
    *,
    rendered_identifiers: set[str],
    commit_sha: str | None = None,
) -> tuple[dict[str, str], int]:
    """Fetch branch baseline merged with merge-base baseline.

    The branch baseline tracks approvals. The merge-base baseline
    fills in entries that were lost during a rebase (the bot commit
    rewrites the full file, and git rebase replays it destructively).

    Branch entries win on conflict so approvals are preserved.
    On a merge-queue branch, healing is limited to identifiers this run
    rendered. An entry missing from the branch baseline whose story still
    renders is the rebase loss above. An entry missing from both is one the
    branch deleted on purpose, and restoring it only manufactures a REMOVED
    that no one on a queue branch can approve, so it reds the batch and every
    pull request sharing it until the deleting one lands.

    Ordinary branches keep healing everything, because there the REMOVED is
    the review gate: it is how a reviewer is asked to confirm that a story
    should go. The queue signal is the server-verified source PR rather than
    the branch name, which is client-supplied — matching the name alone would
    let any caller skip that gate. When verification fails the filter stays
    off, so a GitHub blip costs a red batch rather than a silent removal.

    Identifiers previously approved as REMOVED on this branch are
    tombstoned — healing would otherwise resurrect them from master
    and re-flag them as removed on every subsequent run.

    When *commit_sha* is provided the baseline is fetched at that exact
    commit rather than the branch tip. The tip moves under a concurrent
    push, and an ephemeral merge-queue branch is deleted once its batch
    resolves — a fetch by branch name then 404s, which is indistinguishable
    from "no baseline file" and reports the whole suite as new.

    Returns (merged_baseline, healed_count).
    """
    try:
        github = github_api.get_github_integration_for_repo(repo)
    except Exception:
        logger.info("visual_review.no_github_integration", repo_id=str(repo.id))
        return {}, 0

    default_branch = github_api._get_default_branch(github, repo.repo_full_name)

    # Pin the baseline to the exact commit under test so back-to-back pushes
    # don't race, and so a branch deleted mid-run still resolves.
    baseline_ref = commit_sha or branch
    branch_baseline = _resolve_baselines_at_ref(repo, github, run_type, baseline_ref)

    if branch == default_branch:
        return branch_baseline, 0

    # Compare from the same ref the baseline was read at. A deleted branch 404s
    # here, and healing would then switch off exactly when it is needed.
    merge_base_sha = github_api._get_merge_base_sha(github, repo.repo_full_name, default_branch, baseline_ref)
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

    source_pr_number = github_api._verified_merge_queue_source_pr(
        github, repo.repo_full_name, branch, head_ref=baseline_ref
    )
    tombstoned = _tombstoned_identifiers(repo, run_type, branch, source_pr_number=source_pr_number)
    on_merge_queue_branch = source_pr_number is not None
    healable_merge_base = {
        identifier: baseline_hash
        for identifier, baseline_hash in merge_base_baseline.items()
        if identifier not in tombstoned and (not on_merge_queue_branch or identifier in rendered_identifiers)
    }

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


def _tombstoned_identifiers(repo: Repo, run_type: str, branch: str, source_pr_number: int | None = None) -> set[str]:
    """Identifiers whose latest approved outcome on this branch was REMOVED.

    Healing pulls entries from merge-base back into the baseline when
    they're missing from branch. Without tombstoning, an approved
    removal keeps reappearing: the bot commit drops it from the branch
    file, but the next run's merge-base fetch re-adds it and classifies
    it REMOVED all over again.

    Uses the most recent approved decision per identifier so that a
    later re-addition (approved as NEW/CHANGED) clears the tombstone.

    ``source_pr_number`` widens the scope to that PR's runs — pass only a
    server-verified value (see ``_verified_merge_queue_source_pr``), never
    one parsed from client-supplied input alone.
    """
    from django.db.models import OuterRef, Subquery

    branch_scope = Q(run__branch=branch)
    if source_pr_number is not None:
        branch_scope |= Q(run__pr_number=source_pr_number)

    latest_approved_run = (
        RunSnapshot.objects.using(WRITER_DB)
        .filter(
            branch_scope,
            run__repo=repo,
            run__run_type=run_type,
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
            branch_scope,
            run__repo=repo,
            run__run_type=run_type,
            run__approved=True,
            review_state=ReviewState.APPROVED,
            result=SnapshotResult.REMOVED,
        )
        .annotate(latest_approved_at=Subquery(latest_approved_run))
        .filter(run__created_at=F("latest_approved_at"))
        .values_list("identifier", flat=True)
        .distinct()
    )


def _approved_baseline_updates(snapshots: Iterable[RunSnapshot]) -> list[dict]:
    """The committed-baseline update set: approved changed/new snapshots, by approved hash.

    Derived from DB state so the commit always reflects every approval regardless of how
    many calls it took. Tolerated snapshots are excluded — toleration never updates the baseline.

    Quarantine keeps a flapping hash out of the baseline, so a quarantined CHANGED snapshot is
    excluded even when approved. A quarantined NEW snapshot has no baseline entry to protect,
    and only a per-identifier approval can mark it (bulk approve skips quarantined rows), so an
    approved one is committed. Without this a story that lost its entry while quarantined could
    never get one back: lifting the quarantine fails every run until the entry lands.
    """
    return [
        {"identifier": s.identifier, "new_hash": s.approved_hash}
        for s in snapshots
        if s.review_state == ReviewState.APPROVED
        and (s.result == SnapshotResult.NEW or (s.result == SnapshotResult.CHANGED and not s.is_quarantined))
    ]


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
        raise errors.BaselineFilePathNotConfiguredError(f"No baseline file path configured for run type {run.run_type}")

    github = github_api.get_github_integration_for_repo(repo)

    if run.pr_number is None:
        raise errors.GitHubCommitError("Cannot commit to GitHub: run has no associated PR number")

    pr_info = github_api._get_pr_info(github, repo.repo_full_name, run.pr_number)

    if pr_info["head_sha"] != run.commit_sha:
        raise errors.PRSHAMismatchError(
            f"PR has newer commits. Expected {run.commit_sha}, got {pr_info['head_sha']}. "
            "Please re-run visual tests on the latest commit."
        )

    current_baselines, file_sha = github_api._fetch_baseline_file(
        github, repo.repo_full_name, baseline_path, pr_info["head_ref"]
    )

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
        raise errors.GitHubCommitError(f"Failed to commit baseline: {result.get('error')}")

    run.metadata["baseline_commit_sha"] = result.get("commit_sha")
    run.save(update_fields=["metadata"])

    return result


def build_signed_baseline(run_id: UUID, team_id: int | None = None) -> str:
    """Build the signed baseline YAML for a finalized run, without committing it.

    For callers that commit the baseline themselves (the CLI's auto-approve, which writes
    the file and commits via git rather than the GitHub App). Mirrors the committed set:
    the current baseline merged with the approved changed/new hashes, removed entries pruned.
    """
    run = run_queries.get_run_with_snapshots(run_id, team_id=team_id)
    repo = run.repo

    baseline_paths = repo.baseline_file_paths or {}
    baseline_path = baseline_paths.get(run.run_type) or baseline_paths.get("default", ".snapshots.yml")

    github = github_api.get_github_integration_for_repo(repo)
    current_baselines, _file_sha = github_api._fetch_baseline_file(
        github, repo.repo_full_name, baseline_path, run.branch
    )

    snapshots = list(run.snapshots.all())
    for s in snapshots:
        if s.result == SnapshotResult.REMOVED:
            current_baselines.pop(s.identifier, None)

    return _build_snapshots_yaml(
        repo, current_baselines=current_baselines, updates=_approved_baseline_updates(snapshots)
    )
