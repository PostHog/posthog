import importlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from posthog.test.base import APIBaseTest

from django.apps import apps
from django.db import IntegrityError, router

from posthog.models.scoping import reset_current_team_id, set_current_team_id
from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.stamphog.backend.models import PullRequest, ReviewRun, StamphogInstallation, StamphogRepoConfig
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES, StamphogTeamScopedTestMixin


def _make_repo_config(
    team: Team, repository: str = "PostHog/posthog", installation_id: str = "123"
) -> StamphogRepoConfig:
    return StamphogRepoConfig.objects.unscoped().create(
        team_id=team.id, repository=repository, installation_id=installation_id
    )


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
        _make_repo_config(self.team, "PostHog/posthog", installation_id="123")
        # Should not raise: the (team_id, repository) uniqueness is scoped per team, not global.
        # Each team has its own GitHub App installation, so the (provider, installation_id,
        # repository) identity stays distinct across teams too.
        _make_repo_config(other_team, "PostHog/posthog", installation_id="456")

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


class TestInstallationMigrations(StamphogTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def _run_migration(self, module_name: str, function_name: str) -> None:
        module = importlib.import_module(f"products.stamphog.backend.migrations.{module_name}")
        schema_editor = SimpleNamespace(connection=SimpleNamespace(alias=router.db_for_write(StamphogRepoConfig)))
        getattr(module, function_name)(apps, schema_editor)

    def test_backfill_keeps_every_repository_addable_before_the_cleanup_deletes_unused_rows(self) -> None:
        # The cleanup deletes rows a sync created and nobody turned on. The backfill must first copy
        # their repositories into the snapshot, or those repositories can never be added again.
        rows = {
            name: StamphogRepoConfig.objects.unscoped().create(
                team_id=self.team.id,
                repository=name,
                installation_id=installation_id,
                enabled=enabled,
                connected_by_user_id=connector,
            )
            for name, installation_id, enabled, connector in [
                ("acme/reviewed", "1", True, 5),
                ("acme/unused", "1", False, 7),
                ("acme/with-history", "1", False, None),
                ("acme/placeholder", "", False, None),
                ("acme/label-mode", "1", False, None),
            ]
        }
        StamphogRepoConfig.objects.unscoped().filter(id=rows["acme/label-mode"].id).update(review_mode="label")
        for day, name in enumerate(rows, start=1):
            StamphogRepoConfig.objects.unscoped().filter(id=rows[name].id).update(
                updated_at=datetime(2026, 1, day, tzinfo=UTC)
            )
        _make_pull_request(self.team, rows["acme/with-history"])

        # Twice, because bin/migrate retries a migration that failed part of the way.
        self._run_migration("0008_backfill_installations", "backfill_installations")
        self._run_migration("0008_backfill_installations", "backfill_installations")
        self._run_migration("0009_delete_unused_repo_configs", "delete_unused_repo_configs")

        installation = StamphogInstallation.objects.unscoped().get(team_id=self.team.id)
        assert installation.installation_id == "1"
        assert installation.repositories == ["acme/label-mode", "acme/reviewed", "acme/unused", "acme/with-history"]
        # The newest non-null connector, which the newer row with no connector does not overwrite.
        assert installation.connected_by_user_id == 7
        remaining = StamphogRepoConfig.objects.unscoped().filter(team_id=self.team.id)
        assert sorted(remaining.values_list("repository", flat=True)) == [
            "acme/label-mode",
            "acme/placeholder",
            "acme/reviewed",
            "acme/with-history",
        ]
