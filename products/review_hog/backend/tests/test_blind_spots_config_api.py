from posthog.test.base import APIBaseTest

from posthog.models import Team

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.lazy_seed import sync_canonical_blind_spots
from products.review_hog.backend.reviewer.skill_loader import (
    REVIEW_HOG_BLIND_SPOTS_PREFIX,
    REVIEW_HOG_BLIND_SPOTS_SKILL_NAME,
    REVIEW_HOG_PERSPECTIVE_PREFIX,
    REVIEW_HOG_VALIDATION_PREFIX,
)
from products.skills.backend.models.skills import LLMSkill

_CUSTOM = f"{REVIEW_HOG_BLIND_SPOTS_PREFIX}security-sweep"


class TestReviewBlindSpotsConfigAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_canonical_blind_spots(self.team)
        self.base = f"/api/projects/{self.team.id}/review_hog/blind_spots"

    def _author_custom(self, name: str = _CUSTOM) -> None:
        LLMSkill.objects.create(team=self.team, name=name, description="d", body="x" * 250, version=1, is_latest=True)

    def test_list_shows_canonical_active_and_custom_inactive(self) -> None:
        # The menu flags the user's active sweep; the canonical seeds active on first read.
        self._author_custom()

        res = self.client.get(f"{self.base}/")

        assert res.status_code == 200
        active_by_name = {item["skill_name"]: item["active"] for item in res.json()}
        assert active_by_name[REVIEW_HOG_BLIND_SPOTS_SKILL_NAME] is True
        assert active_by_name[_CUSTOM] is False

    def test_selecting_a_custom_skill_flips_the_canonical_off(self) -> None:
        # Single-active: selecting a custom sweep switches the canonical off in the same call.
        self._author_custom()

        res = self.client.patch(f"{self.base}/{_CUSTOM}/", {"active": True}, format="json")

        assert res.status_code == 200
        assert res.json()["active"] is True
        configs = ReviewSkillConfig.objects.for_team(self.team.id).filter(user_id=self.user.id)
        assert configs.get(skill_name=_CUSTOM).enabled is True
        assert configs.get(skill_name=REVIEW_HOG_BLIND_SPOTS_SKILL_NAME).enabled is False

    def test_selecting_leaves_other_prefixes_enabled(self) -> None:
        # The bulk deactivate is prefix-scoped: a select must not switch off the user's perspective
        # or validator rows in the shared table.
        others = (f"{REVIEW_HOG_PERSPECTIVE_PREFIX}logic-correctness", f"{REVIEW_HOG_VALIDATION_PREFIX}criteria")
        for name in others:
            ReviewSkillConfig.objects.for_team(self.team.id).create(
                team_id=self.team.id, user_id=self.user.id, skill_name=name, enabled=True
            )
        self._author_custom()

        assert self.client.patch(f"{self.base}/{_CUSTOM}/", {"active": True}, format="json").status_code == 200

        configs = ReviewSkillConfig.objects.for_team(self.team.id).filter(user_id=self.user.id)
        assert all(configs.get(skill_name=name).enabled for name in others)

    def test_list_excludes_other_prefixes(self) -> None:
        # A validator skill in the shared LLMSkill namespace must not leak into the sweep menu.
        self._author_custom(name=f"{REVIEW_HOG_VALIDATION_PREFIX}criteria")

        res = self.client.get(f"{self.base}/")

        assert res.status_code == 200
        assert {item["skill_name"] for item in res.json()} == {REVIEW_HOG_BLIND_SPOTS_SKILL_NAME}

    def test_select_rejects_deactivating(self) -> None:
        # Single-active: you switch by picking another sweep, never by turning the current one off.
        res = self.client.patch(f"{self.base}/{REVIEW_HOG_BLIND_SPOTS_SKILL_NAME}/", {"active": False}, format="json")

        assert res.status_code == 400

    def test_patch_rejects_a_non_blind_spots_name(self) -> None:
        res = self.client.patch(
            f"{self.base}/{REVIEW_HOG_PERSPECTIVE_PREFIX}logic-correctness/", {"active": True}, format="json"
        )
        assert res.status_code == 400

    def test_patch_404_for_unknown_skill(self) -> None:
        res = self.client.patch(
            f"{self.base}/{REVIEW_HOG_BLIND_SPOTS_PREFIX}does-not-exist/", {"active": True}, format="json"
        )
        assert res.status_code == 404

    def test_environment_url_resolves_to_the_canonical_team(self) -> None:
        # Same failure mode as the settings/perspectives viewsets: an environment (child team) id in
        # the URL made the canonicalized `for_team` filter and the raw-id create kwarg contradict,
        # so the second select 500ed on the unique constraint.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        url = f"/api/projects/{env.id}/review_hog/blind_spots/{REVIEW_HOG_BLIND_SPOTS_SKILL_NAME}/"

        first = self.client.patch(url, {"active": True}, format="json")
        second = self.client.patch(url, {"active": True}, format="json")

        assert first.status_code == 200
        assert second.status_code == 200
        config = ReviewSkillConfig.objects.for_team(self.team.id).get(
            user_id=self.user.id, skill_name=REVIEW_HOG_BLIND_SPOTS_SKILL_NAME
        )
        assert config.team_id == self.team.id
        assert config.enabled is True
