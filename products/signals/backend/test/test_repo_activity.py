from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models import Organization, Team
from posthog.models.github_integration_base import GitHubRecentCommit
from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalRepositoryAreaActivity
from products.signals.backend.report_generation.repo_activity import (
    MAX_AREAS_PER_RESOLUTION,
    area_for_path,
    areas_for_paths,
    get_area_activity,
)
from products.signals.backend.tasks import refresh_signal_repository_activity


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-repo-activity-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-repo-activity-team")


class FakeGitHub:
    """Stub of the GitHubIntegrationBase surface repo_activity uses."""

    def __init__(self, commits_by_path: dict[str | None, list[GitHubRecentCommit]] | None = None):
        self.commits_by_path = commits_by_path or {}
        self.calls: list[str | None] = []
        self.raise_error: Exception | None = None

    def list_recent_commits(self, repository, *, path=None, since=None, per_page=100, max_pages=1):
        self.calls.append(path)
        if self.raise_error is not None:
            raise self.raise_error
        return self.commits_by_path.get(path, [])


def _commit(login: str, sha: str, days_ago: int) -> GitHubRecentCommit:
    committed_at = (timezone.now() - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return GitHubRecentCommit(
        sha=sha,
        login=login,
        name=login.title(),
        committed_at=committed_at,
        html_url=f"https://github.com/acme/app/commit/{sha}",
    )


class TestAreaForPath:
    def test_root_file_maps_to_empty_area(self):
        assert area_for_path("README.md") == ""

    def test_single_directory(self):
        assert area_for_path("posthog/models.py") == "posthog"

    def test_deep_path_capped_at_two_directories(self):
        assert area_for_path("products/signals/backend/models.py") == "products/signals"
        assert area_for_path("products/signals/backend/temporal/agentic/report.py") == "products/signals"

    def test_leading_slash_normalized(self):
        assert area_for_path("/products/signals/x.py") == "products/signals"

    def test_areas_ranked_by_touch_count_and_capped(self):
        paths = ["a/b/one.py", "a/b/two.py", "c/d/one.py"]
        assert areas_for_paths(paths) == ["a/b", "c/d"]

        many = [f"dir{i}/sub/file.py" for i in range(MAX_AREAS_PER_RESOLUTION + 3)]
        assert len(areas_for_paths(many)) == MAX_AREAS_PER_RESOLUTION


@pytest.mark.django_db
class TestGetAreaActivity:
    def test_creates_row_and_returns_contributors(self, team):
        github = FakeGitHub(
            {
                "products/signals": [
                    _commit("alice", "a" * 7, 3),
                    _commit("alice", "b" * 7, 10),
                    _commit("bob", "c" * 7, 40),
                ]
            }
        )

        result = get_area_activity(github, team.id, "acme/app", ["products/signals"])

        assert github.calls == ["products/signals"]
        contributors = result["products/signals"]
        assert [(c.login, c.commit_count) for c in contributors] == [("alice", 2), ("bob", 1)]
        # Newest-first listing: the first commit seen per login is their latest.
        assert contributors[0].last_commit_sha == "a" * 7

        with team_scope(team.id, canonical=True):
            row = SignalRepositoryAreaActivity.objects.get(repository="acme/app", area="products/signals")
        assert row.refreshed_at is not None

    def test_fresh_row_is_not_refetched(self, team):
        with team_scope(team.id, canonical=True):
            SignalRepositoryAreaActivity.objects.create(
                team=team,
                repository="acme/app",
                area="products/signals",
                contributors=[
                    {
                        "login": "alice",
                        "name": "Alice",
                        "commit_count": 5,
                        "last_commit_at": timezone.now().isoformat(),
                        "last_commit_sha": "e" * 7,
                        "last_commit_url": "https://github.com/acme/app/commit/eeeeeee",
                    }
                ],
                refreshed_at=timezone.now(),
            )
        github = FakeGitHub()

        result = get_area_activity(github, team.id, "acme/app", ["products/signals"])

        assert github.calls == []
        assert [c.login for c in result["products/signals"]] == ["alice"]

    def test_rate_limited_refresh_falls_back_to_stale_data(self, team):
        with team_scope(team.id, canonical=True):
            SignalRepositoryAreaActivity.objects.create(
                team=team,
                repository="acme/app",
                area="products/signals",
                contributors=[
                    {
                        "login": "bob",
                        "name": "Bob",
                        "commit_count": 2,
                        "last_commit_at": (timezone.now() - timedelta(days=20)).isoformat(),
                        "last_commit_sha": "f" * 7,
                        "last_commit_url": "https://github.com/acme/app/commit/fffffff",
                    }
                ],
                refreshed_at=timezone.now() - timedelta(days=30),
            )
        github = FakeGitHub()
        github.raise_error = GitHubRateLimitError("rate limited")

        result = get_area_activity(github, team.id, "acme/app", ["products/signals"])

        assert [c.login for c in result["products/signals"]] == ["bob"]

    def test_never_refreshed_area_is_absent_from_result(self, team):
        github = FakeGitHub()
        github.raise_error = RuntimeError("boom")

        result = get_area_activity(github, team.id, "acme/app", ["products/signals"])

        assert result == {}
        # The row still exists so the weekly refresh can pick it up later.
        with team_scope(team.id, canonical=True):
            assert SignalRepositoryAreaActivity.objects.filter(repository="acme/app").count() == 1


@pytest.mark.django_db
class TestWeeklyRefreshTask:
    def test_refreshes_used_rows_and_drops_idle_ones(self, team):
        now = timezone.now()
        with team_scope(team.id, canonical=True):
            used = SignalRepositoryAreaActivity.objects.create(
                team=team, repository="acme/app", area="products/signals", last_used_at=now
            )
            idle = SignalRepositoryAreaActivity.objects.create(
                team=team, repository="acme/app", area="products/old", last_used_at=now - timedelta(days=120)
            )

        fake_github = FakeGitHub({"products/signals": [_commit("alice", "a" * 7, 1)]})
        with patch(
            "products.signals.backend.tasks.GitHubIntegration.first_for_team_repository",
            return_value=fake_github,
        ):
            refresh_signal_repository_activity()

        with team_scope(team.id, canonical=True):
            assert not SignalRepositoryAreaActivity.objects.filter(id=idle.id).exists()
            used.refresh_from_db()
        assert used.refreshed_at is not None
        assert [c["login"] for c in used.contributors] == ["alice"]

    def test_rate_limit_skips_remaining_rows_for_repository(self, team):
        now = timezone.now()
        with team_scope(team.id, canonical=True):
            SignalRepositoryAreaActivity.objects.create(
                team=team, repository="acme/app", area="a/one", last_used_at=now
            )
            SignalRepositoryAreaActivity.objects.create(
                team=team, repository="acme/app", area="a/two", last_used_at=now
            )

        fake_github = FakeGitHub()
        fake_github.raise_error = GitHubRateLimitError("rate limited")
        with patch(
            "products.signals.backend.tasks.GitHubIntegration.first_for_team_repository",
            return_value=fake_github,
        ):
            refresh_signal_repository_activity()

        # First row hits the limit; the second is skipped without another API call.
        assert fake_github.calls == ["a/one"]
        with team_scope(team.id, canonical=True):
            assert not SignalRepositoryAreaActivity.objects.filter(refreshed_at__isnull=False).exists()
