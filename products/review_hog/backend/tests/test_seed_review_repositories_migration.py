import importlib
from typing import Any

from posthog.test.base import BaseTest

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from parameterized import parameterized

from posthog.models import User
from posthog.models.integration import Integration

from products.review_hog.backend.models import (
    ReviewInstallationClaim,
    ReviewReport,
    ReviewRepository,
    ReviewUserSettings,
)

seed_migration = importlib.import_module("products.review_hog.backend.migrations.0035_seed_review_repositories")


class TestSeedReviewSettingsMigration(BaseTest):
    def _settings(self, email: str, **fields: Any) -> User:
        user = User.objects.create_and_join(self.organization, email, None)
        ReviewUserSettings.objects.for_team(self.team.id).create(team_id=self.team.id, user_id=user.id, **fields)
        return user

    def _run(self) -> None:
        # The migration runs on historical models, whose managers have no team scoping.
        historical_apps = (
            MigrationLoader(connection).project_state(("review_hog", "0035_seed_review_repositories")).apps
        )
        seed_migration.seed_review_settings(historical_apps, None)
        seed_migration.seed_review_settings(historical_apps, None)

    def test_columns_move_into_sparse_preferences_and_empty_rows_go(self) -> None:
        flash = self._settings("flash@example.com", review_authored_prs=True, urgency_threshold="must_fix")
        quiet = self._settings(
            "quiet@example.com", celebrate_clean_reviews=False, review_inbox_prs=True, stamphog_review_inbox_prs=True
        )
        # Resolution becomes opt-in, so the old default of on copies nothing and the row goes.
        self._settings("defaults@example.com", resolve_comments=True, review_labeled_prs=False)

        self._run()

        preferences = dict(ReviewUserSettings.objects.for_team(self.team.id).values_list("user_id", "preferences"))
        assert preferences == {
            flash.id: {"default_review_mode": "flash", "urgency_threshold": "must_fix"},
            quiet.id: {"celebrate_clean_reviews": False, "review_inbox_prs": True, "stamphog_review_inbox_prs": True},
        }

    @parameterized.expand(
        [
            (
                "cached_list_names_the_repositories",
                True,
                {},
                [
                    {"id": 11, "name": "posthog", "full_name": "PostHog/posthog"},
                    {"id": 12, "name": "ai-gateway", "full_name": "PostHog/ai-gateway"},
                    {"id": 13, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
                ],
                [("PostHog/posthog", 11), ("PostHog/ai-gateway", 12)],
            ),
            (
                "account_name_without_a_cached_list",
                True,
                {"account": {"name": "posthog"}},
                [],
                [("PostHog/posthog", None), ("PostHog/ai-gateway", None)],
            ),
            ("another_account", True, {"account": {"name": "example-org"}}, [], []),
            ("never_ran_automatic_reviews", False, {"account": {"name": "posthog"}}, [], []),
        ]
    )
    def test_the_automatic_review_project_selects_the_repositories_the_allowlists_covered(
        self, _name: str, ran_automatic_reviews: bool, config: dict, repository_cache: list, expected_rows: list
    ) -> None:
        ReviewReport.objects.for_team(self.team.id).create(
            team=self.team,
            repository="PostHog/posthog",
            pr_number=1,
            head_branch="feature",
            base_branch="master",
            automatic_reviewed_head_sha="a" * 40 if ran_automatic_reviews else None,
        )
        Integration.objects.create(
            team=self.team, kind="github", integration_id="1001", config=config, repository_cache=repository_cache
        )

        self._run()

        claims = ReviewInstallationClaim.objects.for_team(self.team.id)
        assert list(claims.values_list("installation_id", "scope")) == ([("1001", "selected")] if expected_rows else [])
        rows = ReviewRepository.objects.for_team(self.team.id)
        assert set(rows.values_list("full_name", "github_repo_id", "selected", "flash_for")) == {
            (full_name, github_repo_id, True, None) for full_name, github_repo_id in expected_rows
        }
