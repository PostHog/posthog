"""
Full E2E test for visual_review with GitHub integration.

Uses real storybook snapshots from git history and mocked GitHub API
that operates on a local git repo.

Flow:
1. Extract real snapshots from known git commits
2. Submit baseline run via API
3. Submit current run with baseline hashes
4. Process diffs via Celery task
5. Approve via API → commits to local repo
6. Verify local repo has updated snapshots.yml
"""

import hashlib
import subprocess
from uuid import UUID

import pytest

import yaml
from PIL import Image

from products.visual_review.backend import logic
from products.visual_review.backend.api import api
from products.visual_review.backend.api.dtos import (
    ApproveRunInput,
    ApproveSnapshotInput,
    CreateRunInput,
    SnapshotManifestItem,
)
from products.visual_review.backend.domain_types import SnapshotResult
from products.visual_review.backend.models import Repo
from products.visual_review.backend.tasks.tasks import process_run_diffs
from products.visual_review.backend.tests.conftest import get_head_sha

# --- Test Data ---

# Commits with storybook snapshot changes (from test_e2e.py)
TEST_COMMIT = "5a50c17262"
TEST_COMMIT_DESCRIPTION = "Remove tagging checks from feature flags"
TEST_FILES = [
    "scenes-app-feature-flags--feature-flags-list--dark.png",
    "scenes-app-feature-flags--feature-flags-list--light.png",
]

SNAPSHOT_DIR = "frontend/__snapshots__"


# --- Helpers ---


def extract_file_at_commit(commit: str, path: str) -> bytes:
    """Extract file content at specific git commit."""
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        capture_output=True,
        check=True,
    )
    return result.stdout


def compute_image_hash(png_bytes: bytes) -> str:
    """Compute RGBA bitmap hash (same as CLI)."""
    import io

    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return hashlib.sha256(img.tobytes()).hexdigest()


def get_image_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Get width, height from PNG bytes."""
    import io

    img = Image.open(io.BytesIO(png_bytes))
    return img.width, img.height


def extract_test_snapshots() -> dict[str, dict]:
    """
    Extract before/after snapshots for test commit.

    Returns: {identifier: {baseline_bytes, current_bytes, baseline_hash, current_hash, width, height}}
    """
    parent = f"{TEST_COMMIT}~1"
    snapshots = {}

    for filename in TEST_FILES:
        path = f"{SNAPSHOT_DIR}/{filename}"
        identifier = filename.replace(".png", "")

        try:
            baseline_bytes = extract_file_at_commit(parent, path)
            current_bytes = extract_file_at_commit(TEST_COMMIT, path)

            baseline_hash = compute_image_hash(baseline_bytes)
            current_hash = compute_image_hash(current_bytes)
            width, height = get_image_dimensions(current_bytes)

            snapshots[identifier] = {
                "baseline_bytes": baseline_bytes,
                "current_bytes": current_bytes,
                "baseline_hash": baseline_hash,
                "current_hash": current_hash,
                "width": width,
                "height": height,
            }
        except subprocess.CalledProcessError:
            # Skip files not in both commits
            continue

    return snapshots


def upload_artifact(repo_id: UUID, content_hash: str, width: int, height: int, size_bytes: int):
    """
    Create an artifact record (simulates upload + verification in complete_run).

    In real flow:
    1. CLI uploads to S3
    2. Backend verifies upload in complete_run and creates artifact
    3. Backend links artifact to any pending snapshots

    For tests, we skip S3 and just create the artifact directly, then link.
    """
    storage_path = f"visual_review/{repo_id}/{content_hash[:2]}/{content_hash}.png"

    logic.get_or_create_artifact(
        repo_id=repo_id,
        content_hash=content_hash,
        storage_path=storage_path,
        width=width,
        height=height,
        size_bytes=size_bytes,
    )

    # Link artifact to any snapshots waiting for it (simulates complete_run behavior)
    logic.link_artifact_to_snapshots(repo_id, content_hash)


# --- Tests ---


@pytest.mark.django_db(transaction=True)
class TestFullE2EFlow:
    """Full E2E test with real snapshots and GitHub commit."""

    def test_complete_flow_submit_diff_approve_commit(
        self,
        local_git_repo,
        mock_github_api,
        mock_github_integration,
        team,
        user,
        mocker,
    ):
        """
        Complete E2E flow:
        1. Submit baseline run
        2. Submit current run with changes
        3. Process diffs
        4. Approve → commits to local git repo
        5. Verify repo updated
        """
        # Mock object storage for diff computation
        mocker.patch(
            "products.visual_review.backend.logic.read_artifact_bytes",
            side_effect=self._mock_read_artifact,
        )
        mocker.patch(
            "products.visual_review.backend.logic.write_artifact_bytes",
            side_effect=self._mock_write_artifact,
        )

        # Extract real snapshots
        snapshots = extract_test_snapshots()
        assert len(snapshots) >= 2, "Need at least 2 snapshots for test"

        # Create repo pointing to local repo
        repo = Repo.objects.create(
            team=team,
            name="e2e-test-repo",
            repo_full_name="test-org/test-repo",
            baseline_file_paths={"storybook": ".snapshots.yml"},
        )

        # Store snapshot data for mock
        self._snapshot_data = snapshots

        # --- Step 1: Submit baseline run ---
        # This simulates the first ever run (no baselines yet)

        baseline_manifest = [
            SnapshotManifestItem(
                identifier=identifier,
                content_hash=data["baseline_hash"],
                width=data["width"],
                height=data["height"],
            )
            for identifier, data in snapshots.items()
        ]

        api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type="storybook",
                commit_sha="baseline123",
                branch="main",
                snapshots=baseline_manifest,
                baseline_hashes={},  # No baselines yet
            )
        )

        # Upload baseline artifacts
        for _, data in snapshots.items():
            upload_artifact(
                repo.id,
                data["baseline_hash"],
                data["width"],
                data["height"],
                len(data["baseline_bytes"]),
            )

        # --- Step 2: Submit current run with baseline hashes ---
        # This simulates a PR run where we compare against baselines

        # First, update local repo to have matching commit SHA
        commit_sha = get_head_sha(local_git_repo)

        current_manifest = [
            SnapshotManifestItem(
                identifier=identifier,
                content_hash=data["current_hash"],
                width=data["width"],
                height=data["height"],
            )
            for identifier, data in snapshots.items()
        ]

        baseline_hashes = {identifier: data["baseline_hash"] for identifier, data in snapshots.items()}

        current_result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type="storybook",
                commit_sha=commit_sha,
                branch="feature-branch",
                pr_number=42,
                snapshots=current_manifest,
                baseline_hashes=baseline_hashes,
            )
        )

        # Upload current artifacts
        for _, data in snapshots.items():
            upload_artifact(
                repo.id,
                data["current_hash"],
                data["width"],
                data["height"],
                len(data["current_bytes"]),
            )

        # --- Step 3: Process diffs ---
        # Call Celery task directly (synchronously for test)
        process_run_diffs(str(current_result.run_id))

        # Verify run has changes detected
        run = api.get_run(current_result.run_id)
        assert run.summary.changed >= 2, f"Expected changes, got {run.summary}"

        # Get snapshots for approval
        run_snapshots = api.get_run_snapshots(current_result.run_id)
        changed_snapshots = [s for s in run_snapshots if s.result == SnapshotResult.CHANGED]
        assert len(changed_snapshots) >= 2

        # --- Step 4: Approve changes ---
        approve_input = ApproveRunInput(
            run_id=current_result.run_id,
            user_id=user.id,
            snapshots=[
                ApproveSnapshotInput(
                    identifier=s.identifier,
                    new_hash=s.current_artifact.content_hash,
                )
                for s in changed_snapshots
            ],
            commit_to_github=True,
        )

        approved_run = api.approve_run(approve_input)
        assert approved_run.approved is True

        # --- Step 5: Verify local repo was updated ---
        snapshots_file = local_git_repo / ".snapshots.yml"
        content = snapshots_file.read_text()
        parsed = yaml.safe_load(content)

        assert parsed["version"] == 1
        for identifier, data in snapshots.items():
            assert parsed["snapshots"][identifier] == data["current_hash"], (
                f"Expected {identifier} to have hash {data['current_hash']}"
            )

        # Verify commit message
        log_result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=local_git_repo,
            capture_output=True,
            text=True,
        )
        assert "chore(visual): update visual baselines" in log_result.stdout

    def _mock_read_artifact(self, repo_id, content_hash):
        """Mock that returns real snapshot bytes."""
        for data in self._snapshot_data.values():
            if data["baseline_hash"] == content_hash:
                return data["baseline_bytes"]
            if data["current_hash"] == content_hash:
                return data["current_bytes"]
        return None

    def _mock_write_artifact(self, repo_id, content_hash, content, width=None, height=None):
        """Mock that creates artifact record without S3."""
        from products.visual_review.backend.models import Artifact

        artifact, _ = Artifact.objects.get_or_create(
            repo_id=repo_id,
            content_hash=content_hash,
            defaults={
                "storage_path": f"mock/{content_hash}.png",
                "width": width,
                "height": height,
                "size_bytes": len(content),
            },
        )
        return artifact

    def test_approve_then_resubmit_shows_unchanged(
        self,
        local_git_repo,
        mock_github_api,
        mock_github_integration,
        team,
        user,
        mocker,
    ):
        """
        After approval, resubmitting with approved hashes shows all unchanged.
        """
        mocker.patch(
            "products.visual_review.backend.logic.read_artifact_bytes",
            return_value=None,  # Not needed for this test
        )

        snapshots = extract_test_snapshots()
        self._snapshot_data = snapshots

        repo = Repo.objects.create(
            team=team,
            name="resubmit-test",
            repo_full_name="test-org/test-repo",
            baseline_file_paths={"storybook": ".snapshots.yml"},
        )

        # First run with changes
        commit_sha = get_head_sha(local_git_repo)

        manifest = [
            SnapshotManifestItem(
                identifier=identifier,
                content_hash=data["current_hash"],
                width=data["width"],
                height=data["height"],
            )
            for identifier, data in snapshots.items()
        ]

        # Submit with baseline hashes (simulates changes)
        baseline_hashes = {identifier: data["baseline_hash"] for identifier, data in snapshots.items()}

        result1 = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type="storybook",
                commit_sha=commit_sha,
                branch="feature-branch",
                pr_number=42,
                snapshots=manifest,
                baseline_hashes=baseline_hashes,
            )
        )

        # Upload artifacts
        for _, data in snapshots.items():
            upload_artifact(repo.id, data["current_hash"], data["width"], data["height"], len(data["current_bytes"]))
            upload_artifact(repo.id, data["baseline_hash"], data["width"], data["height"], len(data["baseline_bytes"]))

        run1 = api.get_run(result1.run_id)
        assert run1.summary.changed >= 2

        # Approve (commits to local repo)
        run_snapshots = api.get_run_snapshots(result1.run_id)
        changed = [s for s in run_snapshots if s.result == SnapshotResult.CHANGED]

        api.approve_run(
            ApproveRunInput(
                run_id=result1.run_id,
                user_id=user.id,
                snapshots=[
                    ApproveSnapshotInput(identifier=s.identifier, new_hash=s.current_artifact.content_hash)
                    for s in changed
                ],
                commit_to_github=True,
            )
        )

        # Now resubmit with approved hashes as baselines
        # This simulates CI re-running after bot commit
        new_commit_sha = get_head_sha(local_git_repo)  # New commit after approval

        approved_hashes = {identifier: data["current_hash"] for identifier, data in snapshots.items()}

        result2 = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type="storybook",
                commit_sha=new_commit_sha,
                branch="feature-branch",
                pr_number=42,
                snapshots=manifest,  # Same current hashes
                baseline_hashes=approved_hashes,  # Now baseline == current
            )
        )

        run2 = api.get_run(result2.run_id)

        # All should be unchanged now
        assert run2.summary.changed == 0
        assert run2.summary.new == 0
        assert run2.summary.unchanged == len(snapshots)
