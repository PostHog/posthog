from collections import Counter
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.github_integration_base import GitHubCommitAuthor
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.user_integration import UserIntegration

from products.signals.backend.models import SignalRepositoryAreaActivity
from products.signals.backend.report_generation.repo_activity import (
    ACTIVITY_WINDOW_DAYS,
    MAX_AREA_FILLIN_BREADTH,
    ContributorActivity,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    RECENCY_DECAY_FLOOR,
    RECENCY_FULL_WEIGHT_DAYS,
    STALE_BLAME_MULTIPLIER,
    _AreaContributor,
    _rank_scored_candidates,
    _recency_multiplier,
    _relevant_area_activity,
    _score_candidates,
    rank_assignee_candidates,
    resolve_org_github_login_to_users,
    resolve_suggested_reviewers,
)


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-resolve-reviewers-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-resolve-reviewers-team")


def _create_org_member(email: str, organization: Organization) -> User:
    user = User.objects.create(email=email)
    OrganizationMembership.objects.create(user=user, organization=organization)
    return user


def _make_social_auth(user: User, team: Team, login: str) -> None:
    UserSocialAuth.objects.create(user=user, provider="github", uid="github-social-1", extra_data={"login": login})


def _make_user_integration(user: User, team: Team, login: str) -> None:
    UserIntegration.objects.create(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id="user-int-1",
        config={"installation_id": "user-int-1", "github_user": {"login": login}},
        sensitive_config={},
    )


def _make_team_integration(user: User, team: Team, login: str) -> None:
    Integration.objects.create(
        team=team,
        kind="github",
        integration_id="team-int-1",
        config={"installation_id": "team-int-1", "connecting_user_github_login": login},
        sensitive_config={},
        created_by=user,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("identity_source", "create_identity", "stored_login"),
    [
        ("social_auth", _make_social_auth, "OctoCat"),
        ("user_integration", _make_user_integration, "MixedCase"),
        ("team_integration", _make_team_integration, "TeamConnector"),
    ],
)
def test_resolves_login_across_identity_sources(organization, team, identity_source, create_identity, stored_login):
    user = _create_org_member(f"{identity_source}@example.com", organization)
    create_identity(user, team, stored_login)

    lookup = stored_login.lower()
    result = resolve_org_github_login_to_users(team.id, [lookup])

    assert set(result.keys()) == {lookup}
    assert result[lookup].id == user.id


@pytest.mark.django_db
def test_returns_empty_when_no_match(organization, team):
    user = _create_org_member("nomatch@example.com", organization)
    UserSocialAuth.objects.create(
        user=user,
        provider="github",
        uid="github-nomatch",
        extra_data={"login": "someone"},
    )

    result = resolve_org_github_login_to_users(team.id, ["different-login"])

    assert result == {}


@pytest.mark.django_db
def test_skips_users_outside_organization(organization, team):
    other_org = Organization.objects.create(name="test-resolve-reviewers-other-org")
    try:
        outside_user = User.objects.create(email="outside@example.com")
        OrganizationMembership.objects.create(user=outside_user, organization=other_org)
        UserSocialAuth.objects.create(
            user=outside_user,
            provider="github",
            uid="github-outside",
            extra_data={"login": "outsider"},
        )

        result = resolve_org_github_login_to_users(team.id, ["outsider"])

        assert result == {}
    finally:
        other_org.delete()


# ── recency-aware scoring ─────────────────────────────────────────────────────


class TestRecencyScoring:
    def test_recency_multiplier_shape(self):
        assert _recency_multiplier(None) == STALE_BLAME_MULTIPLIER
        assert _recency_multiplier(0) == 1.0
        assert _recency_multiplier(RECENCY_FULL_WEIGHT_DAYS) == 1.0
        assert _recency_multiplier(ACTIVITY_WINDOW_DAYS) == STALE_BLAME_MULTIPLIER
        assert _recency_multiplier(ACTIVITY_WINDOW_DAYS + 100) == STALE_BLAME_MULTIPLIER
        midpoint = (RECENCY_FULL_WEIGHT_DAYS + ACTIVITY_WINDOW_DAYS) / 2
        assert _recency_multiplier(midpoint) == pytest.approx((1.0 + RECENCY_DECAY_FLOOR) / 2)

    def test_no_activity_data_keeps_blame_weights(self):
        weights = Counter({"old-timer": 10, "runner-up": 4})

        scores = _score_candidates(weights, {}, {})

        assert scores == {"old-timer": 10.0, "runner-up": 4.0}

    def test_stale_blame_author_loses_to_active_area_contributor(self):
        weights = Counter({"old-timer": 10})
        activity = {
            "active-owner": _AreaContributor(
                name="Active Owner",
                commit_count=12,
                days_since_last_commit=2,
                last_commit_sha="a" * 7,
                last_commit_url="https://github.com/acme/app/commit/aaaaaaa",
                area="products/signals",
            ),
        }

        scores = _score_candidates(weights, activity, activity)

        # old-timer authored the blame commits but has no recent commits in the area.
        assert scores["active-owner"] > scores["old-timer"]

    def test_recently_active_blame_author_beats_activity_only_contributor(self):
        def contributor(days_since: float) -> _AreaContributor:
            return _AreaContributor(
                name=None,
                commit_count=12,
                days_since_last_commit=days_since,
                last_commit_sha="b" * 7,
                last_commit_url="https://github.com/acme/app/commit/bbbbbbb",
                area="products/signals",
            )

        weights = Counter({"active-author": 10})
        activity = {
            "active-author": contributor(days_since=5),
            "bystander": contributor(days_since=1),
        }

        scores = _score_candidates(weights, activity, activity)

        assert scores["active-author"] > scores["bystander"]

    def test_lightly_active_contributor_beats_stale_blame_even_with_tiny_blame_weight(self):
        # Regression: a single old blame commit (weight 1) used to crush activity-only
        # candidates via the cap, so the long-gone author still won the assign.
        weights = Counter({"long-gone": 1})
        activity = {
            "light-owner": _AreaContributor(
                name=None,
                commit_count=3,
                days_since_last_commit=1,
                last_commit_sha="c" * 7,
                last_commit_url="",
                area="posthog/migrations",
            ),
        }

        scores = _score_candidates(weights, activity, activity)

        assert scores["light-owner"] > scores["long-gone"]

    def test_half_stale_bystander_does_not_beat_stale_blame(self):
        weights = Counter({"long-gone": 1})
        activity = {
            "half-stale": _AreaContributor(
                name=None,
                commit_count=3,
                days_since_last_commit=70,
                last_commit_sha="c" * 7,
                last_commit_url="",
                area="posthog/migrations",
            ),
        }

        scores = _score_candidates(weights, activity, activity)

        assert scores["long-gone"] >= scores["half-stale"]


@pytest.mark.django_db
class TestAreaWalkUp:
    def _row(self, team, area: str, logins: list[str]) -> None:
        SignalRepositoryAreaActivity.objects.create(
            team=team,
            repository="acme/app",
            area=area,
            contributors=[
                {
                    "login": login,
                    "name": login.title(),
                    "commit_count": 3,
                    "last_commit_at": timezone.now().isoformat(),
                    "last_commit_sha": "a" * 7,
                    "last_commit_url": "https://github.com/acme/app/commit/aaaaaaa",
                }
                for login in logins
            ],
            refreshed_at=timezone.now(),
        )

    def test_empty_area_falls_back_to_parent_only(self, team):
        with team_scope(team.id, canonical=True):
            self._row(team, "products/dead", [])  # refreshed, nobody active
            self._row(team, "products", ["parent-owner"])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            full, gated = _relevant_area_activity(team.id, "acme/app", ["products/dead/models.py"])

        # the dead area walks up to its parent; there is no further, repo-wide level.
        assert set(full) == {"parent-owner"}
        assert full["parent-owner"].area == "products"
        assert set(gated) == {"parent-owner"}

        with team_scope(team.id, canonical=True):
            SignalRepositoryAreaActivity.objects.filter(area="products").update(contributors=[])
        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            full, gated = _relevant_area_activity(team.id, "acme/app", ["products/dead/models.py"])

        # the parent is empty too now, and there is nowhere further to walk up to.
        assert full == {}
        assert gated == {}

    def test_area_over_breadth_threshold_yields_no_gated_fillins(self, team):
        busy_logins = [f"contributor-{i}" for i in range(MAX_AREA_FILLIN_BREADTH + 1)]
        with team_scope(team.id, canonical=True):
            self._row(team, "frontend/src", busy_logins)

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            full, gated = _relevant_area_activity(team.id, "acme/app", ["frontend/src/index.tsx"])

        # a blame author's own recency still reads from the full (ungated) view...
        assert set(full) == set(busy_logins)
        # ...but the area is too broad to hand out fill-in candidates.
        assert gated == {}

    def test_gate_applies_at_every_walk_up_level(self, team):
        busy_logins = [f"contributor-{i}" for i in range(MAX_AREA_FILLIN_BREADTH + 1)]
        with team_scope(team.id, canonical=True):
            self._row(team, "products/dead", [])  # own area empty
            self._row(team, "products", busy_logins)  # parent is also too broad

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            _full, gated = _relevant_area_activity(team.id, "acme/app", ["products/dead/models.py"])

        # walking up to a parent that also fails the gate yields nothing from that level.
        assert gated == {}

    def test_catchall_area_excluded_while_small_touched_area_stays_gated(self, team):
        busy_logins = [f"contributor-{i}" for i in range(MAX_AREA_FILLIN_BREADTH + 1)]
        with team_scope(team.id, canonical=True):
            self._row(team, "frontend/src", busy_logins)
            self._row(team, "products/subscriptions", ["small-area-owner"])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            _full, gated = _relevant_area_activity(
                team.id,
                "acme/app",
                ["frontend/src/index.tsx", "products/subscriptions/models.py"],
            )

        # the catch-all area contributes nothing; the small, genuinely-owned area still does.
        assert set(gated) == {"small-area-owner"}


class TestBlameAuthorProtection:
    def test_low_share_blame_author_in_gated_area_not_displaced_by_fillin(self):
        # robbie-c case: a long-time in-area owner with only one relevant (low-weight) blame
        # commit must still make the cut over busier activity-only fill-ins from the same
        # gated area — the fill-in cap alone doesn't protect a low blame-weight author from
        # being pushed out of the top 3 by score.
        login_weights = Counter({"top-author": 15, "robbie-c": 1})
        gated_activity = {
            "top-author": _AreaContributor(
                name="Top Author",
                commit_count=20,
                days_since_last_commit=1,
                last_commit_sha="t" * 7,
                last_commit_url="https://github.com/acme/app/commit/ttttttt",
                area="products/hogql",
            ),
            "robbie-c": _AreaContributor(
                name="Robbie C",
                commit_count=1,
                days_since_last_commit=10,
                last_commit_sha="r" * 7,
                last_commit_url="https://github.com/acme/app/commit/rrrrrrr",
                area="products/hogql",
            ),
            "fillin-a": _AreaContributor(
                name="Fillin A",
                commit_count=10,
                days_since_last_commit=1,
                last_commit_sha="a" * 7,
                last_commit_url="https://github.com/acme/app/commit/aaaaaaa",
                area="products/hogql",
            ),
            "fillin-b": _AreaContributor(
                name="Fillin B",
                commit_count=3,
                days_since_last_commit=1,
                last_commit_sha="b" * 7,
                last_commit_url="https://github.com/acme/app/commit/bbbbbbb",
                area="products/hogql",
            ),
        }

        reviewers = _rank_scored_candidates(login_weights, gated_activity, gated_activity, {}, {})

        # the top blame author is never displaced, robbie-c reclaims the weakest fill-in's
        # seat, and the busier-but-lower-scored fill-in is the one that gets dropped.
        assert [r.login for r in reviewers] == ["top-author", "fillin-a", "robbie-c"]


class TestFillinTieBreak:
    @parameterized.expand(
        [
            (
                "area_specificity_beats_alphabet",
                _AreaContributor(
                    name=None,
                    commit_count=5,
                    days_since_last_commit=5,
                    last_commit_sha="",
                    last_commit_url="",
                    area="products",
                ),
                _AreaContributor(
                    name=None,
                    commit_count=5,
                    days_since_last_commit=5,
                    last_commit_sha="",
                    last_commit_url="",
                    area="products/signals",
                ),
            ),
            (
                "recency_beats_alphabet",
                _AreaContributor(
                    name=None,
                    commit_count=5,
                    days_since_last_commit=20,
                    last_commit_sha="",
                    last_commit_url="",
                    area="products/signals",
                ),
                _AreaContributor(
                    name=None,
                    commit_count=5,
                    days_since_last_commit=5,
                    last_commit_sha="",
                    last_commit_url="",
                    area="products/signals",
                ),
            ),
            (
                "commit_count_beats_alphabet",
                _AreaContributor(
                    name=None,
                    commit_count=12,
                    days_since_last_commit=5,
                    last_commit_sha="",
                    last_commit_url="",
                    area="products/signals",
                ),
                _AreaContributor(
                    name=None,
                    commit_count=20,
                    days_since_last_commit=5,
                    last_commit_sha="",
                    last_commit_url="",
                    area="products/signals",
                ),
            ),
        ]
    )
    def test_equal_score_fillins_break_ties_by_specificity_then_recency_then_commit_count(
        self, _criterion, aaa_contributor, zzz_contributor
    ):
        # In every case below "aaa-candidate" and "zzz-candidate" score identically, so a plain
        # alphabetical tie-break would pick "aaa-candidate" — the new tie-break chain must pick
        # "zzz-candidate" instead, for the reason named by each case.
        gated_activity = {"aaa-candidate": aaa_contributor, "zzz-candidate": zzz_contributor}

        reviewers = _rank_scored_candidates(Counter(), gated_activity, gated_activity, {}, {})

        assert reviewers[0].login == "zzz-candidate"


@pytest.mark.django_db
class TestRankAssigneeCandidates:
    def _seed_area(self, team, area: str, entries: list[tuple[str, int, int]]) -> None:
        with team_scope(team.id, canonical=True):
            SignalRepositoryAreaActivity.objects.create(
                team=team,
                repository="acme/app",
                area=area,
                contributors=[
                    {
                        "login": login,
                        "name": login.title(),
                        "commit_count": count,
                        "last_commit_at": (timezone.now() - timedelta(days=days_ago)).isoformat(),
                        "last_commit_sha": "a" * 7,
                        "last_commit_url": "https://github.com/acme/app/commit/aaaaaaa",
                    }
                    for login, count, days_ago in entries
                ],
                refreshed_at=timezone.now(),
            )

    def test_stale_agent_candidate_demoted_below_active_area_owner(self, team):
        self._seed_area(team, "products/signals", [("active-owner", 12, 2)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(
                team.id, "acme/app", ["old-timer"], ["products/signals/backend/models.py"]
            )

        assert [candidate.login for candidate in ranked] == ["active-owner", "old-timer"]
        # activity-only candidate carries generated evidence; the agent candidate keeps none
        assert "Recently active in `products/signals`" in ranked[0].commits[0].reason
        assert ranked[1].commits == []

    def test_active_agent_candidate_keeps_top_spot(self, team):
        self._seed_area(team, "products/signals", [("agent-pick", 5, 3), ("bystander", 12, 1)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(
                team.id, "acme/app", ["agent-pick"], ["products/signals/backend/models.py"]
            )

        assert ranked[0].login == "agent-pick"

    def test_paths_alone_yield_activity_candidates(self, team):
        self._seed_area(team, "products/signals", [("area-owner", 8, 1)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(team.id, "acme/app", [], ["products/signals/backend/models.py"])

        assert [candidate.login for candidate in ranked] == ["area-owner"]

    def test_no_activity_data_returns_agent_order(self, team):
        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(
                team.id, "acme/app", ["first-pick", "second-pick"], ["products/signals/backend/models.py"]
            )

        assert [candidate.login for candidate in ranked] == ["first-pick", "second-pick"]


@pytest.mark.django_db
class TestResolveSuggestedReviewersEndToEnd:
    def test_stale_blame_author_demoted_and_active_owner_suggested(self, team):
        class FakeGitHub:
            def get_commit_author_info(self, repository, sha):
                return GitHubCommitAuthor(
                    login="old-timer",
                    name="Old Timer",
                    commit_url=f"https://github.com/acme/app/commit/{sha}",
                    file_paths=("products/signals/backend/models.py",),
                )

        activity = {
            "products/signals": [
                ContributorActivity(
                    login="active-owner",
                    name="Active Owner",
                    commit_count=15,
                    last_commit_at=timezone.now() - timedelta(days=2),
                    last_commit_sha="c" * 7,
                    last_commit_url="https://github.com/acme/app/commit/ccccccc",
                ),
            ]
        }

        with (
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.GitHubIntegration.first_for_team_repository",
                return_value=FakeGitHub(),
            ),
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.get_area_activity",
                return_value=activity,
            ),
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.repository_activity_needs_rebuild",
                return_value=False,
            ),
        ):
            reviewers = resolve_suggested_reviewers(team.id, "acme/app", {"d" * 7: "introduced the bug"})

        assert [r.login for r in reviewers] == ["active-owner", "old-timer"]
        # The activity-only candidate carries their latest area commit as evidence.
        assert reviewers[0].commits[0].sha == "c" * 7
        assert "Recently active in `products/signals`" in reviewers[0].commits[0].reason
        # The blame author keeps their blame commit evidence, just demoted.
        assert reviewers[1].commits[0].sha == "d" * 7

    def test_catchall_area_excluded_while_small_touched_area_stays_gated(self, team):
        by_sha = {
            "a" * 7: GitHubCommitAuthor(
                login="blame-author-1",
                name="Blame One",
                commit_url="https://github.com/acme/app/commit/aaaaaaa",
                file_paths=("frontend/src/App.tsx",),
            ),
            "b" * 7: GitHubCommitAuthor(
                login="blame-author-2",
                name="Blame Two",
                commit_url="https://github.com/acme/app/commit/bbbbbbb",
                file_paths=("products/subscriptions/models.py",),
            ),
        }

        class FakeGitHub:
            def get_commit_author_info(self, repository, sha):
                return by_sha[sha]

        busy_contributors = [
            ContributorActivity(
                login=f"busy-{i}",
                name=f"Busy {i}",
                commit_count=5,
                last_commit_at=timezone.now() - timedelta(days=1),
                last_commit_sha="x" * 7,
                last_commit_url="https://github.com/acme/app/commit/xxxxxxx",
            )
            for i in range(MAX_AREA_FILLIN_BREADTH + 1)
        ]
        activity = {
            "frontend/src": busy_contributors,
            "products/subscriptions": [
                ContributorActivity(
                    login="small-owner",
                    name="Small Owner",
                    commit_count=5,
                    last_commit_at=timezone.now() - timedelta(days=1),
                    last_commit_sha="s" * 7,
                    last_commit_url="https://github.com/acme/app/commit/sssssss",
                ),
            ],
        }

        with (
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.GitHubIntegration.first_for_team_repository",
                return_value=FakeGitHub(),
            ),
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.get_area_activity",
                return_value=activity,
            ),
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.repository_activity_needs_rebuild",
                return_value=False,
            ),
        ):
            reviewers = resolve_suggested_reviewers(
                team.id, "acme/app", {"a" * 7: "touched frontend", "b" * 7: "touched subscriptions"}
            )

        logins = [r.login for r in reviewers]
        assert set(logins) == {"blame-author-1", "blame-author-2", "small-owner"}
        assert "busy-0" not in logins

    def test_fewer_than_three_suggestions_when_only_two_genuine_candidates(self, team):
        by_sha = {
            "a" * 7: GitHubCommitAuthor(
                login="author-a",
                name="Author A",
                commit_url="https://github.com/acme/app/commit/aaaaaaa",
                file_paths=("products/signals/backend/models.py",),
            ),
            "b" * 7: GitHubCommitAuthor(
                login="author-b",
                name="Author B",
                commit_url="https://github.com/acme/app/commit/bbbbbbb",
                file_paths=("products/signals/backend/tasks.py",),
            ),
        }

        class FakeGitHub:
            def get_commit_author_info(self, repository, sha):
                return by_sha[sha]

        with (
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.GitHubIntegration.first_for_team_repository",
                return_value=FakeGitHub(),
            ),
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.get_area_activity",
                return_value={},
            ),
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.repository_activity_needs_rebuild",
                return_value=False,
            ),
        ):
            reviewers = resolve_suggested_reviewers(
                team.id, "acme/app", {"a" * 7: "introduced the bug", "b" * 7: "adjacent change"}
            )

        # no repo-wide (or any other) pool exists to pad a third seat out of thin air.
        assert [r.login for r in reviewers] == ["author-a", "author-b"]

    def test_all_bot_commits_with_no_gated_area_returns_empty(self, team):
        class FakeGitHub:
            def get_commit_author_info(self, repository, sha):
                return GitHubCommitAuthor(
                    login="posthog-bot",
                    name="PostHog Bot",
                    commit_url=f"https://github.com/acme/app/commit/{sha}",
                    file_paths=("products/signals/backend/models.py",),
                    is_bot=True,
                )

        with (
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.GitHubIntegration.first_for_team_repository",
                return_value=FakeGitHub(),
            ),
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.get_area_activity",
                return_value={},
            ),
            patch(
                "products.signals.backend.report_generation.resolve_reviewers.repository_activity_needs_rebuild",
                return_value=False,
            ),
        ):
            reviewers = resolve_suggested_reviewers(team.id, "acme/app", {"d" * 7: "bot-authored change"})

        assert reviewers == []
