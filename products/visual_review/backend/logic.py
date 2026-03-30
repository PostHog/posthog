"""
Business logic for visual_review.

ORM queries, validation, calculations, business rules.
Called by api/api.py facade. Do not call from outside this module.
"""

from uuid import UUID

from django.conf import settings
from django.db import (
    models as db_models,
    transaction,
)
from django.db.models import Count, F, Q
from django.utils import timezone

import structlog

from .facade.enums import ReviewDecision, ReviewState, RunPurpose, RunStatus, SnapshotResult
from .models import Artifact, Repo, Run, RunSnapshot
from .signing import sign_snapshot_hash, verify_signed_hash
from .storage import ArtifactStorage

logger = structlog.get_logger(__name__)

# Derive the writer alias from the app label — must match db_routing.yaml.
# Falls back to "default" when the product database isn't configured.
_APP_LABEL = "visual_review"
_WRITER_ALIAS = f"{_APP_LABEL}_db_writer"
WRITER_DB = _WRITER_ALIAS if _WRITER_ALIAS in settings.DATABASES else "default"


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
) -> Repo:
    repo = get_repo(repo_id, team_id)
    if baseline_file_paths is not None:
        repo.baseline_file_paths = baseline_file_paths
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
    "processing": Q(status__in=[RunStatus.PENDING, RunStatus.PROCESSING]) & _CURRENT,
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


@transaction.atomic(using=WRITER_DB)
def create_run(
    repo_id: UUID,
    team_id: int,
    run_type: str,
    commit_sha: str,
    branch: str,
    pr_number: int | None,
    snapshots: list[dict],
    baseline_hashes: dict[str, str],
    unchanged_count: int = 0,
    removed_identifiers: list[str] | None = None,
    purpose: str = RunPurpose.REVIEW,
    metadata: dict | None = None,
) -> tuple[Run, list[dict]]:
    """
    Create a new run with its snapshots.

    Returns the run and list of upload targets for missing artifacts.
    Each upload target has: content_hash, url, fields
    """
    repo = get_repo(repo_id, team_id)

    # Verify HMAC signatures on baseline hashes before trusting them.
    # Unsigned or invalid hashes are silently dropped (treated as no baseline → NEW).
    verified_baselines = _verify_baseline_hashes(repo, baseline_hashes)

    # Supersede ALL old runs before inserting the new one. The unique
    # partial index on (repo, branch, run_type) WHERE superseded_by IS NULL
    # requires the slot to be free before the insert. A new CI push always
    # replaces the previous run — approved and clean runs still show up in
    # their respective UI filters via REVIEW_STATE_FILTERS.
    supersede_filter = Run.objects.filter(
        repo_id=repo_id,
        branch=branch,
        run_type=run_type,
        superseded_by__isnull=True,
    )
    # Collect IDs before mutating, then self-reference to clear the slot
    superseded_ids = list(supersede_filter.values_list("id", flat=True))
    if superseded_ids:
        from django.db.models import F

        Run.objects.filter(id__in=superseded_ids, team_id=team_id).update(superseded_by=F("id"))

    removed = removed_identifiers or []
    total = len(snapshots) + unchanged_count

    run = Run.objects.create(
        repo=repo,
        team_id=repo.team_id,
        run_type=run_type,
        commit_sha=commit_sha,
        branch=branch,
        pr_number=pr_number,
        purpose=purpose,
        total_snapshots=total,
        metadata=metadata or {},
    )

    # Fix up the sentinel pointers to reference the actual new run
    if superseded_ids:
        Run.objects.filter(id__in=superseded_ids, team_id=team_id).update(superseded_by=run)

    _added, uploads = _register_snapshots(run, repo, snapshots, verified_baselines, removed)
    _update_run_counts(run)

    transaction.on_commit(
        lambda: _post_commit_status(run, repo, "pending", "Visual review in progress"), using=WRITER_DB
    )

    return run, uploads


def _register_snapshots(
    run: Run,
    repo: Repo,
    snapshots: list[dict],
    verified_baselines: dict[str, str],
    removed: list[str] | None = None,
) -> tuple[int, list[dict]]:
    """Register snapshots on a run and return upload targets.

    Reused by create_run (full/delta manifest) and add_snapshots_to_run (shard flow).
    Idempotent per (run, identifier) via unique constraint — safe for shard retries.
    """
    repo_id = repo.id
    all_hashes: set[str] = set()
    added_count = 0

    for snap in snapshots:
        identifier = snap["identifier"]
        current_hash = snap["content_hash"]
        baseline_hash = verified_baselines.get(identifier)

        all_hashes.add(current_hash)
        if baseline_hash:
            all_hashes.add(baseline_hash)

        current_artifact = get_artifact(repo_id, current_hash)
        baseline_artifact = get_artifact(repo_id, baseline_hash) if baseline_hash else None

        if baseline_hash is None:
            result = SnapshotResult.NEW
        elif current_hash == baseline_hash:
            result = SnapshotResult.UNCHANGED
        else:
            result = SnapshotResult.CHANGED

        _snapshot, created = RunSnapshot.objects.get_or_create(
            run=run,
            team_id=repo.team_id,
            identifier=identifier,
            defaults={
                "current_hash": current_hash,
                "baseline_hash": baseline_hash or "",
                "current_artifact": current_artifact,
                "baseline_artifact": baseline_artifact,
                "result": result,
                "current_width": snap.get("width"),
                "current_height": snap.get("height"),
                "metadata": snap.get("metadata") or {},
            },
        )
        if created:
            added_count += 1

    for identifier in removed or []:
        baseline_hash = verified_baselines.get(identifier)
        baseline_artifact = get_artifact(repo_id, baseline_hash) if baseline_hash else None
        _snapshot, created = RunSnapshot.objects.get_or_create(
            run=run,
            team_id=repo.team_id,
            identifier=identifier,
            defaults={
                "current_hash": "",
                "baseline_hash": baseline_hash or "",
                "baseline_artifact": baseline_artifact,
                "result": SnapshotResult.REMOVED,
                "metadata": {},
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


def _update_run_counts(run: Run) -> None:
    """Recalculate result counts from RunSnapshot rows."""
    counts = run.snapshots.values("result").annotate(n=Count("id"))
    by_result = {row["result"]: row["n"] for row in counts}

    run.changed_count = by_result.get(SnapshotResult.CHANGED, 0)
    run.new_count = by_result.get(SnapshotResult.NEW, 0)
    run.removed_count = by_result.get(SnapshotResult.REMOVED, 0)
    run.save(update_fields=["changed_count", "new_count", "removed_count"])


@transaction.atomic(using=WRITER_DB)
def add_snapshots_to_run(
    run_id: UUID,
    team_id: int,
    snapshots: list[dict],
    baseline_hashes: dict[str, str],
    unchanged_count: int = 0,
) -> tuple[int, list[dict]]:
    """Add a batch of snapshots to an existing run (shard-based flow).

    Returns (added_count, upload_targets). Idempotent — safe for retries.
    """
    run = get_run(run_id, team_id=team_id)

    if run.status != RunStatus.PENDING:
        raise ValueError(f"Can only add snapshots to pending runs (current status: {run.status})")

    repo = run.repo
    verified_baselines = _verify_baseline_hashes(repo, baseline_hashes)

    added, uploads = _register_snapshots(run, repo, snapshots, verified_baselines)

    # Atomically increment total (safe for concurrent shards)
    Run.objects.filter(id=run_id, team_id=team_id).update(
        total_snapshots=F("total_snapshots") + added + unchanged_count
    )
    _update_run_counts(run)

    return added, uploads


def mark_run_processing(run_id: UUID) -> Run:
    run = get_run(run_id)
    run.status = RunStatus.PROCESSING
    run.save(update_fields=["status"])
    return run


def complete_run(
    run_id: UUID,
    removed_identifiers: list[str] | None = None,
    unchanged_count: int = 0,
    baseline_hashes: dict[str, str] | None = None,
) -> Run:
    """
    Complete a run: verify uploads, create artifacts, trigger diff processing.

    In shard flow, this is where removed snapshots are detected and final
    counts are reconciled — shards only know about their own subset.

    1. Registers removed identifiers (shard flow)
    2. Verifies all expected uploads exist in S3
    3. Creates Artifact records for verified uploads
    4. Links artifacts to snapshots
    5. Triggers async diff processing (only if there are changes to diff)

    Idempotent: returns immediately if already processing or completed.
    """
    run = get_run(run_id)
    if run.status in (RunStatus.PROCESSING, RunStatus.COMPLETED):
        return run

    # Shard flow: register removed identifiers at complete time
    removed = removed_identifiers or []
    if removed:
        repo = run.repo
        verified = _verify_baseline_hashes(repo, baseline_hashes or {})
        for identifier in removed:
            baseline_hash = verified.get(identifier)
            baseline_artifact = get_artifact(repo.id, baseline_hash) if baseline_hash else None
            RunSnapshot.objects.get_or_create(
                run=run,
                team_id=repo.team_id,
                identifier=identifier,
                defaults={
                    "current_hash": "",
                    "baseline_hash": baseline_hash or "",
                    "baseline_artifact": baseline_artifact,
                    "result": SnapshotResult.REMOVED,
                    "metadata": {},
                },
            )

    # Reconcile final counts (includes shards' unchanged + any removals)
    if unchanged_count or removed:
        Run.objects.filter(id=run_id, team_id=run.repo.team_id).update(
            total_snapshots=F("total_snapshots") + unchanged_count,
        )
        _update_run_counts(run)

    verify_uploads_and_create_artifacts(run_id)

    run = get_run(run_id)

    # Optimization: if no changes, skip diff processing entirely
    if run.changed_count == 0 and run.new_count == 0:
        mark_run_completed(run_id)
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


def mark_run_completed(run_id: UUID, error_message: str = "") -> Run:
    run = get_run_with_snapshots(run_id)

    snapshots = list(run.snapshots.all())

    changed_count = sum(1 for s in snapshots if s.result == SnapshotResult.CHANGED)
    new_count = sum(1 for s in snapshots if s.result == SnapshotResult.NEW)
    removed_count = sum(1 for s in snapshots if s.result == SnapshotResult.REMOVED)

    run.status = RunStatus.FAILED if error_message else RunStatus.COMPLETED
    run.error_message = error_message
    run.completed_at = timezone.now()
    run.changed_count = changed_count
    run.new_count = new_count
    run.removed_count = removed_count
    run.save(update_fields=["status", "error_message", "completed_at", "changed_count", "new_count", "removed_count"])

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
        _post_commit_status(run, repo, "success", f"Visual changes detected: {', '.join(parts)}")
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

    updates = [{"identifier": s["identifier"], "new_hash": s["new_hash"]} for s in approved_snapshots]
    new_content = _build_snapshots_yaml(repo, current_baselines, updates)

    # Use GitHubIntegration.update_file() - it expects just the repo name, not full path
    # The org comes from github.organization()
    repo_name = repo.repo_full_name.split("/")[-1] if "/" in repo.repo_full_name else repo.repo_full_name

    result = github.update_file(
        repository=repo_name,
        file_path=baseline_path,
        content=new_content,
        commit_message="chore(visual): update visual baselines",
        branch=pr_info["head_ref"],
        sha=file_sha,
    )

    if not result.get("success"):
        raise GitHubCommitError(f"Failed to commit baseline: {result.get('error')}")

    return result


def auto_approve_run(run_id: UUID, user_id: int) -> tuple[Run, str]:
    """Auto-approve a completed run and return signed baseline YAML.

    Used by the CLI during the transition period to keep baselines in sync
    with jest-image-snapshot. Approves all CHANGED + NEW snapshots via the
    normal approve_run path, then builds a fresh signed YAML.

    Idempotent: if the run is already approved, rebuilds the YAML from
    the current state. If there are no changes to approve, returns the
    run as-is with a signed YAML of all current hashes.
    """
    run = get_run_with_snapshots(run_id)
    repo = run.repo

    if run.status != RunStatus.COMPLETED:
        raise ValueError(f"Run must be completed before auto-approve (current status: {run.status})")

    if is_run_stale(run):
        raise StaleRunError("This run has been superseded by a newer run.")

    # Collect snapshots that need approval (changed + new)
    needs_approval = [
        {"identifier": s.identifier, "new_hash": s.current_hash}
        for s in run.snapshots.all()
        if s.result in (SnapshotResult.CHANGED, SnapshotResult.NEW)
    ]

    if needs_approval and not run.approved:
        approve_run(
            run_id=run_id,
            user_id=user_id,
            approved_snapshots=needs_approval,
            commit_to_github=False,
        )
        # Override to AUTO_APPROVED (approve_run sets HUMAN_APPROVED)
        Run.objects.filter(id=run_id, team_id=repo.team_id).update(review_decision=ReviewDecision.AUTO_APPROVED)
        run = get_run_with_snapshots(run_id)

    snapshots = list(run.snapshots.all().order_by("identifier"))

    # Preserve existing baselines for unchanged snapshots
    baseline_updates = [
        {"identifier": s.identifier, "new_hash": s.baseline_hash}
        for s in snapshots
        if s.result == SnapshotResult.UNCHANGED and s.baseline_hash
    ]
    # Approve changed/new snapshots with their current hash
    change_updates = [
        {"identifier": s.identifier, "new_hash": s.current_hash}
        for s in snapshots
        if s.result in (SnapshotResult.CHANGED, SnapshotResult.NEW)
    ]

    baseline_content = _build_snapshots_yaml(repo, current_baselines={}, updates=baseline_updates + change_updates)
    return run, baseline_content


@transaction.atomic(using=WRITER_DB)
def approve_run(run_id: UUID, user_id: int, approved_snapshots: list[dict], commit_to_github: bool = True) -> Run:
    """
    Approve visual changes for a run.

    If commit_to_github is True and run has a PR:
    1. Validates PR SHA matches run's commit_sha
    2. Commits updated baseline to GitHub
    3. Updates baseline hashes for approved snapshots in DB
    """
    run = get_run(run_id)
    repo = run.repo

    if run.purpose == RunPurpose.OBSERVE:
        raise ValueError("Observational runs cannot be approved")

    if is_run_stale(run):
        raise StaleRunError("This run has been superseded by a newer run. Approve the latest run instead.")

    # Build lookup of identifier -> new_hash
    approvals = {s["identifier"]: s["new_hash"] for s in approved_snapshots}

    # Validate all identifiers exist in this run
    run_identifiers = set(run.snapshots.values_list("identifier", flat=True))
    unknown = set(approvals.keys()) - run_identifiers
    if unknown:
        raise ValueError(f"Unknown snapshot identifiers: {', '.join(sorted(unknown))}")

    # Validate approved hashes match snapshot current_hash (prevents baseline corruption)
    for snapshot in run.snapshots.filter(identifier__in=approvals.keys()):
        expected_hash = approvals[snapshot.identifier]
        if expected_hash != snapshot.current_hash:
            raise ValueError(
                f"Hash mismatch for {snapshot.identifier}: "
                f"approved {expected_hash[:12]} but current is {snapshot.current_hash[:12]}"
            )

    # Validate all artifacts exist before making any changes
    for identifier, new_hash in approvals.items():
        artifact = get_artifact(repo.id, new_hash)
        if not artifact:
            raise ArtifactNotFoundError(f"Artifact not found for hash {new_hash} (snapshot: {identifier})")

    # Commit to GitHub first (if enabled and PR exists)
    # Do this before DB changes so we can fail cleanly
    if commit_to_github and run.pr_number and repo.repo_full_name:
        _commit_baseline_to_github(run, repo, approved_snapshots)

    # Record approval on each snapshot without mutating result/baseline
    # This preserves the diff history while tracking what was approved
    for snapshot in run.snapshots.filter(identifier__in=approvals.keys()):
        new_hash = approvals[snapshot.identifier]
        snapshot.review_state = ReviewState.APPROVED
        snapshot.reviewed_at = timezone.now()
        snapshot.reviewed_by_id = user_id
        snapshot.approved_hash = new_hash
        snapshot.save(update_fields=["review_state", "reviewed_at", "reviewed_by_id", "approved_hash"])

    # Mark run approved
    run.approved = True
    run.review_decision = ReviewDecision.HUMAN_APPROVED
    run.approved_at = timezone.now()
    run.approved_by_id = user_id
    run.save(update_fields=["approved", "review_decision", "approved_at", "approved_by_id"])

    _post_commit_status(run, repo, "success", "Visual changes approved")

    return run


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
