from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.lazy_seed import sync_canonical_resolution, sync_canonical_validation
from products.review_hog.backend.reviewer.skill_loader import (
    REVIEW_HOG_RESOLUTION_GAPS_SKILL_NAME,
    REVIEW_HOG_RESOLUTION_PREFIX,
    REVIEW_HOG_RESOLUTION_SKILL_NAME,
    REVIEW_HOG_RESOLUTION_SMALL_SKILL_NAME,
    REVIEW_HOG_VALIDATION_SKILL_NAME,
    load_resolution_skill_for_run,
)
from products.skills.backend.models.skills import LLMSkill

_CUSTOM = f"{REVIEW_HOG_RESOLUTION_PREFIX}conservative"


class TestReviewResolutionConfigAPI(APIBaseTest):
    """The wiring that is new for this kind — route, prefix constants, seed function, and the
    prefix scoping of the single-active swap. The shared single-active machinery (visibility,
    404s, env-url canonicalization, scopes) is covered by the validator/blind-spots suites."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        sync_canonical_resolution(self.team)
        self.base = f"/api/projects/{self.team.id}/review_hog/resolution"

    def test_list_seeds_the_default_active_and_shows_profiles_and_customs_inactive(self) -> None:
        # One assert per wiring seam: a wrong route 404s, a wrong seed function renders an empty
        # menu, a wrong prefix constant lists the wrong kind's skills. The fix profiles must be
        # listed but never auto-activated next to the default.
        LLMSkill.objects.create(
            team=self.team,
            name=_CUSTOM,
            description="d",
            body="x" * 250,
            version=1,
            is_latest=True,
            created_by=self.user,
        )

        res = self.client.get(f"{self.base}/")

        assert res.status_code == 200
        active_by_name = {item["skill_name"]: item["active"] for item in res.json()}
        assert active_by_name == {
            REVIEW_HOG_RESOLUTION_SKILL_NAME: True,
            REVIEW_HOG_RESOLUTION_GAPS_SKILL_NAME: False,
            REVIEW_HOG_RESOLUTION_SMALL_SKILL_NAME: False,
            _CUSTOM: False,
        }

    @parameterized.expand(
        [
            ("no_selection", None, REVIEW_HOG_RESOLUTION_SKILL_NAME),
            ("gaps_profile", REVIEW_HOG_RESOLUTION_GAPS_SKILL_NAME, REVIEW_HOG_RESOLUTION_GAPS_SKILL_NAME),
            ("small_profile", REVIEW_HOG_RESOLUTION_SMALL_SKILL_NAME, REVIEW_HOG_RESOLUTION_SMALL_SKILL_NAME),
        ]
    )
    def test_run_loads_the_selected_criteria(self, _name: str, selected: str | None, expected: str) -> None:
        # A profile has no `created_by`, so a loader that only treats the default as visible would
        # fall back to the default and silently ignore the user's selection.
        if selected is not None:
            res = self.client.patch(f"{self.base}/{selected}/", {"active": True}, format="json")
            assert res.status_code == 200, res.content

        loaded = load_resolution_skill_for_run(self.team.id, self.user.id)

        assert loaded.skill_name == expected

    def test_select_swaps_single_active_without_touching_other_kinds(self) -> None:
        # The swap's bulk deactivate must be scoped to the resolution prefix: a copy-paste error
        # keeping another kind's prefix would silently kill the user's validator selection in the
        # shared config table.
        sync_canonical_validation(self.team)
        configs = ReviewSkillConfig.objects.for_team(self.team.id)
        configs.create(
            team_id=self.team.id, user_id=self.user.id, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME, enabled=True
        )
        LLMSkill.objects.create(
            team=self.team,
            name=_CUSTOM,
            description="d",
            body="x" * 250,
            version=1,
            is_latest=True,
            created_by=self.user,
        )

        res = self.client.patch(f"{self.base}/{_CUSTOM}/", {"active": True}, format="json")

        assert res.status_code == 200, res.content
        by_name = dict(configs.filter(user_id=self.user.id).values_list("skill_name", "enabled"))
        assert by_name[_CUSTOM] is True
        assert by_name[REVIEW_HOG_RESOLUTION_SKILL_NAME] is False
        assert by_name[REVIEW_HOG_VALIDATION_SKILL_NAME] is True
