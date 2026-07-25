from collections import Counter
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.github_integration_base import GitHubCommitAuthor
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.user_integration import UserIntegration

from products.signals.backend.models import SignalRepositoryAreaActivity
from products.signals.backend.report_generation.repo_activity import ACTIVITY_WINDOW_DAYS, ContributorActivity
from products.signals.backend.report_generation.resolve_reviewers import (
    MAX_AREA_CONTRIBUTORS_FOR_OWNERSHIP,
    RECENCY_DECAY_FLOOR,
    RECENCY_FULL_WEIGHT_DAYS,
    STALE_BLAME_MULTIPLIER,
    _AreaContributor,
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

        scores = _score_candidates(weights, {})

        assert scores == {"old-timer": 10.0, "runner-up": 4.0}

    def test_recency_decays_blame_author_absent_from_the_area(self):
        # Both authored the relevant commits; only "active" has recent commits in the area.
        weights = Counter({"active": 10, "gone": 10})
        activity = {
            "active": _AreaContributor(
                name=None,
                commit_count=5,
                days_since_last_commit=2,
                last_commit_sha="a" * 7,
                last_commit_url="",
                area="products/signals",
            ),
        }

        scores = _score_candidates(weights, activity)

        assert scores["active"] == pytest.approx(10.0)
        assert scores["gone"] == pytest.approx(10.0 * STALE_BLAME_MULTIPLIER)

    def test_non_authors_are_never_scored(self):
        # The area is active, but only people who authored a relevant commit are candidates:
        # a nearby-active bystander is not invented into the reviewer set.
        weights = Counter({"author": 4})
        activity = {
            "author": _AreaContributor(
                name=None,
                commit_count=3,
                days_since_last_commit=1,
                last_commit_sha="a" * 7,
                last_commit_url="",
                area="products/signals",
            ),
            "busy-bystander": _AreaContributor(
                name=None,
                commit_count=50,
                days_since_last_commit=0,
                last_commit_sha="b" * 7,
                last_commit_url="",
                area="products/signals",
            ),
        }

        scores = _score_candidates(weights, activity)

        assert set(scores) == {"author"}


def _seed_area_row(team: Team, area: str, logins: list[str]) -> None:
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


@pytest.mark.django_db
class TestAreaWalkUp:
    def test_empty_area_falls_back_to_parent_not_repo_wide(self, team):
        with team_scope(team.id, canonical=True):
            _seed_area_row(team, "products/dead", [])  # refreshed, nobody active
            _seed_area_row(team, "products", ["parent-owner"])
            _seed_area_row(team, "*", ["repo-regular"])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            merged = _relevant_area_activity(team.id, "acme/app", ["products/dead/models.py"])

        # the dead area walks up to its parent
        assert set(merged) == {"parent-owner"}
        assert merged["parent-owner"].area == "products"

        # with the parent empty too, the repo-wide bucket is not a fallback: no ownership signal
        with team_scope(team.id, canonical=True):
            SignalRepositoryAreaActivity.objects.filter(area="products").update(contributors=[])
        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            merged = _relevant_area_activity(team.id, "acme/app", ["products/dead/models.py"])

        assert merged == {}

    def test_broad_area_is_skipped_as_a_catch_all(self, team):
        # A source root with more committers than an area can meaningfully be owned by.
        busy = [f"gen{i}" for i in range(MAX_AREA_CONTRIBUTORS_FOR_OWNERSHIP + 1)]
        with team_scope(team.id, canonical=True):
            _seed_area_row(team, "frontend/src", busy)
            _seed_area_row(team, "frontend", ["frontend-owner"])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            merged = _relevant_area_activity(team.id, "acme/app", ["frontend/src/lib/api.ts"])

        # none of the catch-all committers are ownership candidates; it walks up to the parent
        assert set(merged) == {"frontend-owner"}


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

    def test_only_agent_proposed_candidates_are_ranked(self, team):
        # "bystander" is the busiest person in the area but the agent did not propose them,
        # so they are not added to the ranking.
        self._seed_area(team, "products/signals", [("agent-pick", 5, 3), ("bystander", 12, 1)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(
                team.id, "acme/app", ["agent-pick"], ["products/signals/backend/models.py"]
            )

        assert [candidate.login for candidate in ranked] == ["agent-pick"]

    def test_paths_alone_yield_nothing(self, team):
        # No agent-proposed candidates: area activity alone never invents an assignee.
        self._seed_area(team, "products/signals", [("area-owner", 8, 1)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(team.id, "acme/app", [], ["products/signals/backend/models.py"])

        assert ranked == []

    def test_no_activity_data_returns_agent_order(self, team):
        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(
                team.id, "acme/app", ["first-pick", "second-pick"], ["products/signals/backend/models.py"]
            )

        assert [candidate.login for candidate in ranked] == ["first-pick", "second-pick"]


@pytest.mark.django_db
class TestResolveSuggestedReviewersEndToEnd:
    def test_only_commit_authors_are_suggested(self, team):
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

        # Only the commit author is suggested; the nearby-active non-author is never invented in.
        assert [r.login for r in reviewers] == ["old-timer"]
        assert reviewers[0].commits[0].sha == "d" * 7
