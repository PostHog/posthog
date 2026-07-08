from posthog.test.base import APIBaseTest

from posthog.models import Team

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.lazy_seed import sync_canonical_validation
from products.review_hog.backend.reviewer.skill_loader import (
    REVIEW_HOG_PERSPECTIVE_PREFIX,
    REVIEW_HOG_VALIDATION_PREFIX,
    REVIEW_HOG_VALIDATION_SKILL_NAME,
)
from products.skills.backend.models.skills import LLMSkill

_CUSTOM = f"{REVIEW_HOG_VALIDATION_PREFIX}strict"


class TestReviewValidatorConfigAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_canonical_validation(self.team)
        self.base = f"/api/projects/{self.team.id}/review_hog/validators"

    def _author_custom(self) -> None:
        LLMSkill.objects.create(
            team=self.team, name=_CUSTOM, description="d", body="x" * 250, version=1, is_latest=True
        )

    def test_list_shows_canonical_active_and_custom_inactive(self) -> None:
        # The menu surfaces every validator skill flagging the user's active one — the canonical seeds
        # active, a custom not yet selected shows inactive — so the future UI can render the radio list.
        self._author_custom()

        res = self.client.get(f"{self.base}/")

        assert res.status_code == 200
        active_by_name = {item["skill_name"]: item["active"] for item in res.json()}
        assert active_by_name[REVIEW_HOG_VALIDATION_SKILL_NAME] is True
        assert active_by_name[_CUSTOM] is False

    def test_selecting_a_custom_validator_flips_the_canonical_off(self) -> None:
        # Single-active: selecting a custom validator makes it the user's only active one and switches
        # the canonical off in the same call — the "author a custom validator and run it" path.
        self._author_custom()

        res = self.client.patch(f"{self.base}/{_CUSTOM}/", {"active": True}, format="json")

        assert res.status_code == 200
        assert res.json()["active"] is True
        configs = ReviewSkillConfig.objects.for_team(self.team.id).filter(user_id=self.user.id)
        assert configs.get(skill_name=_CUSTOM).enabled is True
        assert configs.get(skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME).enabled is False

    def test_switching_between_custom_validators_keeps_exactly_one_active(self) -> None:
        # Single-active through a switch-back: selecting C2 must flip C1 off (the deactivate covers ALL
        # other validators, not just the canonical), then re-selecting C1 must re-enable its disabled row.
        c1, c2 = f"{REVIEW_HOG_VALIDATION_PREFIX}c1", f"{REVIEW_HOG_VALIDATION_PREFIX}c2"
        for name in (c1, c2):
            LLMSkill.objects.create(
                team=self.team, name=name, description="d", body="x" * 250, version=1, is_latest=True
            )
        configs = ReviewSkillConfig.objects.for_team(self.team.id).filter(user_id=self.user.id)

        assert self.client.patch(f"{self.base}/{c1}/", {"active": True}, format="json").status_code == 200
        assert self.client.patch(f"{self.base}/{c2}/", {"active": True}, format="json").status_code == 200
        assert configs.get(skill_name=c1).enabled is False
        assert configs.get(skill_name=c2).enabled is True

        assert self.client.patch(f"{self.base}/{c1}/", {"active": True}, format="json").status_code == 200
        assert configs.get(skill_name=c1).enabled is True
        assert configs.get(skill_name=c2).enabled is False
        assert configs.filter(skill_name__startswith=REVIEW_HOG_VALIDATION_PREFIX, enabled=True).count() == 1

    def test_selecting_a_validator_leaves_perspective_configs_enabled(self) -> None:
        # The select endpoint's bulk deactivate is prefix-scoped to validators: it must NOT disable the
        # user's enabled perspective rows in the shared table (else their next review has no perspectives).
        perspective = f"{REVIEW_HOG_PERSPECTIVE_PREFIX}logic-correctness"
        ReviewSkillConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, skill_name=perspective, enabled=True
        )
        self._author_custom()

        assert self.client.patch(f"{self.base}/{_CUSTOM}/", {"active": True}, format="json").status_code == 200

        config = ReviewSkillConfig.objects.for_team(self.team.id).get(user_id=self.user.id, skill_name=perspective)
        assert config.enabled is True

    def test_list_excludes_perspective_skills(self) -> None:
        # The validator menu is prefix-scoped: a perspective skill in the shared LLMSkill namespace must
        # not leak into the validator list.
        LLMSkill.objects.create(
            team=self.team,
            name=f"{REVIEW_HOG_PERSPECTIVE_PREFIX}logic-correctness",
            description="d",
            body="x" * 250,
            version=1,
            is_latest=True,
        )

        res = self.client.get(f"{self.base}/")

        assert res.status_code == 200
        names = {item["skill_name"] for item in res.json()}
        assert names == {REVIEW_HOG_VALIDATION_SKILL_NAME}

    def test_select_rejects_deactivating(self) -> None:
        # Validators are single-active: there is no "turn the current one off" — you switch by picking
        # another. A false `active` is rejected rather than leaving the user with no validator.
        res = self.client.patch(f"{self.base}/{REVIEW_HOG_VALIDATION_SKILL_NAME}/", {"active": False}, format="json")

        assert res.status_code == 400

    def test_patch_rejects_a_non_validator_name(self) -> None:
        res = self.client.patch(
            f"{self.base}/{REVIEW_HOG_PERSPECTIVE_PREFIX}logic-correctness/", {"active": True}, format="json"
        )
        assert res.status_code == 400

    def test_patch_404_for_unknown_validator(self) -> None:
        res = self.client.patch(
            f"{self.base}/{REVIEW_HOG_VALIDATION_PREFIX}does-not-exist/", {"active": True}, format="json"
        )
        assert res.status_code == 404

    def test_environment_url_resolves_to_the_canonical_team(self) -> None:
        # Same failure mode as the settings/perspectives viewsets: an environment (child team) id in
        # the URL made the canonicalized `for_team` filter and the raw-id create kwarg contradict,
        # so the second select 500ed on the unique constraint.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        url = f"/api/projects/{env.id}/review_hog/validators/{REVIEW_HOG_VALIDATION_SKILL_NAME}/"

        first = self.client.patch(url, {"active": True}, format="json")
        second = self.client.patch(url, {"active": True}, format="json")

        assert first.status_code == 200
        assert second.status_code == 200
        config = ReviewSkillConfig.objects.for_team(self.team.id).get(
            user_id=self.user.id, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME
        )
        assert config.team_id == self.team.id
        assert config.enabled is True
