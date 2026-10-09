from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team, User

from products.review_hog.backend.api.settings import ReviewUserSettingsSerializer
from products.review_hog.backend.models import ReviewProjectSettings, ReviewUserSettings
from products.skills.backend.models.skills import LLMSkill
from products.stamphog.backend.facade.testing import seed_repo_config

_INTERNAL_FLAG = "products.review_hog.backend.internal_features.posthog_feature_flag_enabled"


class TestReviewUserSettingsAPI(APIBaseTest):
    # The serializer resolves stamphog_connected off the stamphog product DB on every response.
    databases = {"default", "stamphog_db_writer", "stamphog_db_reader"}

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.url = f"/api/projects/{self.team.id}/review_hog/settings/"

    def test_get_returns_defaults_without_creating_a_row(self) -> None:
        res = self.client.get(self.url)

        assert res.status_code == 200
        assert res.json() == {
            "default_review_mode": "follow",
            "resolve_comments": False,
            "urgency_threshold": "consider",
            "celebrate_clean_reviews": True,
            "review_inbox_prs": False,
            "stamphog_review_inbox_prs": False,  # opt-in: a real approval must never be a default
            "sources": {
                "default_review_mode": "default",
                "resolve_comments": "default",
                "urgency_threshold": "default",
                "celebrate_clean_reviews": "default",
                "review_inbox_prs": "default",
                "stamphog_review_inbox_prs": "default",
            },
            "project_defaults": {"urgency_threshold": "consider", "celebrate_clean_reviews": True},
            "stamphog_connected": False,  # no synced+enabled repo config in this project
        }
        assert not ReviewUserSettings.objects.for_team(self.team.id).filter(user_id=self.user.id).exists()

    def test_patch_stores_only_values_that_differ_from_the_inherited_ones(self) -> None:
        ReviewProjectSettings.objects.for_team(self.team.id).create(
            team=self.team, preferences={"urgency_threshold": "should_fix"}
        )

        res = self.client.patch(
            self.url,
            {
                "urgency_threshold": "must_fix",
                "stamphog_review_inbox_prs": True,
                "resolve_comments": True,
                "default_review_mode": "flash",
                "celebrate_clean_reviews": True,
            },
            format="json",
        )

        assert res.status_code == 200
        assert res.json()["urgency_threshold"] == "must_fix"
        assert res.json()["sources"]["urgency_threshold"] == "user"
        assert res.json()["sources"]["celebrate_clean_reviews"] == "default"
        row = ReviewUserSettings.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert row.preferences == {
            "urgency_threshold": "must_fix",
            "stamphog_review_inbox_prs": True,
            "resolve_comments": True,
            "default_review_mode": "flash",
        }

        # Picking the project value clears the user's own value, so later project changes reach them.
        follows_project = self.client.patch(self.url, {"urgency_threshold": "should_fix"}, format="json")

        assert follows_project.json()["sources"]["urgency_threshold"] == "project"
        row.refresh_from_db()
        assert "urgency_threshold" not in row.preferences

    @parameterized.expand(
        [
            # (name, enabled, installation_id, connected_by_user_id, expected) — "connected" must mean
            # a review can actually run: an unsynced or disabled config would make the toggle a no-op
            # (hosted reviews fail closed without a connecting user to mint sandbox credentials under).
            ("synced_and_enabled", True, "inst-1", 42, True),
            ("disabled", False, "inst-1", 42, False),
            ("never_synced_blank_installation", True, "", 42, False),
            ("no_connecting_user", True, "inst-1", None, False),
        ]
    )
    def test_stamphog_connected_requires_a_synced_enabled_repo_config(
        self, _name, enabled, installation_id, connected_by_user_id, expected
    ) -> None:
        seed_repo_config(
            team_id=self.team.id,
            repository="posthog/posthog",
            enabled=enabled,
            installation_id=installation_id,
            connected_by_user_id=connected_by_user_id,
        )

        with patch(_INTERNAL_FLAG, return_value=True):
            res = self.client.get(self.url)

        assert res.status_code == 200
        assert res.json()["stamphog_connected"] is expected

    def test_patch_rejects_an_unknown_threshold(self) -> None:
        res = self.client.patch(self.url, {"urgency_threshold": "everything"}, format="json")
        assert res.status_code == 400

    def test_settings_are_per_user(self) -> None:
        # One user's choice must not leak into a teammate's preferences — the gates read the PR author's.
        other = User.objects.create_and_join(self.organization, "other-settings@posthog.com", None)
        self.client.patch(self.url, {"default_review_mode": "flash", "resolve_comments": True}, format="json")

        self.client.force_login(other)
        res = self.client.get(self.url)

        assert res.status_code == 200
        assert res.json()["default_review_mode"] == "follow"
        assert res.json()["resolve_comments"] is False

    def test_get_seeds_the_authoring_skill_idempotently(self) -> None:
        # The settings GET is the tab's always-called endpoint, so it must make the authoring guide
        # exist before any review has run (the "Create your own …" tasks skill-get it) — and a
        # repeat GET must not version-bump-loop the row.
        for _ in range(2):
            assert self.client.get(self.url).status_code == 200

        rows = LLMSkill.objects.filter(team=self.team, name="review-hog-authoring")
        assert rows.count() == 1
        assert rows.get().version == 1

    def test_environment_flag_access_uses_the_url_team_but_settings_use_the_parent(self) -> None:
        # With an environment (child team) id in the URL, the canonicalized `for_team` filter and a
        # raw-id create kwarg used to contradict each other: the row landed on the parent, the get
        # never matched, and every call after the first 500ed on the unique constraint.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        url = f"/api/projects/{env.id}/review_hog/settings/"
        enabled_project_id = str(self.team.id)

        def enabled_for_project(
            key: str,
            _distinct_id: str,
            *,
            group_properties: dict[str, dict[str, str]] | None = None,
            **_kwargs: object,
        ) -> bool:
            return key == "review-hog" and (group_properties or {}).get("project", {}).get("id") == enabled_project_id

        with patch("posthoganalytics.feature_enabled", side_effect=enabled_for_project):
            parent = self.client.patch(self.url, {"urgency_threshold": "should_fix"}, format="json")
            assert parent.status_code == 200
            assert self.client.get(url).status_code == 403

            enabled_project_id = str(env.id)
            first = self.client.get(url)
            second = self.client.patch(url, {"urgency_threshold": "must_fix"}, format="json")

        assert first.status_code == 200
        assert first.json()["urgency_threshold"] == "should_fix"
        assert second.status_code == 200
        row = ReviewUserSettings.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert row.team_id == self.team.id
        assert row.preferences == {"urgency_threshold": "must_fix"}


class TestReviewUserSettingsValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("full_mode_is_not_offered", {"default_review_mode": "full"}, "default_review_mode"),
            ("unknown_threshold", {"urgency_threshold": "everything"}, "urgency_threshold"),
        ]
    )
    def test_rejects_values_outside_the_schema(self, _name: str, data: dict, field: str) -> None:
        serializer = ReviewUserSettingsSerializer(data=data, partial=True)

        assert not serializer.is_valid()
        assert field in serializer.errors
