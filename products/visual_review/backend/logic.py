"""
Business logic for visual_review.

ORM queries, validation, calculations, business rules.
Called by api/api.py facade. Do not call from outside this module.
"""

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from .domain_types import ReviewState, RunStatus, SnapshotResult
from .models import Artifact, Project, Run, RunSnapshot
from .storage import ArtifactStorage


class ProjectNotFoundError(Exception):
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


class BaselineFilePathNotConfiguredError(Exception):
    """Project does not have a baseline file path configured for this run type."""

    pass


# --- Project Operations ---


def get_project(project_id: UUID) -> Project:
    try:
        return Project.objects.get(id=project_id)
    except Project.DoesNotExist as e:
        raise ProjectNotFoundError(f"Project {project_id} not found") from e


def list_projects_for_team(team_id: int) -> list[Project]:
    return list(Project.objects.filter(team_id=team_id).order_by("-created_at"))


def create_project(team_id: int, name: str) -> Project:
    return Project.objects.create(team_id=team_id, name=name)


def update_project(
    project_id: UUID,
    name: str | None = None,
    repo_full_name: str | None = None,
    baseline_file_paths: dict[str, str] | None = None,
) -> Project:
    project = get_project(project_id)
    if name is not None:
        project.name = name
    if repo_full_name is not None:
        project.repo_full_name = repo_full_name
    if baseline_file_paths is not None:
        project.baseline_file_paths = baseline_file_paths
    project.save()
    return project


# --- Artifact Operations ---


def get_artifact(project_id: UUID, content_hash: str) -> Artifact | None:
    return Artifact.objects.filter(project_id=project_id, content_hash=content_hash).first()


def get_or_create_artifact(
    project_id: UUID,
    content_hash: str,
    storage_path: str,
    width: int | None = None,
    height: int | None = None,
    size_bytes: int | None = None,
) -> tuple[Artifact, bool]:
    return Artifact.objects.get_or_create(
        project_id=project_id,
        content_hash=content_hash,
        defaults={
            "storage_path": storage_path,
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
        },
    )


def find_missing_hashes(project_id: UUID, hashes: list[str]) -> list[str]:
    """Return hashes that don't exist as artifacts in the project."""
    existing = set(
        Artifact.objects.filter(project_id=project_id, content_hash__in=hashes).values_list("content_hash", flat=True)
    )
    return [h for h in hashes if h not in existing]


def get_presigned_upload_url(project_id: UUID, content_hash: str) -> dict | None:
    storage = ArtifactStorage(str(project_id))
    return storage.get_presigned_upload_url(content_hash)


def get_presigned_download_url(project_id: UUID, content_hash: str) -> str | None:
    storage = ArtifactStorage(str(project_id))
    return storage.get_presigned_download_url(content_hash)


def read_artifact_bytes(project_id: UUID, content_hash: str) -> bytes | None:
    """Read artifact content from storage."""
    storage = ArtifactStorage(str(project_id))
    return storage.read(content_hash)


def write_artifact_bytes(
    project_id: UUID,
    content_hash: str,
    content: bytes,
    width: int | None = None,
    height: int | None = None,
) -> Artifact:
    """
    Write artifact content to storage and create DB record.
    Used for server-generated artifacts like diff images.
    """
    storage = ArtifactStorage(str(project_id))
    storage_path = storage.write(content_hash, content)

    artifact, _ = Artifact.objects.get_or_create(
        project_id=project_id,
        content_hash=content_hash,
        defaults={
            "storage_path": storage_path,
            "width": width,
            "height": height,
            "size_bytes": len(content),
        },
    )
    return artifact


# --- Run Operations ---


def list_runs_for_team(team_id: int) -> list[Run]:
    """List all runs for projects belonging to a team, ordered by creation date (newest first)."""
    return list(Run.objects.filter(project__team_id=team_id).select_related("project").order_by("-created_at"))


def get_run(run_id: UUID) -> Run:
    try:
        return Run.objects.select_related("project").get(id=run_id)
    except Run.DoesNotExist as e:
        raise RunNotFoundError(f"Run {run_id} not found") from e


def get_run_with_snapshots(run_id: UUID) -> Run:
    try:
        return Run.objects.prefetch_related(
            "snapshots__current_artifact",
            "snapshots__baseline_artifact",
            "snapshots__diff_artifact",
        ).get(id=run_id)
    except Run.DoesNotExist as e:
        raise RunNotFoundError(f"Run {run_id} not found") from e


@transaction.atomic
def create_run(
    project_id: UUID,
    run_type: str,
    commit_sha: str,
    branch: str,
    pr_number: int | None,
    snapshots: list[dict],
    baseline_hashes: dict[str, str],
    metadata: dict | None = None,
) -> tuple[Run, list[dict]]:
    """
    Create a new run with its snapshots.

    Returns the run and list of upload targets for missing artifacts.
    Each upload target has: content_hash, url, fields
    """
    project = get_project(project_id)

    run = Run.objects.create(
        project=project,
        run_type=run_type,
        commit_sha=commit_sha,
        branch=branch,
        pr_number=pr_number,
        total_snapshots=len(snapshots),
        metadata=metadata or {},
    )

    all_hashes: set[str] = set()
    # Store width/height from manifest for later artifact creation
    hash_metadata: dict[str, dict] = {}

    for snap in snapshots:
        identifier = snap["identifier"]
        current_hash = snap["content_hash"]
        baseline_hash = baseline_hashes.get(identifier)

        all_hashes.add(current_hash)
        hash_metadata[current_hash] = {
            "width": snap.get("width"),
            "height": snap.get("height"),
        }
        if baseline_hash:
            all_hashes.add(baseline_hash)

        # Look up existing artifacts
        current_artifact = get_artifact(project_id, current_hash)
        baseline_artifact = get_artifact(project_id, baseline_hash) if baseline_hash else None

        # Determine initial result based on baseline_hash presence, not artifact existence
        # (baseline artifact might not be uploaded yet)
        if baseline_hash is None:
            result = SnapshotResult.NEW
        elif current_hash == baseline_hash:
            result = SnapshotResult.UNCHANGED
        else:
            result = SnapshotResult.CHANGED

        RunSnapshot.objects.create(
            run=run,
            identifier=identifier,
            current_hash=current_hash,
            baseline_hash=baseline_hash or "",
            current_artifact=current_artifact,
            baseline_artifact=baseline_artifact,
            result=result,
            # Store metadata on snapshot for artifact creation during complete
            current_width=snap.get("width"),
            current_height=snap.get("height"),
            # Flexible metadata (browser, viewport, is_critical, etc.)
            metadata=snap.get("metadata") or {},
        )

    # Calculate initial summary counts from snapshot results
    # These are known at creation time based on hash comparison
    snapshots_list = list(run.snapshots.all())
    run.changed_count = sum(1 for s in snapshots_list if s.result == SnapshotResult.CHANGED)
    run.new_count = sum(1 for s in snapshots_list if s.result == SnapshotResult.NEW)
    run.removed_count = sum(1 for s in snapshots_list if s.result == SnapshotResult.REMOVED)
    run.save(update_fields=["changed_count", "new_count", "removed_count"])

    # Find missing hashes and generate upload URLs
    missing_hashes = find_missing_hashes(project_id, list(all_hashes))
    storage = ArtifactStorage(str(project_id))

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

    return run, uploads


def mark_run_processing(run_id: UUID) -> Run:
    run = get_run(run_id)
    run.status = RunStatus.PROCESSING
    run.save(update_fields=["status"])
    return run


def verify_uploads_and_create_artifacts(run_id: UUID) -> int:
    """
    Verify S3 uploads exist and create Artifact records.

    Called when run is completed. Checks S3 for each expected hash,
    creates Artifact if present, and links to snapshots.

    Returns number of artifacts created.
    """
    run = get_run_with_snapshots(run_id)
    project_id = run.project_id
    storage = ArtifactStorage(str(project_id))

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
        if get_artifact(project_id, content_hash):
            continue

        # Check if file exists in S3
        if not storage.exists(content_hash):
            continue

        # Create artifact record
        storage_path = storage._key(content_hash)
        artifact, created = get_or_create_artifact(
            project_id=project_id,
            content_hash=content_hash,
            storage_path=storage_path,
            width=metadata.get("width"),
            height=metadata.get("height"),
        )

        if created:
            created_count += 1
            link_artifact_to_snapshots(project_id, content_hash)

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

    return run


def get_github_integration_for_project(project: Project):
    """Get GitHub integration for the project's team."""
    from posthog.models.integration import GitHubIntegration, Integration

    integration = Integration.objects.filter(team_id=project.team_id, kind="github").first()

    if not integration:
        raise GitHubIntegrationNotFoundError(f"No GitHub integration found for team {project.team_id}")

    return GitHubIntegration(integration)


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


def _fetch_baseline_file(github, repo_full_name: str, file_path: str, branch: str) -> tuple[dict[str, str], str | None]:
    """
    Fetch current baseline file content from GitHub.

    Returns (snapshots dict, file SHA for update). If file doesn't exist, returns ({}, None).
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

    return parsed.get("snapshots", {}), file_sha


def _build_snapshots_yaml(current_baselines: dict[str, str], updates: list[dict]) -> str:
    """Build updated snapshots.yml content."""
    import yaml

    merged = dict(current_baselines)
    for update in updates:
        merged[update["identifier"]] = update["new_hash"]

    sorted_snapshots = dict(sorted(merged.items()))

    data = {
        "version": 1,
        "snapshots": sorted_snapshots,
    }

    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def _commit_baseline_to_github(run: Run, project: Project, approved_snapshots: list[dict]) -> dict:
    """
    Commit updated baseline file to GitHub.

    Raises:
        GitHubIntegrationNotFoundError: No GitHub integration for team
        PRSHAMismatchError: PR has newer commits than this run
        BaselineFilePathNotConfiguredError: No baseline path for run type
        GitHubCommitError: GitHub API error
    """
    baseline_paths = project.baseline_file_paths or {}
    baseline_path = baseline_paths.get(run.run_type) or baseline_paths.get("default", ".snapshots.yml")

    if not baseline_path:
        raise BaselineFilePathNotConfiguredError(f"No baseline file path configured for run type {run.run_type}")

    github = get_github_integration_for_project(project)

    if github.access_token_expired():
        github.refresh_access_token()

    pr_info = _get_pr_info(github, project.repo_full_name, run.pr_number)

    if pr_info["head_sha"] != run.commit_sha:
        raise PRSHAMismatchError(
            f"PR has newer commits. Expected {run.commit_sha}, got {pr_info['head_sha']}. "
            "Please re-run visual tests on the latest commit."
        )

    current_baselines, file_sha = _fetch_baseline_file(
        github, project.repo_full_name, baseline_path, pr_info["head_ref"]
    )

    updates = [{"identifier": s["identifier"], "new_hash": s["new_hash"]} for s in approved_snapshots]
    new_content = _build_snapshots_yaml(current_baselines, updates)

    # Use GitHubIntegration.update_file() - it expects just the repo name, not full path
    # The org comes from github.organization()
    repo_name = project.repo_full_name.split("/")[-1] if "/" in project.repo_full_name else project.repo_full_name

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


@transaction.atomic
def approve_run(run_id: UUID, user_id: int, approved_snapshots: list[dict], commit_to_github: bool = True) -> Run:
    """
    Approve visual changes for a run.

    If commit_to_github is True and run has a PR:
    1. Validates PR SHA matches run's commit_sha
    2. Commits updated baseline to GitHub
    3. Updates baseline hashes for approved snapshots in DB
    """
    run = get_run(run_id)
    project = run.project

    # Build lookup of identifier -> new_hash
    approvals = {s["identifier"]: s["new_hash"] for s in approved_snapshots}

    # Validate all artifacts exist before making any changes
    for identifier, new_hash in approvals.items():
        artifact = get_artifact(project.id, new_hash)
        if not artifact:
            raise ArtifactNotFoundError(f"Artifact not found for hash {new_hash} (snapshot: {identifier})")

    # Commit to GitHub first (if enabled and PR exists)
    # Do this before DB changes so we can fail cleanly
    if commit_to_github and run.pr_number and project.repo_full_name:
        _commit_baseline_to_github(run, project, approved_snapshots)

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
    run.approved_at = timezone.now()
    run.approved_by_id = user_id
    run.save(update_fields=["approved", "approved_at", "approved_by_id"])

    return run


# --- Snapshot Operations ---


def get_run_snapshots(run_id: UUID) -> list[RunSnapshot]:
    run = get_run(run_id)
    return list(
        run.snapshots.select_related("current_artifact", "baseline_artifact", "diff_artifact").order_by("identifier")
    )


def update_snapshot_diff(
    snapshot_id: UUID,
    diff_artifact: Artifact,
    diff_percentage: float,
    diff_pixel_count: int,
) -> RunSnapshot:
    snapshot = RunSnapshot.objects.get(id=snapshot_id)
    snapshot.diff_artifact = diff_artifact
    snapshot.diff_percentage = diff_percentage
    snapshot.diff_pixel_count = diff_pixel_count
    snapshot.save(update_fields=["diff_artifact", "diff_percentage", "diff_pixel_count"])
    return snapshot


def link_artifact_to_snapshots(project_id: UUID, content_hash: str) -> int:
    """
    After an artifact is uploaded, link it to any pending snapshots.

    Returns number of snapshots updated.
    """
    artifact = get_artifact(project_id, content_hash)
    if not artifact:
        return 0

    # Link as current artifact where hash matches but artifact not linked
    current_updated = RunSnapshot.objects.filter(
        run__project_id=project_id,
        current_hash=content_hash,
        current_artifact__isnull=True,
    ).update(current_artifact=artifact)

    # Link as baseline artifact where hash matches but artifact not linked
    baseline_updated = RunSnapshot.objects.filter(
        run__project_id=project_id,
        baseline_hash=content_hash,
        baseline_artifact__isnull=True,
    ).update(baseline_artifact=artifact)

    return current_updated + baseline_updated
