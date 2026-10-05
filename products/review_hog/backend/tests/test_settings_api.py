from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models import Team, User

from products.review_hog.backend.api.settings import ReviewUserSettingsSerializer
from products.review_hog.backend.models import ReviewUserSettings
from products.skills.backend.models.skills import LLMSkill
from products.stamphog.backend.facade.testing import seed_repo_config


class TestReviewUserSettingsAPI(APIBaseTest):
    # The serializer resolves stamphog_connected off the stamphog product DB on every response.
    databases = {"default", "stamphog_db_writer", "stamphog_db_reader"}

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.url = f"/api/projects/{self.team.id}/review_hog/settings/"

    def test_get_creates_the_row_with_defaults(self) -> None:
        # First read auto-creates the singleton with the model defaults, so the UI never special-cases
        # a missing row (and the label trigger keeps its opt-out default of on).
        res = self.client.get(self.url)

        assert res.status_code == 200
        assert res.json() == {
            "review_inbox_prs": False,
            "stamphog_review_inbox_prs": False,  # opt-in: a real approval must never be a default
            "review_labeled_prs": True,
            "resolve_comments": True,
            "celebrate_clean_reviews": True,
            "review_authored_prs": False,
            "flash_reasoning_effort": "medium",
            "urgency_threshold": "consider",
            "can_trigger_reviews": True,
            "show_internal_features": False,
            "stamphog_connected": False,  # no synced+enabled repo config in this project
        }
        assert ReviewUserSettings.objects.for_team(self.team.id).filter(user_id=self.user.id).count() == 1

    def test_patch_updates_only_the_provided_fields(self) -> None:
        # resolve_comments rides along: it's the UI toggle's only write path, so a serializer that
        # stops accepting it (e.g. marked read-only) would silently no-op the switch.
        res = self.client.patch(
            self.url,
            {
                "urgency_threshold": "must_fix",
                "stamphog_review_inbox_prs": True,
                "resolve_comments": False,
                "review_authored_prs": True,
                "flash_reasoning_effort": "xhigh",
                "celebrate_clean_reviews": False,
            },
            format="json",
        )

        assert res.status_code == 200
        assert res.json()["urgency_threshold"] == "must_fix"
        row = ReviewUserSettings.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert row.urgency_threshold == "must_fix"
        assert row.stamphog_review_inbox_prs is True
        assert row.resolve_comments is False
        assert row.review_authored_prs is True
        assert row.flash_reasoning_effort == "xhigh"
        assert row.celebrate_clean_reviews is False
        assert row.review_labeled_prs is True  # untouched field keeps its default

        disabled = self.client.patch(self.url, {"review_authored_prs": False}, format="json")

        assert disabled.status_code == 200
        disabled_row = ReviewUserSettings.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert disabled_row.review_authored_prs is False
        assert disabled_row.flash_reasoning_effort == "xhigh"

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

        with override_settings(REVIEWHOG_TEAM_IDS=[self.team.id]):
            res = self.client.get(self.url)

        assert res.status_code == 200
        assert res.json()["show_internal_features"] is True
        assert res.json()["stamphog_connected"] is expected

    def test_patch_rejects_an_unknown_threshold(self) -> None:
        res = self.client.patch(self.url, {"urgency_threshold": "everything"}, format="json")
        assert res.status_code == 400

    def test_settings_are_per_user(self) -> None:
        # One user's opt-out must not leak into a teammate's row — the gate reads the PR author's.
        other = User.objects.create_and_join(self.organization, "other-settings@posthog.com", None)
        self.client.patch(
            self.url,
            {"review_labeled_prs": False, "review_authored_prs": True, "flash_reasoning_effort": "xhigh"},
            format="json",
        )

        self.client.force_login(other)
        res = self.client.get(self.url)

        assert res.status_code == 200
        assert res.json()["review_labeled_prs"] is True
        assert res.json()["review_authored_prs"] is False
        assert res.json()["flash_reasoning_effort"] == "medium"

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
        assert row.urgency_threshold == "must_fix"


class TestReviewUserSettingsValidation(SimpleTestCase):
    @parameterized.expand(["low", "high"])
    def test_flash_effort_rejects_values_outside_its_supported_choices(self, effort: str) -> None:
        serializer = ReviewUserSettingsSerializer(data={"flash_reasoning_effort": effort}, partial=True)

        assert not serializer.is_valid()
        assert "flash_reasoning_effort" in serializer.errors
