from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import Team

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.lazy_seed import sync_canonical_perspectives
from products.review_hog.backend.reviewer.skill_loader import (
    CANONICAL_PERSPECTIVE_SKILL_NAMES,
    REVIEW_HOG_PERSPECTIVE_PREFIX,
    REVIEW_HOG_VALIDATION_SKILL_NAME,
    register_missing_perspective_configs,
)
from products.skills.backend.models.skills import LLMSkill

_CUSTOM = f"{REVIEW_HOG_PERSPECTIVE_PREFIX}custom-x"


class TestReviewPerspectiveConfigAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_canonical_perspectives(self.team)
        self.base = f"/api/projects/{self.team.id}/review_hog/perspectives"

    def _author_custom(self) -> None:
        LLMSkill.objects.create(
            team=self.team, name=_CUSTOM, description="d", body="x" * 250, version=1, is_latest=True
        )

    def test_list_shows_canonicals_enabled_and_custom_disabled(self) -> None:
        # The menu surfaces every perspective skill with this user's enable state — canonicals seed on,
        # a custom not yet switched on shows off — so the future UI can render the full toggle list.
        self._author_custom()

        res = self.client.get(f"{self.base}/")

        assert res.status_code == 200
        by_name = {item["skill_name"]: item["enabled"] for item in res.json()}
        assert all(by_name[name] is True for name in CANONICAL_PERSPECTIVE_SKILL_NAMES)
        assert by_name[_CUSTOM] is False

    def test_enabling_a_custom_perspective_upserts_the_config(self) -> None:
        # Authoring a custom skill then PATCHing it on must create an enabled config in one call — the
        # "create a custom perspective and run it" path.
        self._author_custom()

        res = self.client.patch(f"{self.base}/{_CUSTOM}/", {"enabled": True}, format="json")

        assert res.status_code == 200
        assert res.json()["enabled"] is True
        config = ReviewSkillConfig.objects.for_team(self.team.id).get(user_id=self.user.id, skill_name=_CUSTOM)
        assert config.enabled is True

    def test_cannot_disable_the_last_enabled_perspective(self) -> None:
        # The min-1 floor: a user must always keep ≥1 perspective on, or their reviews would run empty.
        register_missing_perspective_configs(self.team.id, self.user.id)
        names = sorted(CANONICAL_PERSPECTIVE_SKILL_NAMES)
        for name in names[:2]:
            assert self.client.patch(f"{self.base}/{name}/", {"enabled": False}, format="json").status_code == 200

        res = self.client.patch(f"{self.base}/{names[2]}/", {"enabled": False}, format="json")

        assert res.status_code == 400
        last = ReviewSkillConfig.objects.for_team(self.team.id).get(user_id=self.user.id, skill_name=names[2])
        assert last.enabled is True

    def test_an_enabled_validator_does_not_satisfy_the_perspective_floor(self) -> None:
        # The min-1 floor counts only perspectives: an enabled validator in the shared table must not
        # let a user disable their last perspective.
        register_missing_perspective_configs(self.team.id, self.user.id)
        names = sorted(CANONICAL_PERSPECTIVE_SKILL_NAMES)
        for name in names[:2]:
            assert self.client.patch(f"{self.base}/{name}/", {"enabled": False}, format="json").status_code == 200
        ReviewSkillConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME, enabled=True
        )

        res = self.client.patch(f"{self.base}/{names[2]}/", {"enabled": False}, format="json")

        assert res.status_code == 400

    @parameterized.expand(
        [
            ("unknown_perspective_skill", f"{REVIEW_HOG_PERSPECTIVE_PREFIX}does-not-exist", 404),
            ("not_a_perspective_name", "review-hog-validation-criteria", 400),
        ]
    )
    def test_patch_rejects_bad_skill(self, _name: str, skill_name: str, expected_status: int) -> None:
        res = self.client.patch(f"{self.base}/{skill_name}/", {"enabled": True}, format="json")
        assert res.status_code == expected_status

    def test_environment_url_resolves_to_the_canonical_team(self) -> None:
        # With an environment (child team) id in the URL, the canonicalized `for_team` filter and a
        # raw-id create kwarg used to contradict each other: the config row landed on the parent, the
        # get never matched, and every call after the first 500ed on the unique constraint (and the
        # raw-id LLMSkill lookups 404ed / listed an empty menu).
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        name = CANONICAL_PERSPECTIVE_SKILL_NAMES[0]
        url = f"/api/projects/{env.id}/review_hog/perspectives/{name}/"

        listing = self.client.get(f"/api/projects/{env.id}/review_hog/perspectives/")
        first = self.client.patch(url, {"enabled": False}, format="json")
        second = self.client.patch(url, {"enabled": True}, format="json")

        assert listing.status_code == 200
        assert {i["skill_name"] for i in listing.json()} >= set(CANONICAL_PERSPECTIVE_SKILL_NAMES)
        assert first.status_code == 200
        assert second.status_code == 200
        config = ReviewSkillConfig.objects.for_team(self.team.id).get(user_id=self.user.id, skill_name=name)
        assert config.team_id == self.team.id
        assert config.enabled is True
