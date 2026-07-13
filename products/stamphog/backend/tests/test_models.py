import pytest
from posthog.test.base import APIBaseTest

from django.db import IntegrityError

from posthog.models.scoping import reset_current_team_id, set_current_team_id
from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.stamphog.backend.models import PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES, StamphogTeamScopedTestMixin


def _make_repo_config(team: Team, repository: str = "PostHog/posthog") -> StamphogRepoConfig:
    return StamphogRepoConfig.objects.unscoped().create(team_id=team.id, repository=repository, installation_id="123")


def _make_pull_request(team: Team, repo_config: StamphogRepoConfig, pr_number: int = 1) -> PullRequest:
    return PullRequest.objects.unscoped().create(
        team_id=team.id,
        repo_config=repo_config,
        pr_number=pr_number,
        pr_url=f"https://github.com/{repo_config.repository}/pull/{pr_number}",
    )


class TestStamphogRepoConfigModel(StamphogTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def test_duplicate_repository_for_same_team_rejected(self) -> None:
        # Same repo config could otherwise be double-registered by a repeated
        # webhook-driven onboarding flow, silently duplicating gate policy.
        _make_repo_config(self.team, "PostHog/posthog")
        with pytest.raises(IntegrityError):
            _make_repo_config(self.team, "PostHog/posthog")

    def test_same_repository_allowed_across_teams(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        _make_repo_config(self.team, "PostHog/posthog")
        # Should not raise: uniqueness is scoped per team, not global.
        _make_repo_config(other_team, "PostHog/posthog")

    def test_for_team_excludes_other_teams_rows(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        mine = _make_repo_config(self.team, "PostHog/posthog")
        _make_repo_config(other_team, "PostHog/other-repo")

        results = list(StamphogRepoConfig.objects.for_team(self.team.id))
        assert results == [mine]


class TestReviewRunModel(StamphogTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.repo_config = _make_repo_config(self.team)
        self.pull_request = _make_pull_request(self.team, self.repo_config)

    def _make_run(self, delivery_id: str | None) -> ReviewRun:
        return ReviewRun.objects.unscoped().create(
            team_id=self.team.id,
            pull_request=self.pull_request,
            head_sha="abc123",
            delivery_id=delivery_id,
        )

    def test_duplicate_delivery_id_rejected(self) -> None:
        # delivery_id uniqueness is the dedupe mechanism for redelivered
        # GitHub webhooks; if it stops being enforced, a redelivery would
        # spawn a second review run for the same PR event.
        self._make_run("delivery-1")
        with pytest.raises(IntegrityError):
            self._make_run("delivery-1")

    def test_multiple_null_delivery_ids_allowed(self) -> None:
        # null delivery_id covers runs not created from a webhook (e.g. manual
        # retriggers); Postgres unique constraints don't collide on NULL, but
        # this locks in that assumption for this specific column.
        self._make_run(None)
        self._make_run(None)  # must not raise

    def test_queryset_without_team_context_raises(self) -> None:
        # Fail-closed scoping guard: reading ReviewRun outside team_scope()
        # or .for_team() must not silently return every team's runs.
        self._make_run("delivery-2")
        # The mixin holds team scope open for the whole test; clear it here to
        # exercise the manager's fail-closed default directly.
        token = set_current_team_id(None)
        try:
            with pytest.raises(TeamScopeError):
                list(ReviewRun.objects.all())
        finally:
            reset_current_team_id(token)

    def test_for_team_scopes_to_owning_team(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        other_repo_config = _make_repo_config(other_team, "PostHog/other-repo")
        other_pull_request = _make_pull_request(other_team, other_repo_config)
        mine = self._make_run("delivery-3")
        ReviewRun.objects.unscoped().create(
            team_id=other_team.id,
            pull_request=other_pull_request,
            head_sha="def456",
            delivery_id="delivery-4",
        )

        results = list(ReviewRun.objects.for_team(self.team.id))
        assert results == [mine]
