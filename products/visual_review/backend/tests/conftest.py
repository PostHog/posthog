"""
Shared fixtures for visual_review tests.

Shared PostHog test fixtures (team, user, django_db_setup) are inherited
from products/conftest.py which re-exports posthog/conftest.py.
"""

import re
import json
import base64
import hashlib
import subprocess
from contextlib import AbstractContextManager
from pathlib import Path

import pytest
from unittest.mock import MagicMock

import responses

from posthog.models.scoping import team_scope

from products.visual_review.backend.models import Repo

PRODUCT_DATABASES = {"default", "visual_review_db_writer", "visual_review_db_reader"}


@pytest.fixture(autouse=True)
def _set_team_scope(request):
    """Set team context for raw pytest tests that use the database.

    ProductTeamModel is fail-closed — queries without context raise
    TeamScopeError. Only activates for tests marked with @pytest.mark.django_db.

    TestCase / APIBaseTest subclasses are skipped here even when the
    marker is present, because they create their own team in setUp()
    and `getfixturevalue("team")` would duplicate-create with the same
    api_token (collision on `posthog_team_api_token_a9a1df8a_uniq`).
    Those tests use VisualReviewTeamScopedTestMixin (below) which
    wraps setUp/tearDown with team_scope using the test's own
    self.team — no extra team creation.
    """
    if request.node.get_closest_marker("django_db") is None:
        yield
        return

    is_django_testcase = request.cls is not None and any(cls.__name__ == "TestCase" for cls in request.cls.__mro__)
    if is_django_testcase:
        yield
        return

    team = request.getfixturevalue("team")
    with team_scope(team.id):
        yield


class VisualReviewTeamScopedTestMixin:
    """Mixin for TestCase / APIBaseTest tests that use ProductTeamModel.

    Wraps setUp/tearDown with team_scope so the test body's queries to
    Repo, Run, RunSnapshot etc. find a scope. Place this BEFORE
    APIBaseTest in the MRO so its setUp runs first (creating self.team)
    and our setUp can use it:

        class TestFoo(VisualReviewTeamScopedTestMixin, APIBaseTest):
            def test_thing(self):
                Repo.objects.create(...)  # auto-scoped

    The `_team_scope_cm` attribute is initialized to None up front so a
    partial-init failure in setUp (e.g. team_scope() raising during
    resolve, or super().setUp() raising) doesn't leave tearDown trying
    to __exit__ an unentered context manager.
    """

    _team_scope_cm: AbstractContextManager[None] | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        cm = team_scope(self.team.id)  # type: ignore[attr-defined]
        cm.__enter__()
        self._team_scope_cm = cm

    def tearDown(self) -> None:
        if self._team_scope_cm is not None:
            try:
                self._team_scope_cm.__exit__(None, None, None)
            finally:
                self._team_scope_cm = None
        super().tearDown()  # type: ignore[misc]


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

        # Track status check calls for assertions
        status_checks = []
        issue_comments = []
        next_comment_id = [1000]

        def status_callback(request):
            data = json.loads(request.body)
            status_checks.append(data)
            return (201, {}, json.dumps({"id": 1, "state": data["state"]}))

        def issue_comment_callback(request):
            data = json.loads(request.body)
            comment_id = next_comment_id[0]
            next_comment_id[0] += 1
            issue_comments.append({**data, "id": comment_id, "action": "created"})
            return (201, {}, json.dumps({"id": comment_id, "body": data["body"]}))

        def issue_comment_update_callback(request):
            data = json.loads(request.body)
            issue_comments.append({**data, "action": "updated"})
            return (200, {}, json.dumps({"id": 1, "body": data["body"]}))

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
        rsps.add_callback(
            responses.POST,
            re.compile(r"https://api\.github\.com/repos/.+/statuses/.+"),
            callback=status_callback,
        )
        rsps.add_callback(
            responses.POST,
            re.compile(r"https://api\.github\.com/repos/.+/issues/\d+/comments"),
            callback=issue_comment_callback,
        )
        rsps.add_callback(
            responses.PATCH,
            re.compile(r"https://api\.github\.com/repos/.+/issues/comments/\d+"),
            callback=issue_comment_update_callback,
        )

        rsps.status_checks = status_checks  # type: ignore[attr-defined]
        rsps.issue_comments = issue_comments  # type: ignore[attr-defined]
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
        team_id=team.id,
        repo_external_id=12345,
        repo_full_name="test-org/test-repo",
        baseline_file_paths={"storybook": ".snapshots.yml"},
    )
