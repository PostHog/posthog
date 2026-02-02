"""
Shared fixtures for visual_review tests.

This conftest loads shared PostHog test fixtures (team, user, django_db_setup)
via pytest_plugins. These fixtures handle Django/ClickHouse test database setup.
"""

import re
import json
import base64
import hashlib
import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock

import responses

from products.visual_review.backend.models import Repo

# Import shared PostHog test fixtures (team, user, django_db_setup, etc.)
# This makes posthog/conftest.py fixtures available to our tests
pytest_plugins = ["posthog.conftest"]

# --- Local Git Repo Fixtures ---


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


def get_head_sha(repo_path: Path) -> str:
    """Get current HEAD SHA of the repo."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_file_content_from_repo(repo_path: Path, file_path: str, branch: str) -> tuple[str, str] | None:
    """Get file content and SHA at a specific branch."""
    subprocess.run(["git", "checkout", branch], cwd=repo_path, capture_output=True, check=True)

    full_path = repo_path / file_path
    if not full_path.exists():
        return None

    content = full_path.read_text()
    blob_sha = hashlib.sha1(f"blob {len(content)}\0{content}".encode()).hexdigest()
    return content, blob_sha


def commit_file_to_repo(repo_path: Path, file_path: str, content: str, message: str, branch: str) -> str:
    """Write file and commit to repo. Returns new commit SHA."""
    subprocess.run(["git", "checkout", branch], cwd=repo_path, capture_output=True, check=True)

    full_path = repo_path / file_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)

    subprocess.run(["git", "add", file_path], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True)

    return get_head_sha(repo_path)


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
        repo_path = local_git_repo

        def pr_callback(request):
            return (
                200,
                {},
                json.dumps(
                    {
                        "head": {
                            "ref": "feature-branch",
                            "sha": get_head_sha(repo_path),
                        }
                    }
                ),
            )

        def get_file_callback(request):
            match = re.search(r"/contents/(.+?)(?:\?|$)", request.url)
            if not match:
                return (404, {}, json.dumps({"message": "Not Found"}))

            file_path = match.group(1)
            branch = "feature-branch"
            if "ref=" in request.url:
                branch_match = re.search(r"ref=([^&]+)", request.url)
                if branch_match:
                    branch = branch_match.group(1)

            result = get_file_content_from_repo(repo_path, file_path, branch)
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
            match = re.search(r"/contents/(.+?)(?:\?|$)", request.url)
            if not match:
                return (400, {}, json.dumps({"message": "Bad Request"}))

            file_path = match.group(1)
            data = json.loads(request.body)

            content = base64.b64decode(data["content"]).decode()
            message = data["message"]
            branch = data["branch"]

            commit_sha = commit_file_to_repo(repo_path, file_path, content, message, branch)
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
    """
    from posthog.models.integration import GitHubIntegration, Integration

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

    original_filter = Integration.objects.filter

    def patched_filter(*args, **kwargs):
        if kwargs.get("kind") == "github" and kwargs.get("team_id") == team.id:
            mock_qs = MagicMock()
            mock_qs.first.return_value = mock_integration
            return mock_qs
        return original_filter(*args, **kwargs)

    mocker.patch.object(Integration.objects, "filter", side_effect=patched_filter)

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
