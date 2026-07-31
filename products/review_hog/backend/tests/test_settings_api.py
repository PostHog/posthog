from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import Team, User
from posthog.models.scoping import team_scope

from products.review_hog.backend.models import ReviewUserSettings
from products.skills.backend.models.skills import LLMSkill
from products.stamphog.backend.models import StamphogRepoConfig


class TestReviewUserSettingsAPI(APIBaseTest):
    # The serializer resolves stamphog_connected off the stamphog product DB on every response.
    databases = {"default", "stamphog_db_writer", "stamphog_db_reader"}

    def setUp(self) -> None:
        super().setUp()
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
            "urgency_threshold": "consider",
            "can_trigger_reviews": False,  # REVIEWHOG_TEAM_ID is unset in tests
            "stamphog_connected": False,  # no synced+enabled repo config in this project
        }
        assert ReviewUserSettings.objects.for_team(self.team.id).filter(user_id=self.user.id).count() == 1

    def test_patch_updates_only_the_provided_fields(self) -> None:
        res = self.client.patch(
            self.url, {"urgency_threshold": "must_fix", "stamphog_review_inbox_prs": True}, format="json"
        )

        assert res.status_code == 200
        assert res.json()["urgency_threshold"] == "must_fix"
        row = ReviewUserSettings.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert row.urgency_threshold == "must_fix"
        assert row.stamphog_review_inbox_prs is True
        assert row.review_labeled_prs is True  # untouched field keeps its default

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
        with team_scope(self.team.id):
            StamphogRepoConfig.objects.create(
                team_id=self.team.id,
                repository="posthog/posthog",
                enabled=enabled,
                installation_id=installation_id,
                connected_by_user_id=connected_by_user_id,
            )

        res = self.client.get(self.url)

        assert res.status_code == 200
        assert res.json()["stamphog_connected"] is expected

    def test_patch_rejects_an_unknown_threshold(self) -> None:
        res = self.client.patch(self.url, {"urgency_threshold": "everything"}, format="json")
        assert res.status_code == 400

    def test_settings_are_per_user(self) -> None:
        # One user's opt-out must not leak into a teammate's row — the gate reads the PR author's.
        other = User.objects.create_and_join(self.organization, "other-settings@posthog.com", None)
        self.client.patch(self.url, {"review_labeled_prs": False}, format="json")

        self.client.force_login(other)
        res = self.client.get(self.url)

        assert res.status_code == 200
        assert res.json()["review_labeled_prs"] is True

    def test_get_seeds_the_authoring_skill_idempotently(self) -> None:
        # The settings GET is the tab's always-called endpoint, so it must make the authoring guide
        # exist before any review has run (the "Create your own …" tasks skill-get it) — and a
        # repeat GET must not version-bump-loop the row.
        for _ in range(2):
            assert self.client.get(self.url).status_code == 200

        rows = LLMSkill.objects.filter(team=self.team, name="review-hog-authoring")
        assert rows.count() == 1
        assert rows.get().version == 1

    def test_environment_url_resolves_to_the_canonical_team(self) -> None:
        # With an environment (child team) id in the URL, the canonicalized `for_team` filter and a
        # raw-id create kwarg used to contradict each other: the row landed on the parent, the get
        # never matched, and every call after the first 500ed on the unique constraint.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        url = f"/api/projects/{env.id}/review_hog/settings/"

        first = self.client.get(url)
        second = self.client.patch(url, {"urgency_threshold": "must_fix"}, format="json")

        assert first.status_code == 200
        assert second.status_code == 200
        row = ReviewUserSettings.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert row.team_id == self.team.id
        assert row.urgency_threshold == "must_fix"
