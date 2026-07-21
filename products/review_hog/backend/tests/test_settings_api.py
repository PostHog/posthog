from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import Team, User

from products.review_hog.backend.models import ReviewUserSettings
from products.skills.backend.models.skills import LLMSkill
from products.stamphog.backend.models import StamphogRepoConfig


class TestReviewUserSettingsAPI(APIBaseTest):
    # The serializer's stamphog_available field reads stamphog's repo configs, which live on the
    # product DB when one is configured (always true under TEST settings).
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
            "review_labeled_prs": True,
            "stamphog_review_inbox_prs": False,
            "stamphog_available": False,  # no stamphog repo config in this team
            "urgency_threshold": "consider",
            "can_trigger_reviews": False,  # REVIEWHOG_TEAM_ID is unset in tests
        }
        assert ReviewUserSettings.objects.for_team(self.team.id).filter(user_id=self.user.id).count() == 1

    @parameterized.expand(
        [
            # (name, enabled, installation_id, expected) — only a synced (non-blank installation) AND
            # enabled config makes the toggle actionable; the UI disables it otherwise.
            ("synced_and_enabled", True, "12345", True),
            ("disabled", False, "12345", False),
            ("never_synced", True, "", False),
        ]
    )
    def test_stamphog_available_requires_a_synced_enabled_repo_config(
        self, _name, enabled, installation_id, expected
    ) -> None:
        StamphogRepoConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, repository="acme/widgets", enabled=enabled, installation_id=installation_id
        )

        res = self.client.get(self.url)

        assert res.status_code == 200
        assert res.json()["stamphog_available"] is expected

    def test_patch_stamphog_toggle_persists_without_touching_siblings(self) -> None:
        res = self.client.patch(self.url, {"stamphog_review_inbox_prs": True}, format="json")

        assert res.status_code == 200
        row = ReviewUserSettings.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert row.stamphog_review_inbox_prs is True
        assert row.review_inbox_prs is False  # the two inbox opt-ins are independent

    def test_patch_updates_only_the_provided_fields(self) -> None:
        res = self.client.patch(self.url, {"urgency_threshold": "must_fix"}, format="json")

        assert res.status_code == 200
        assert res.json()["urgency_threshold"] == "must_fix"
        row = ReviewUserSettings.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert row.urgency_threshold == "must_fix"
        assert row.review_labeled_prs is True  # untouched field keeps its default

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
