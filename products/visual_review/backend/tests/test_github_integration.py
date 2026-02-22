"""
Tests for GitHub integration in the approve flow.

Uses a local git repo with mocked GitHub API endpoints.
The real code paths are exercised, but HTTP calls are intercepted
and redirected to operate on the local repo.
"""

import re
import json
import base64
import hashlib
import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock

import yaml
import responses

from products.visual_review.backend import logic
from products.visual_review.backend.facade.enums import RunStatus, SnapshotResult
from products.visual_review.backend.models import Artifact, Repo, Run, RunSnapshot

# --- Fixtures ---


@pytest.fixture
def local_git_repo(tmp_path):
    """Create a local git repo with a test branch simulating a PR."""
    repo = tmp_path / "test-repo"
    repo.mkdir()

    # Initialize repo
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    # Create initial commit on main
    snapshots_file = repo / ".snapshots.yml"
    snapshots_file.write_text("version: 1\nsnapshots: {}\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)

    # Create feature branch (simulates PR branch)
    subprocess.run(["git", "checkout", "-b", "feature-branch"], cwd=repo, check=True)

    return repo


def _get_head_sha(repo_path: Path) -> str:
    """Get current HEAD SHA of the repo."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _get_current_branch(repo_path: Path) -> str:
    """Get current branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _get_file_content(repo_path: Path, file_path: str, branch: str) -> tuple[str, str] | None:
    """Get file content and SHA at a specific branch."""
    # Checkout branch
    subprocess.run(["git", "checkout", branch], cwd=repo_path, capture_output=True, check=True)

    full_path = repo_path / file_path
    if not full_path.exists():
        return None

    content = full_path.read_text()
    # GitHub uses blob SHA, we'll fake it with content hash
    blob_sha = hashlib.sha1(f"blob {len(content)}\0{content}".encode()).hexdigest()
    return content, blob_sha


def _commit_file(repo_path: Path, file_path: str, content: str, message: str, branch: str) -> str:
    """Write file and commit to repo. Returns new commit SHA."""
    subprocess.run(["git", "checkout", branch], cwd=repo_path, capture_output=True, check=True)

    full_path = repo_path / file_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)

    subprocess.run(["git", "add", file_path], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True)

    return _get_head_sha(repo_path)


@pytest.fixture
def mock_github_api(local_git_repo):
    """
    Mock GitHub API endpoints to operate on local git repo.

    Intercepts:
    - GET /repos/{owner}/{repo}/pulls/{pr} -> PR info
    - GET /repos/{owner}/{repo}/contents/{path} -> file content
    - PUT /repos/{owner}/{repo}/contents/{path} -> commit file
    """
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # Store repo path for callbacks
        repo_path = local_git_repo

        def pr_callback(request):
            """Return PR info with current branch and SHA."""
            return (
                200,
                {},
                json.dumps(
                    {
                        "head": {
                            "ref": "feature-branch",
                            "sha": _get_head_sha(repo_path),
                        }
                    }
                ),
            )

        def get_file_callback(request):
            """Return file content from local repo."""
            # Extract file path from URL
            match = re.search(r"/contents/(.+?)(?:\?|$)", request.url)
            if not match:
                return (404, {}, json.dumps({"message": "Not Found"}))

            file_path = match.group(1)

            # Get branch from query params
            branch = "feature-branch"
            if "ref=" in request.url:
                branch_match = re.search(r"ref=([^&]+)", request.url)
                if branch_match:
                    branch = branch_match.group(1)

            result = _get_file_content(repo_path, file_path, branch)
            if result is None:
                return (404, {}, json.dumps({"message": "Not Found"}))

            content, blob_sha = result
            encoded = base64.b64encode(content.encode()).decode()

            return (
                200,
                {},
                json.dumps(
                    {
                        "content": encoded,
                        "sha": blob_sha,
                        "encoding": "base64",
                    }
                ),
            )

        def put_file_callback(request):
            """Commit file to local repo."""
            # Extract file path from URL
            match = re.search(r"/contents/(.+?)(?:\?|$)", request.url)
            if not match:
                return (400, {}, json.dumps({"message": "Bad Request"}))

            file_path = match.group(1)
            data = json.loads(request.body)

            content = base64.b64decode(data["content"]).decode()
            message = data["message"]
            branch = data["branch"]

            commit_sha = _commit_file(repo_path, file_path, content, message, branch)
            file_sha = hashlib.sha1(f"blob {len(content)}\0{content}".encode()).hexdigest()

            return (
                200,
                {},
                json.dumps(
                    {
                        "commit": {
                            "sha": commit_sha,
                            "html_url": f"https://github.com/test/repo/commit/{commit_sha}",
                        },
                        "content": {
                            "sha": file_sha,
                        },
                    }
                ),
            )

        # Register callbacks
        rsps.add_callback(
            responses.GET,
            re.compile(r"https://api\.github\.com/repos/.+/pulls/\d+"),
            callback=pr_callback,
        )
        rsps.add_callback(
            responses.GET,
            re.compile(r"https://api\.github\.com/repos/.+/contents/.+"),
            callback=get_file_callback,
        )
        rsps.add_callback(
            responses.PUT,
            re.compile(r"https://api\.github\.com/repos/.+/contents/.+"),
            callback=put_file_callback,
        )

        yield rsps


@pytest.fixture
def mock_github_integration(team, mocker):
    """
    Create a mock GitHub integration for the team.

    This patches the Integration lookup to return a fake integration
    with valid credentials structure.
    """
    from posthog.models.integration import GitHubIntegration, Integration

    # Create a mock integration object
    mock_integration = MagicMock(spec=Integration)
    mock_integration.id = 1
    mock_integration.team_id = team.id
    mock_integration.kind = "github"
    mock_integration.config = {
        "installation_id": "12345",
        "account": {"name": "test-org", "type": "Organization"},
    }
    mock_integration.sensitive_config = {
        "access_token": "ghs_fake_token_for_testing",
    }

    # Patch the Integration.objects.filter to return our mock
    original_filter = Integration.objects.filter

    def patched_filter(*args, **kwargs):
        if kwargs.get("kind") == "github" and kwargs.get("team_id") == team.id:
            mock_qs = MagicMock()
            mock_qs.first.return_value = mock_integration
            return mock_qs
        return original_filter(*args, **kwargs)

    mocker.patch.object(Integration.objects, "filter", side_effect=patched_filter)

    # Also patch GitHubIntegration methods we need
    def mock_access_token_expired(self):
        return False

    mocker.patch.object(GitHubIntegration, "access_token_expired", mock_access_token_expired)

    return mock_integration


@pytest.fixture
def vr_project_with_github(team, mock_github_integration):
    """Create a visual review repo configured for GitHub."""
    return Repo.objects.create(
        team=team,
        name="test-repo",
        repo_full_name="test-org/test-repo",
        baseline_file_paths={"storybook": ".snapshots.yml"},
    )


@pytest.fixture
def run_with_changes(vr_project_with_github, local_git_repo):
    """
    Create a run with changed snapshots that can be approved.

    Sets up:
    - A run with pr_number and commit_sha matching the local repo
    - Snapshots marked as 'changed' with artifacts
    """
    repo = vr_project_with_github
    commit_sha = _get_head_sha(local_git_repo)

    run = Run.objects.create(
        repo=repo,
        status=RunStatus.COMPLETED,
        run_type="storybook",
        commit_sha=commit_sha,
        branch="feature-branch",
        pr_number=42,
        total_snapshots=2,
        changed_count=2,
    )

    # Create artifacts for the snapshots
    artifact1 = Artifact.objects.create(
        repo=repo,
        content_hash="abc123hash",
        storage_path="visual_review/test/abc123hash.png",
        width=800,
        height=600,
    )
    artifact2 = Artifact.objects.create(
        repo=repo,
        content_hash="def456hash",
        storage_path="visual_review/test/def456hash.png",
        width=1200,
        height=800,
    )

    # Create snapshots
    RunSnapshot.objects.create(
        run=run,
        identifier="button--primary",
        current_hash="abc123hash",
        baseline_hash="old111hash",
        current_artifact=artifact1,
        result=SnapshotResult.CHANGED,
    )
    RunSnapshot.objects.create(
        run=run,
        identifier="card--default",
        current_hash="def456hash",
        baseline_hash="old222hash",
        current_artifact=artifact2,
        result=SnapshotResult.CHANGED,
    )

    return run


# --- Tests ---


@pytest.mark.django_db
class TestGitHubCommitOnApprove:
    """Test that approve commits baseline updates to GitHub."""

    def test_approve_commits_to_local_repo(
        self,
        local_git_repo,
        mock_github_api,
        mock_github_integration,
        vr_project_with_github,
        run_with_changes,
        user,
    ):
        """
        Full E2E test: approve should commit updated snapshots.yml to the repo.
        """
        run = run_with_changes

        # Approve the snapshots
        approved = [
            {"identifier": "button--primary", "new_hash": "abc123hash"},
            {"identifier": "card--default", "new_hash": "def456hash"},
        ]

        result = logic.approve_run(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=approved,
            commit_to_github=True,
        )

        # Verify run is approved in DB
        assert result.approved is True

        # Verify the local git repo was updated
        snapshots_file = local_git_repo / ".snapshots.yml"
        content = snapshots_file.read_text()
        parsed = yaml.safe_load(content)

        assert parsed["version"] == 1
        assert parsed["snapshots"]["button--primary"] == "abc123hash"
        assert parsed["snapshots"]["card--default"] == "def456hash"

        # Verify a commit was made
        log_result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=local_git_repo,
            capture_output=True,
            text=True,
        )
        assert "chore(visual): update visual baselines" in log_result.stdout

    def test_approve_merges_with_existing_baselines(
        self,
        local_git_repo,
        mock_github_api,
        mock_github_integration,
        vr_project_with_github,
        run_with_changes,
        user,
    ):
        """Approve should merge with existing baselines, not replace them."""
        # First, add some existing baselines to the repo
        snapshots_file = local_git_repo / ".snapshots.yml"
        existing = {
            "version": 1,
            "snapshots": {
                "existing--snapshot": "existinghash",
                "button--primary": "oldhash",  # Will be updated
            },
        }
        snapshots_file.write_text(yaml.dump(existing))
        subprocess.run(["git", "add", "."], cwd=local_git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "add existing"], cwd=local_git_repo, check=True)

        # Update run's commit_sha to match
        run = run_with_changes
        run.commit_sha = _get_head_sha(local_git_repo)
        run.save()

        # Approve only button--primary
        approved = [{"identifier": "button--primary", "new_hash": "abc123hash"}]

        logic.approve_run(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=approved,
            commit_to_github=True,
        )

        # Verify merged result
        content = snapshots_file.read_text()
        parsed = yaml.safe_load(content)

        assert parsed["snapshots"]["existing--snapshot"] == "existinghash"  # Preserved
        assert parsed["snapshots"]["button--primary"] == "abc123hash"  # Updated

    def test_approve_fails_on_sha_mismatch(
        self,
        local_git_repo,
        mock_github_api,
        mock_github_integration,
        vr_project_with_github,
        run_with_changes,
        user,
    ):
        """Approve should fail if PR has new commits since the run."""
        run = run_with_changes

        # Make a new commit to the repo (simulating someone pushing to the PR)
        dummy_file = local_git_repo / "new_file.txt"
        dummy_file.write_text("new content")
        subprocess.run(["git", "add", "."], cwd=local_git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "new commit"], cwd=local_git_repo, check=True)

        # Now the run's commit_sha doesn't match HEAD
        approved = [{"identifier": "button--primary", "new_hash": "abc123hash"}]

        with pytest.raises(logic.PRSHAMismatchError) as exc_info:
            logic.approve_run(
                run_id=run.id,
                user_id=user.id,
                approved_snapshots=approved,
                commit_to_github=True,
            )

        assert "newer commits" in str(exc_info.value)

    def test_approve_without_github_skips_commit(
        self,
        vr_project_with_github,
        run_with_changes,
        user,
    ):
        """Approve with commit_to_github=False should only update DB."""
        run = run_with_changes

        approved = [{"identifier": "button--primary", "new_hash": "abc123hash"}]

        # This should succeed without GitHub mocks
        result = logic.approve_run(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=approved,
            commit_to_github=False,
        )

        assert result.approved is True

    def test_approve_without_pr_number_skips_commit(
        self,
        mock_github_integration,
        vr_project_with_github,
        user,
    ):
        """Approve for a run without pr_number should only update DB."""
        repo = vr_project_with_github

        # Create run without pr_number
        run = Run.objects.create(
            repo=repo,
            status=RunStatus.COMPLETED,
            run_type="storybook",
            commit_sha="abc123",
            branch="main",
            pr_number=None,  # No PR
            total_snapshots=1,
            changed_count=1,
        )

        artifact = Artifact.objects.create(
            repo=repo,
            content_hash="newhash",
            storage_path="path/to/artifact.png",
        )

        RunSnapshot.objects.create(
            run=run,
            identifier="test-snapshot",
            current_hash="newhash",
            current_artifact=artifact,
            result=SnapshotResult.CHANGED,
        )

        approved = [{"identifier": "test-snapshot", "new_hash": "newhash"}]

        # Should succeed without GitHub interaction
        result = logic.approve_run(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=approved,
            commit_to_github=True,  # True but no pr_number
        )

        assert result.approved is True

    def test_approve_preserves_result_and_sets_approval_fields(
        self,
        vr_project_with_github,
        run_with_changes,
        user,
    ):
        """
        Approve should NOT mutate snapshot.result.

        Instead it sets approval fields to record the approval while
        preserving the diff history.
        """
        run = run_with_changes
        snapshots_before = list(run.snapshots.all())

        # Verify snapshots are CHANGED before approval
        for s in snapshots_before:
            assert s.result == SnapshotResult.CHANGED
            assert s.reviewed_at is None
            assert s.reviewed_by_id is None
            assert s.approved_hash == ""

        approved = [
            {"identifier": "button--primary", "new_hash": "abc123hash"},
            {"identifier": "card--default", "new_hash": "def456hash"},
        ]

        logic.approve_run(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=approved,
            commit_to_github=False,
        )

        # Refresh snapshots from DB
        for s in run.snapshots.all():
            # Result should NOT have changed - still CHANGED
            assert s.result == SnapshotResult.CHANGED, f"Expected result to stay CHANGED but got {s.result}"

            # Approval fields should be populated
            assert s.reviewed_at is not None
            assert s.reviewed_by_id == user.id
            assert s.approved_hash in ["abc123hash", "def456hash"]


@pytest.mark.django_db
class TestGitHubIntegrationErrors:
    """Test error handling for GitHub integration."""

    def test_missing_github_integration(self, team, user):
        """Should raise error if team has no GitHub integration."""
        repo = Repo.objects.create(
            team=team,
            name="no-github-repo",
            repo_full_name="org/repo",
            baseline_file_paths={"storybook": ".snapshots.yml"},
        )

        run = Run.objects.create(
            repo=repo,
            status=RunStatus.COMPLETED,
            run_type="storybook",
            commit_sha="abc123",
            branch="feature",
            pr_number=1,
            total_snapshots=1,
        )

        artifact = Artifact.objects.create(
            repo=repo,
            content_hash="hash123",
            storage_path="path.png",
        )

        RunSnapshot.objects.create(
            run=run,
            identifier="snap",
            current_hash="hash123",
            current_artifact=artifact,
            result=SnapshotResult.CHANGED,
        )

        with pytest.raises(logic.GitHubIntegrationNotFoundError):
            logic.approve_run(
                run_id=run.id,
                user_id=user.id,
                approved_snapshots=[{"identifier": "snap", "new_hash": "hash123"}],
                commit_to_github=True,
            )
