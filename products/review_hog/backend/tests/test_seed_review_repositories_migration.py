import importlib
from typing import Any

from posthog.test.base import BaseTest

from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings

from posthog.models import User

from products.review_hog.backend.models import (
    ReviewRepository,
    ReviewRepositoryPerson,
    ReviewUserRepositoryChoice,
    ReviewUserSettings,
)

seed_migration = importlib.import_module("products.review_hog.backend.migrations.0035_seed_review_repositories")


class TestSeedReviewRepositoriesMigration(BaseTest):
    def _settings(self, email: str, **fields: Any) -> User:
        user = User.objects.create_and_join(self.organization, email, None)
        ReviewUserSettings.objects.for_team(self.team.id).create(team_id=self.team.id, user_id=user.id, **fields)
        return user

    def test_opted_in_users_keep_flash_in_posthog_only(self) -> None:
        opted_in = self._settings("opted-in@example.com", review_authored_prs=True)
        not_opted_in = self._settings("not-opted-in@example.com", review_authored_prs=False)

        # The migration runs on historical models, whose managers have no team scoping.
        historical_apps = (
            MigrationLoader(connection).project_state(("review_hog", "0035_seed_review_repositories")).apps
        )
        with override_settings(REVIEWHOG_TEAM_IDS=[self.team.id]):
            seed_migration.seed_review_repositories(historical_apps, None)
            seed_migration.seed_review_repositories(historical_apps, None)

        modes = dict(ReviewUserSettings.objects.for_team(self.team.id).values_list("user_id", "default_review_mode"))
        assert modes == {opted_in.id: "flash", not_opted_in.id: "follow"}
        repositories = ReviewRepository.objects.for_team(self.team.id)
        assert sorted(repositories.values_list("full_name", "flash_for")) == [
            ("PostHog/ai-gateway", "listed"),
            ("PostHog/posthog", "listed"),
        ]
        assert not ReviewRepositoryPerson.objects.for_team(self.team.id).exists()
        choices = ReviewUserRepositoryChoice.objects.for_team(self.team.id)
        assert list(choices.values_list("user_id", "repository__full_name", "mode")) == [
            (opted_in.id, "PostHog/ai-gateway", "off")
        ]
