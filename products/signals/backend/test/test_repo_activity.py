from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from posthog.models import Organization, Team
from posthog.models.github_integration_base import GitHubCommitAttribution
from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalRepositoryAreaActivity
from products.signals.backend.report_generation.repo_activity import (
    MAX_AREAS_PER_RESOLUTION,
    REPO_WIDE_AREA,
    area_fallback_chain,
    area_for_path,
    areas_for_paths,
    get_area_activity,
    rebuild_repository_activity,
    repository_activity_needs_rebuild,
)
from products.signals.backend.tasks import refresh_signal_repository_activity
from products.tasks.backend.facade.repo_activity import RepositoryCommitActivity

_COLLECT_PATCH_TARGET = "products.signals.backend.report_generation.repo_activity.collect_repository_commit_activity"


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-repo-activity-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-repo-activity-team")


def _commit(sha: str, email: str, days_ago: int, paths: list[str], name: str = "") -> RepositoryCommitActivity:
    return RepositoryCommitActivity(
        sha=sha,
        author_name=name or email.split("@")[0],
        author_email=email,
        committed_at=(timezone.now() - timedelta(days=days_ago)).isoformat(),
        paths=paths,
    )


def _fresh_row(team, area: str, contributors: list[dict] | None = None, **kwargs):
    with team_scope(team.id, canonical=True):
        return SignalRepositoryAreaActivity.objects.create(
            team=team,
            repository="acme/app",
            area=area,
            contributors=contributors
            or [
                {
                    "login": "alice",
                    "name": "Alice",
                    "commit_count": 5,
                    "last_commit_at": timezone.now().isoformat(),
                    "last_commit_sha": "e" * 7,
                    "last_commit_url": "https://github.com/acme/app/commit/eeeeeee",
                }
            ],
            refreshed_at=kwargs.pop("refreshed_at", timezone.now()),
            **kwargs,
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

    def test_fallback_chain_walks_up_to_repo_wide(self):
        assert area_fallback_chain("products/signals") == ["products/signals", "products", REPO_WIDE_AREA]
        assert area_fallback_chain("posthog") == ["posthog", REPO_WIDE_AREA]
        assert area_fallback_chain("") == ["", REPO_WIDE_AREA]


class FakeAttributionGitHub:
    """Stub of the commits-listing surface the rebuild joins against."""

    def __init__(self, by_sha: dict[str, tuple[str, bool]]):
        self.by_sha = by_sha

    def list_commit_attributions(self, repository, *, since, max_pages=60):
        return [
            GitHubCommitAttribution(sha=sha, login=login, is_bot=is_bot) for sha, (login, is_bot) in self.by_sha.items()
        ]


def _patch_attributions(by_sha: dict[str, tuple[str, bool]]):
    return patch(
        "products.signals.backend.report_generation.repo_activity.GitHubIntegration.first_for_team_repository",
        return_value=FakeAttributionGitHub(by_sha),
    )


@pytest.mark.django_db
class TestRebuildRepositoryActivity:
    def test_builds_area_map_joining_git_history_with_github_attribution(self, team):
        commits = [
            _commit("a" * 7, "whatever@anything.com", 2, ["products/signals/backend/models.py"]),
            _commit("b" * 7, "other@anything.com", 9, ["products/signals/frontend/App.tsx"]),
            _commit("c" * 7, "bob@example.com", 30, ["products/signals/backend/tasks.py", "posthog/models/user.py"]),
            _commit("d" * 7, "nobody@example.com", 1, ["products/signals/backend/views.py"]),
        ]
        attributions = {
            # identity comes from GitHub's sha attribution — the git emails above are noise
            "a" * 7: ("alice", False),
            "b" * 7: ("alice", False),
            "c" * 7: ("BobDev", False),
            # "d" is absent: GitHub couldn't attribute it, so it drops
        }

        with patch(_COLLECT_PATCH_TARGET, return_value=commits), _patch_attributions(attributions):
            rebuild_repository_activity(team.id, "acme/app")

        activity = get_area_activity(team.id, "acme/app", ["products/signals", "posthog/models"])

        signals_area = {c.login: c for c in activity["products/signals"]}
        # alice: both commits, latest one kept as evidence
        assert signals_area["alice"].commit_count == 2
        assert signals_area["alice"].last_commit_sha == "a" * 7
        # login lowercased
        assert signals_area["bobdev"].commit_count == 1
        assert [c.login for c in activity["posthog/models"]] == ["bobdev"]
        assert "nobody" not in signals_area

        # commits are also indexed at the parent and repo-wide levels for walk-up
        parents = get_area_activity(team.id, "acme/app", ["products", REPO_WIDE_AREA])
        assert {c.login for c in parents["products"]} == {"alice", "bobdev"}
        repo_wide = {c.login: c for c in parents[REPO_WIDE_AREA]}
        assert repo_wide["alice"].commit_count == 2
        assert repo_wide["bobdev"].commit_count == 1

    def test_bot_commits_are_excluded(self, team):
        commits = [
            _commit("a" * 7, "marius.andra@gmail.com", 3, ["frontend/src/notebooks/Notebook.tsx"]),
            _commit("b" * 7, "bot@example.com", 1, ["frontend/src/generated.ts"]),
        ]
        attributions = {
            "a" * 7: ("MariusAndra", False),
            "b" * 7: ("posthog[bot]", True),
        }

        with patch(_COLLECT_PATCH_TARGET, return_value=commits), _patch_attributions(attributions):
            rebuild_repository_activity(team.id, "acme/app")

        activity = get_area_activity(team.id, "acme/app", ["frontend/src"])
        assert [c.login for c in activity["frontend/src"]] == ["mariusandra"]

    def test_replaces_previous_map_and_empties_dead_areas(self, team):
        _fresh_row(team, "products/old", refreshed_at=timezone.now() - timedelta(days=30))

        commits = [_commit("a" * 7, "alice@example.com", 1, ["products/new/x.py"])]
        with patch(_COLLECT_PATCH_TARGET, return_value=commits), _patch_attributions({"a" * 7: ("alice", False)}):
            rebuild_repository_activity(team.id, "acme/app")

        with team_scope(team.id, canonical=True):
            old_row = SignalRepositoryAreaActivity.objects.get(repository="acme/app", area="products/old")
            new_row = SignalRepositoryAreaActivity.objects.get(repository="acme/app", area="products/new")
        # the dead area is refreshed-but-empty: "nobody is active", not "unknown"
        assert old_row.contributors == []
        assert old_row.refreshed_at is not None
        assert old_row.refreshed_at > timezone.now() - timedelta(minutes=1)
        assert [c["login"] for c in new_row.contributors] == ["alice"]


@pytest.mark.django_db
class TestGetAreaActivity:
    def test_reads_fresh_cache(self, team):
        _fresh_row(team, "products/signals")

        result = get_area_activity(team.id, "acme/app", ["products/signals"])

        assert [c.login for c in result["products/signals"]] == ["alice"]

    def test_missing_area_gets_placeholder_row_and_is_absent(self, team):
        result = get_area_activity(team.id, "acme/app", ["products/signals"])

        assert result == {}
        with team_scope(team.id, canonical=True):
            row = SignalRepositoryAreaActivity.objects.get(repository="acme/app", area="products/signals")
        assert row.refreshed_at is None

    def test_needs_rebuild_transitions(self, team):
        assert repository_activity_needs_rebuild(team.id, "acme/app") is True

        row = _fresh_row(team, "products/signals")
        assert repository_activity_needs_rebuild(team.id, "acme/app") is False

        with team_scope(team.id, canonical=True):
            SignalRepositoryAreaActivity.objects.filter(id=row.id).update(
                refreshed_at=timezone.now() - timedelta(days=30)
            )
        assert repository_activity_needs_rebuild(team.id, "acme/app") is True


@pytest.mark.django_db
class TestWeeklyRefreshTask:
    def test_enqueues_one_rebuild_per_repository_and_drops_idle_rows(self, team):
        now = timezone.now()
        with team_scope(team.id, canonical=True):
            SignalRepositoryAreaActivity.objects.create(
                team=team, repository="acme/app", area="a/one", last_used_at=now
            )
            SignalRepositoryAreaActivity.objects.create(
                team=team, repository="acme/app", area="a/two", last_used_at=now
            )
            SignalRepositoryAreaActivity.objects.create(
                team=team, repository="acme/other", area="b/one", last_used_at=now
            )
            idle = SignalRepositoryAreaActivity.objects.create(
                team=team, repository="acme/dead", area="c/one", last_used_at=now - timedelta(days=120)
            )

        with patch("products.signals.backend.tasks.rebuild_signal_repository_activity.delay") as delay:
            refresh_signal_repository_activity()

        enqueued = {(call.kwargs["team_id"], call.kwargs["repository"]) for call in delay.call_args_list}
        assert enqueued == {(team.id, "acme/app"), (team.id, "acme/other")}
        with team_scope(team.id, canonical=True):
            assert not SignalRepositoryAreaActivity.objects.filter(id=idle.id).exists()
