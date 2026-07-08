import pytest
from posthog.test.base import BaseTest

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.lazy_seed import (
    discover_canonical_blind_spots,
    sync_canonical_blind_spots,
    sync_canonical_validation,
)
from products.review_hog.backend.reviewer.skill_loader import (
    REVIEW_HOG_BLIND_SPOTS_PREFIX,
    REVIEW_HOG_BLIND_SPOTS_SKILL_NAME,
    REVIEW_HOG_VALIDATION_SKILL_NAME,
    BlindSpotsSkillNotFoundError,
    load_blind_spots_skill_for_run,
    register_missing_blind_spots_config,
)
from products.review_hog.backend.temporal.activities import _sync_review_skills
from products.skills.backend.models.skills import LLMSkill

_CUSTOM = f"{REVIEW_HOG_BLIND_SPOTS_PREFIX}security-sweep"


def test_discover_finds_the_blind_spots_skill() -> None:
    # The on-disk SKILL.md must parse and match the loader's canonical name — a renamed dir or a
    # frontmatter-name typo would make every review hard-fail at the blind-spots load.
    assert {s.name for s in discover_canonical_blind_spots()} == {REVIEW_HOG_BLIND_SPOTS_SKILL_NAME}


class TestLoadBlindSpotsSkillForRun(BaseTest):
    def _author_custom(self) -> None:
        LLMSkill.objects.create(
            team=self.team, name=_CUSTOM, description="custom sweep", body="x" * 250, version=1, is_latest=True
        )

    def test_cold_user_gets_the_canonical_pinned(self) -> None:
        # A cold user resolves the canonical pinned to the synced version — the always-on sweep
        # must never lack a skill.
        sync_canonical_blind_spots(self.team)

        loaded = load_blind_spots_skill_for_run(self.team.id, self.user.id)

        assert loaded.skill_name == REVIEW_HOG_BLIND_SPOTS_SKILL_NAME
        assert loaded.version == 1

    def test_resolves_the_selected_custom_skill(self) -> None:
        # With a custom sweep selected (canonical off), the run resolves the custom skill.
        sync_canonical_blind_spots(self.team)
        self._author_custom()
        register_missing_blind_spots_config(self.team.id, self.user.id)
        configs = ReviewSkillConfig.objects.for_team(self.team.id)
        configs.filter(user_id=self.user.id, skill_name=REVIEW_HOG_BLIND_SPOTS_SKILL_NAME).update(enabled=False)
        configs.create(team_id=self.team.id, user_id=self.user.id, skill_name=_CUSTOM, enabled=True)

        loaded = load_blind_spots_skill_for_run(self.team.id, self.user.id)

        assert loaded.skill_name == _CUSTOM

    def test_ignores_other_prefixes_in_the_shared_table(self) -> None:
        # Prefix-scoped in the shared config table: a user whose only enabled row is a VALIDATOR
        # still falls back to the blind-spots canonical, never to the validation criteria.
        sync_canonical_blind_spots(self.team)
        sync_canonical_validation(self.team)
        register_missing_blind_spots_config(self.team.id, self.user.id)
        configs = ReviewSkillConfig.objects.for_team(self.team.id)
        configs.filter(user_id=self.user.id, skill_name=REVIEW_HOG_BLIND_SPOTS_SKILL_NAME).update(enabled=False)
        configs.create(
            team_id=self.team.id, user_id=self.user.id, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME, enabled=True
        )

        loaded = load_blind_spots_skill_for_run(self.team.id, self.user.id)

        assert loaded.skill_name == REVIEW_HOG_BLIND_SPOTS_SKILL_NAME

    def test_falls_back_to_canonical_when_the_selected_skill_row_is_missing(self) -> None:
        # A selected sweep whose skill row was archived falls back to the canonical, not a dead run.
        sync_canonical_blind_spots(self.team)
        register_missing_blind_spots_config(self.team.id, self.user.id)
        configs = ReviewSkillConfig.objects.for_team(self.team.id)
        configs.filter(user_id=self.user.id, skill_name=REVIEW_HOG_BLIND_SPOTS_SKILL_NAME).update(enabled=False)
        configs.create(
            team_id=self.team.id, user_id=self.user.id, skill_name=f"{REVIEW_HOG_BLIND_SPOTS_PREFIX}ghost", enabled=True
        )

        loaded = load_blind_spots_skill_for_run(self.team.id, self.user.id)

        assert loaded.skill_name == REVIEW_HOG_BLIND_SPOTS_SKILL_NAME

    def test_raises_when_no_skill_synced(self) -> None:
        # No sync ran, so even the canonical fallback has no row — a setup error, fail loudly.
        with pytest.raises(BlindSpotsSkillNotFoundError):
            load_blind_spots_skill_for_run(self.team.id, self.user.id)


class TestColdStartSyncSeedsBlindSpots(BaseTest):
    def test_cold_start_sync_seeds_the_blind_spots_skill(self) -> None:
        # Guards that the run path's syncer list includes blind spots — the only sync moment there is.
        _sync_review_skills(self.team.id)
        assert LLMSkill.objects.filter(team=self.team, name=REVIEW_HOG_BLIND_SPOTS_SKILL_NAME, is_latest=True).exists()
