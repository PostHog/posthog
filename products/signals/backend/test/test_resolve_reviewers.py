from collections import Counter
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from social_django.models import UserSocialAuth

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models import Organization, Team, User
from posthog.models.github_integration_base import GitHubCommitAuthor
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.user_integration import UserIntegration

from products.signals.backend.models import SignalRepositoryAreaActivity
from products.signals.backend.report_generation.repo_activity import ACTIVITY_WINDOW_DAYS, ContributorActivity
from products.signals.backend.report_generation.resolve_reviewers import (
    MAX_CONTRIBUTORS_FOR_OWNERSHIP,
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
    resolve_suggested_reviewers_with_diagnostics,
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


def _area_contributor(
    *,
    days_since_last_commit: float,
    commit_count: int = 12,
    is_likely_owner_of_area: bool = True,
) -> _AreaContributor:
    return _AreaContributor(
        name=None,
        commit_count=commit_count,
        days_since_last_commit=days_since_last_commit,
        last_commit_sha="a" * 7,
        last_commit_url="https://github.com/acme/app/commit/aaaaaaa",
        area="products/signals",
        is_likely_owner_of_area=is_likely_owner_of_area,
    )


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

    def test_stale_blame_author_loses_to_active_area_contributor(self):
        weights = Counter({"old-timer": 10})
        activity = {"active-owner": _area_contributor(days_since_last_commit=2)}

        scores = _score_candidates(weights, activity)

        # old-timer authored the blame commits but has no recent commits in the area.
        assert scores["active-owner"] > scores["old-timer"]

    def test_active_blame_author_suppresses_activity_only_candidates(self):
        weights = Counter({"active-author": 10})
        activity = {
            "active-author": _area_contributor(days_since_last_commit=5),
            "bystander": _area_contributor(days_since_last_commit=1),
        }

        scores = _score_candidates(weights, activity)

        # The blame author is the live reviewer, so the fresher bystander is not proposed.
        assert set(scores) == {"active-author"}

    def test_lightly_active_contributor_beats_stale_blame_even_with_tiny_blame_weight(self):
        # Regression: a single old blame commit (weight 1) used to crush activity-only
        # candidates via the cap, so the long-gone author still won the assign.
        weights = Counter({"long-gone": 1})
        activity = {"light-owner": _area_contributor(days_since_last_commit=1, commit_count=3)}

        scores = _score_candidates(weights, activity)

        assert scores["light-owner"] > scores["long-gone"]

    def test_crowded_area_nominates_nobody_but_still_decays_blame(self):
        weights = Counter({"old-timer": 10})
        # The blame author is past the window, so only the crowded area keeps the stranger out —
        # even with the crowd fallback allowed, since a blame candidate exists.
        activity = {
            "old-timer": _area_contributor(
                days_since_last_commit=ACTIVITY_WINDOW_DAYS + 5, is_likely_owner_of_area=False
            ),
            "prolific-stranger": _area_contributor(days_since_last_commit=1, is_likely_owner_of_area=False),
        }

        scores = _score_candidates(weights, activity, allow_crowd_fallback=True)

        assert set(scores) == {"old-timer"}
        assert scores["old-timer"] < 10.0

    @pytest.mark.parametrize(
        ("allow_crowd_fallback", "expected_logins"),
        [(True, {"crowd-regular", "crowd-passerby"}), (False, set())],
    )
    def test_crowd_fallback_fires_only_on_the_reviewer_path(self, allow_crowd_fallback, expected_logins):
        # No blame candidate at all and no focused area: the pipeline reviewer path must
        # propose the crowd's contributors rather than nobody, while the agent re-ranking
        # path must keep returning nothing so the agent's own judgment wins.
        activity = {
            "crowd-regular": _area_contributor(days_since_last_commit=1, is_likely_owner_of_area=False),
            "crowd-passerby": _area_contributor(
                days_since_last_commit=5, commit_count=2, is_likely_owner_of_area=False
            ),
        }

        scores = _score_candidates(Counter(), activity, allow_crowd_fallback=allow_crowd_fallback)

        assert set(scores) == expected_logins

    def test_half_stale_bystander_does_not_beat_stale_blame(self):
        weights = Counter({"long-gone": 1})
        activity = {"half-stale": _area_contributor(days_since_last_commit=70, commit_count=3)}

        scores = _score_candidates(weights, activity)

        assert scores["long-gone"] >= scores["half-stale"]


def _seed_area(team: Team, area: str, entries: list[tuple[str, int, int]]) -> None:
    """Seed one refreshed area row from (login, commit_count, days_ago) entries."""
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


@pytest.mark.django_db
class TestAreaWalkUp:
    def test_empty_area_falls_back_to_parent_then_repo_wide(self, team):
        _seed_area(team, "products/dead", [])  # refreshed, nobody active
        _seed_area(team, "products", [("parent-owner", 3, 0)])
        _seed_area(team, "*", [("repo-regular", 3, 0)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            merged = _relevant_area_activity(team.id, "acme/app", ["products/dead/models.py"])

        # the dead area walks up to its parent; repo-wide stays in reserve
        assert set(merged) == {"parent-owner"}
        assert merged["parent-owner"].area == "products"

        with team_scope(team.id, canonical=True):
            SignalRepositoryAreaActivity.objects.filter(area="products").update(contributors=[])
        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            merged = _relevant_area_activity(team.id, "acme/app", ["products/dead/models.py"])

        assert set(merged) == {"repo-regular"}

    @pytest.mark.parametrize(
        ("contributor_count", "is_likely_owner_of_area"),
        [(MAX_CONTRIBUTORS_FOR_OWNERSHIP, True), (MAX_CONTRIBUTORS_FOR_OWNERSHIP + 1, False)],
    )
    def test_ownership_needs_a_focused_area(self, team, contributor_count, is_likely_owner_of_area):
        _seed_area(team, "products/tasks", [(f"dev-{i}", 3, 0) for i in range(contributor_count)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            merged = _relevant_area_activity(team.id, "acme/app", ["products/tasks/management/commands/demo.py"])

        assert len(merged) == contributor_count
        assert all(contributor.is_likely_owner_of_area is is_likely_owner_of_area for contributor in merged.values())

    def test_fresher_crowded_commit_does_not_erase_focused_area_ownership(self, team):
        _seed_area(team, "products/signals", [("alice", 4, 10)])
        _seed_area(
            team,
            "*",
            [("alice", 9, 1), *[(f"dev-{i}", 3, 2) for i in range(MAX_CONTRIBUTORS_FOR_OWNERSHIP)]],
        )

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            merged = _relevant_area_activity(
                team.id, "acme/app", ["products/signals/backend/models.py", "bin/deploy.sh"]
            )

        # Evidence still follows alice's freshest commit, which landed repo-wide...
        assert merged["alice"].area == "*"
        assert merged["alice"].days_since_last_commit == pytest.approx(1, abs=0.01)
        # ...but the claim she earned in products/signals survives it.
        assert merged["alice"].is_likely_owner_of_area
        assert not merged["dev-0"].is_likely_owner_of_area


@pytest.mark.django_db
class TestRankAssigneeCandidates:
    def test_stale_agent_candidate_demoted_below_active_area_owner(self, team):
        _seed_area(team, "products/signals", [("active-owner", 12, 2)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(
                team.id, "acme/app", ["old-timer"], ["products/signals/backend/models.py"]
            )

        # The agent candidate is not active in the area, so the area owner is kept as the
        # fallback and outranks it.
        assert [candidate.login for candidate in ranked] == ["active-owner", "old-timer"]
        assert "Recently active in `products/signals`" in ranked[0].commits[0].reason
        assert ranked[1].commits == []

    def test_active_agent_candidate_keeps_top_spot(self, team):
        _seed_area(team, "products/signals", [("agent-pick", 5, 3), ("bystander", 12, 1)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(
                team.id, "acme/app", ["agent-pick"], ["products/signals/backend/models.py"]
            )

        # The agent candidate is itself active in the area, so the active bystander is not
        # padded in as a fallback — only the real candidate is returned.
        assert [candidate.login for candidate in ranked] == ["agent-pick"]

    def test_paths_alone_yield_activity_candidates(self, team):
        _seed_area(team, "products/signals", [("area-owner", 8, 1)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(team.id, "acme/app", [], ["products/signals/backend/models.py"])

        assert [candidate.login for candidate in ranked] == ["area-owner"]

    def test_no_activity_data_returns_agent_order(self, team):
        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(
                team.id, "acme/app", ["first-pick", "second-pick"], ["products/signals/backend/models.py"]
            )

        assert [candidate.login for candidate in ranked] == ["first-pick", "second-pick"]

    def test_no_candidates_and_crowded_area_returns_nothing(self, team):
        # The agent path must not inherit the reviewer path's crowd fallback: when the agent
        # deliberately proposed nobody and only a crowded area is cached, an empty result
        # lets the caller keep the agent's judgment.
        _seed_area(team, "products/signals", [(f"dev-{i}", 3, 1) for i in range(MAX_CONTRIBUTORS_FOR_OWNERSHIP + 1)])

        with patch("products.signals.backend.report_generation.resolve_reviewers._schedule_activity_rebuild"):
            ranked = rank_assignee_candidates(team.id, "acme/app", [], ["products/signals/backend/models.py"])

        assert ranked == []


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

        # The blame author has no current area activity, so the active area owner is kept as the
        # fallback and outranks them.
        assert [r.login for r in reviewers] == ["active-owner", "old-timer"]
        assert reviewers[0].commits[0].sha == "c" * 7
        assert "Recently active in `products/signals`" in reviewers[0].commits[0].reason
        assert reviewers[1].commits[0].sha == "d" * 7

    def test_activity_only_owner_not_added_when_blame_author_is_active(self, team):
        class FakeGitHub:
            def get_commit_author_info(self, repository, sha):
                return GitHubCommitAuthor(
                    login="active-author",
                    name="Active Author",
                    commit_url=f"https://github.com/acme/app/commit/{sha}",
                    file_paths=("products/signals/backend/models.py",),
                )

        # The blame author is themselves currently active in the area (a live reviewer), so the
        # separate area owner must not be padded in as a fallback.
        activity = {
            "products/signals": [
                ContributorActivity(
                    login="active-author",
                    name="Active Author",
                    commit_count=9,
                    last_commit_at=timezone.now() - timedelta(days=2),
                    last_commit_sha="a" * 7,
                    last_commit_url="https://github.com/acme/app/commit/aaaaaaa",
                ),
                ContributorActivity(
                    login="area-owner",
                    name="Area Owner",
                    commit_count=15,
                    last_commit_at=timezone.now() - timedelta(days=1),
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

        assert [r.login for r in reviewers] == ["active-author"]
        assert reviewers[0].commits[0].sha == "d" * 7

    def test_bot_only_blame_in_crowded_area_still_proposes_contributors(self, team):
        # The production regression this guards: every finding commit is bot-authored, and the
        # only cached activity level is too crowded to imply ownership (a monorepo norm), so
        # the resolver used to return nobody and the report went unrouted.
        class FakeGitHub:
            def get_commit_author_info(self, repository, sha):
                return GitHubCommitAuthor(
                    login="release-bot",
                    name="Release Bot",
                    commit_url=f"https://github.com/acme/app/commit/{sha}",
                    file_paths=("products/signals/backend/models.py",),
                    is_bot=True,
                )

        activity = {
            "products/signals": [
                ContributorActivity(
                    login=f"dev-{i}",
                    name=f"Dev {i}",
                    commit_count=MAX_CONTRIBUTORS_FOR_OWNERSHIP + 1 - i,
                    last_commit_at=timezone.now() - timedelta(days=1),
                    last_commit_sha="c" * 7,
                    last_commit_url="https://github.com/acme/app/commit/ccccccc",
                )
                for i in range(MAX_CONTRIBUTORS_FOR_OWNERSHIP + 1)
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

        # Ties on score break by commit count, so the crowd's most active contributors surface.
        assert [r.login for r in reviewers] == ["dev-0", "dev-1", "dev-2"]
        assert "Recently active in `products/signals`" in reviewers[0].commits[0].reason

    def test_stale_cached_blame_author_does_not_suppress_fresh_owner(self, team):
        class FakeGitHub:
            def get_commit_author_info(self, repository, sha):
                return GitHubCommitAuthor(
                    login="aged-author",
                    name="Aged Author",
                    commit_url=f"https://github.com/acme/app/commit/{sha}",
                    file_paths=("products/signals/backend/models.py",),
                )

        # The blame author is in the area cache but their last commit has aged past the window
        # (the cache is served while a rebuild is scheduled). They are not a live reviewer, so the
        # fresh area owner must still surface rather than being suppressed by a stale cache entry.
        activity = {
            "products/signals": [
                ContributorActivity(
                    login="aged-author",
                    name="Aged Author",
                    commit_count=20,
                    last_commit_at=timezone.now() - timedelta(days=ACTIVITY_WINDOW_DAYS + 30),
                    last_commit_sha="a" * 7,
                    last_commit_url="https://github.com/acme/app/commit/aaaaaaa",
                ),
                ContributorActivity(
                    login="fresh-owner",
                    name="Fresh Owner",
                    commit_count=12,
                    last_commit_at=timezone.now() - timedelta(days=1),
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

        logins = [r.login for r in reviewers]
        assert "fresh-owner" in logins
        assert logins.index("fresh-owner") < logins.index("aged-author")


@pytest.mark.django_db
class TestResolveSuggestedReviewersDiagnostics:
    @pytest.mark.parametrize(
        "name,repository,commit_hashes,author,expected_outcome,expected_counts",
        [
            ("no_repository", "", {"d" * 7: "bug"}, None, "no_repository", {"commit_hash_count": 1}),
            ("no_commit_hashes", "acme/app", {}, None, "no_commit_hashes", {"commit_hash_count": 0}),
            (
                "unattributed_commits",
                "acme/app",
                {"d" * 7: "bug", "e" * 7: "bug"},
                None,
                "no_commit_authors",
                {"lookups_attempted": 2, "lookups_resolved": 0, "lookups_missing": 2},
            ),
            (
                "bot_only_no_activity",
                "acme/app",
                {"d" * 7: "bug"},
                GitHubCommitAuthor(
                    login="dependabot[bot]",
                    name="dependabot",
                    commit_url="https://github.com/acme/app/commit/ddddddd",
                    file_paths=("products/signals/backend/models.py",),
                    is_bot=True,
                ),
                "only_bot_authors",
                {"lookups_resolved": 1, "bot_author_count": 1, "blame_login_count": 0, "touched_path_count": 1},
            ),
        ],
    )
    def test_empty_result_names_its_cause(
        self, team, name, repository, commit_hashes, author, expected_outcome, expected_counts
    ):
        class FakeGitHub:
            def get_commit_author_info(self, repository, sha):
                return author

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
            resolution = resolve_suggested_reviewers_with_diagnostics(team.id, repository, commit_hashes)

        assert resolution.reviewers == []
        assert resolution.diagnostics.outcome == expected_outcome
        for field, value in expected_counts.items():
            assert getattr(resolution.diagnostics, field) == value, field

    def test_a_throttled_lookup_outweighs_what_the_others_returned(self, team):
        # One lookup throttled, the other unattributed. The throttled commit is the one that could
        # have carried the human author, so the rate limit is the cause worth reporting — reading
        # this as `no_commit_authors` would send someone hunting a GitHub attribution problem.
        class FakeGitHub:
            def get_commit_author_info(self, repository, sha):
                if sha.startswith("d"):
                    raise GitHubRateLimitError("rate limited")
                return None

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
            resolution = resolve_suggested_reviewers_with_diagnostics(
                team.id, "acme/app", {"d" * 7: "bug", "e" * 7: "bug"}
            )

        assert resolution.reviewers == []
        assert resolution.diagnostics.outcome == "github_rate_limited"
        assert resolution.diagnostics.lookups_rate_limited == 1
        assert resolution.diagnostics.lookups_attempted == 2

    def test_no_integration_is_reported_before_any_lookup(self, team):
        with patch(
            "products.signals.backend.report_generation.resolve_reviewers.GitHubIntegration.first_for_team_repository",
            return_value=None,
        ):
            resolution = resolve_suggested_reviewers_with_diagnostics(team.id, "acme/app", {"d" * 7: "bug"})

        assert resolution.reviewers == []
        assert resolution.diagnostics.outcome == "no_github_integration"
        assert resolution.diagnostics.lookups_attempted == 0
