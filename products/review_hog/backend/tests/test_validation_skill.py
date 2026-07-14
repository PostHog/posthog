import pytest
from posthog.test.base import BaseTest

from posthog.models import User

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.lazy_seed import (
    REVIEW_HOG_SKILL_CATEGORY,
    discover_canonical_validation,
    sync_canonical_validation,
)
from products.review_hog.backend.reviewer.skill_loader import (
    CANONICAL_VALIDATION_SKILL_NAMES,
    REVIEW_HOG_VALIDATION_PREFIX,
    REVIEW_HOG_VALIDATION_SKILL_NAME,
    ValidationSkillNotFoundError,
    load_validation_skill_for_run,
    register_missing_validation_config,
)
from products.review_hog.backend.temporal.activities import _sync_review_skills
from products.skills.backend.api.skill_services import publish_skill_version
from products.skills.backend.models.skills import LLMSkill

_CUSTOM_VALIDATOR = f"{REVIEW_HOG_VALIDATION_PREFIX}strict"


def _author_validator_skill(team, name: str) -> LLMSkill:
    return LLMSkill.objects.create(
        team=team, name=name, description="custom", body="x" * 250, version=1, is_latest=True
    )


def test_discover_finds_the_validation_criteria_skill() -> None:
    # The on-disk validation SKILL.md must parse and be the single canonical criteria skill — a
    # renamed dir or frontmatter-name typo would silently leave the validator with no criteria.
    assert {s.name for s in discover_canonical_validation()} == {REVIEW_HOG_VALIDATION_SKILL_NAME}


class TestSyncCanonicalValidation(BaseTest):
    def test_creates_a_seeded_row_in_the_validation_category(self) -> None:
        result = sync_canonical_validation(self.team)

        assert result.created_skill_names == (REVIEW_HOG_VALIDATION_SKILL_NAME,)
        row = LLMSkill.objects.get(team=self.team, name=REVIEW_HOG_VALIDATION_SKILL_NAME, is_latest=True)
        # Both review-hog skill sets share one category (one "Code review" tab); a wrong category
        # strands the skill — categorized skills are hidden from the default tab.
        assert row.category == REVIEW_HOG_SKILL_CATEGORY
        assert len(row.body) > 200  # the criteria body moved to disk, not an empty stub

    def test_leaves_team_edited_row_alone(self) -> None:
        # The cold-start sync runs before every review, so a team that rewrote its validation bar
        # must keep that edit — clobbering it here would silently wipe the customization mid-run.
        sync_canonical_validation(self.team)
        edited = LLMSkill.objects.get(team=self.team, name=REVIEW_HOG_VALIDATION_SKILL_NAME, is_latest=True)
        edited.body = "the team rewrote the validation bar"
        edited.save(update_fields=["body"])

        result = sync_canonical_validation(self.team)

        assert REVIEW_HOG_VALIDATION_SKILL_NAME in result.diverged_skill_names
        assert REVIEW_HOG_VALIDATION_SKILL_NAME not in result.updated_skill_names
        latest = LLMSkill.objects.get(team=self.team, name=REVIEW_HOG_VALIDATION_SKILL_NAME, is_latest=True)
        assert latest.version == 1
        assert latest.body == "the team rewrote the validation bar"


class TestRegisterMissingValidationConfig(BaseTest):
    def test_seeds_the_canonical_validator_enabled_and_is_idempotent(self) -> None:
        # Seeding enables the canonical validator for the user (so a cold user has a default selected)
        # and must NOT auto-create a config for a custom validator. Re-running must not duplicate rows.
        _author_validator_skill(self.team, _CUSTOM_VALIDATOR)
        register_missing_validation_config(self.team.id, self.user.id)
        register_missing_validation_config(self.team.id, self.user.id)

        rows = ReviewSkillConfig.objects.for_team(self.team.id).filter(
            user_id=self.user.id, skill_name__startswith=REVIEW_HOG_VALIDATION_PREFIX
        )
        assert {r.skill_name for r in rows} == set(CANONICAL_VALIDATION_SKILL_NAMES)
        assert all(r.enabled for r in rows)

    def test_does_not_re_enable_the_disabled_canonical(self) -> None:
        # Single-active: after a user selects a custom validator (canonical off), the next run's seed
        # must NOT flip the canonical back on — that would leave two validators active.
        register_missing_validation_config(self.team.id, self.user.id)
        ReviewSkillConfig.objects.for_team(self.team.id).filter(
            user_id=self.user.id, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME
        ).update(enabled=False)

        register_missing_validation_config(self.team.id, self.user.id)

        config = ReviewSkillConfig.objects.for_team(self.team.id).get(
            user_id=self.user.id, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME
        )
        assert config.enabled is False


class TestLoadValidationSkillForRun(BaseTest):
    def test_cold_user_gets_the_canonical_pinned(self) -> None:
        # A user who never selected anything: seeding enables the canonical, the loader resolves it
        # pinned to the synced latest version.
        sync_canonical_validation(self.team)

        loaded = load_validation_skill_for_run(self.team.id, self.user.id)

        assert loaded.skill_name == REVIEW_HOG_VALIDATION_SKILL_NAME
        assert loaded.version == 1

    def test_pins_the_team_edited_version(self) -> None:
        # The run must pull the team's edited validator, not the canonical original — that's the
        # whole point of team-level customization. Edits via the real publish path (bumps version).
        sync_canonical_validation(self.team)
        publish_skill_version(
            self.team,
            user=self.user,
            skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME,
            body="only flag issues that block the merge",
            base_version=1,
        )

        loaded = load_validation_skill_for_run(self.team.id, self.user.id)

        assert loaded.version == 2
        pinned = LLMSkill.objects.get(team=self.team, name=REVIEW_HOG_VALIDATION_SKILL_NAME, version=loaded.version)
        assert pinned.body == "only flag issues that block the merge"

    def test_resolves_the_selected_custom_validator(self) -> None:
        # The core "author a custom validator and run it" path: with the custom selected (canonical
        # off), the run resolves the custom validator, not the canonical default.
        sync_canonical_validation(self.team)
        _author_validator_skill(self.team, _CUSTOM_VALIDATOR)
        register_missing_validation_config(self.team.id, self.user.id)
        configs = ReviewSkillConfig.objects.for_team(self.team.id)
        configs.filter(user_id=self.user.id, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME).update(enabled=False)
        configs.create(team_id=self.team.id, user_id=self.user.id, skill_name=_CUSTOM_VALIDATOR, enabled=True)

        loaded = load_validation_skill_for_run(self.team.id, self.user.id)

        assert loaded.skill_name == _CUSTOM_VALIDATOR

    def test_falls_back_to_canonical_when_none_enabled(self) -> None:
        # No min-1 floor: if the user has no enabled validator row at all, the loader resolves the
        # canonical default rather than raising (the validator always has a fallback).
        sync_canonical_validation(self.team)
        register_missing_validation_config(self.team.id, self.user.id)
        ReviewSkillConfig.objects.for_team(self.team.id).filter(user_id=self.user.id).update(enabled=False)

        loaded = load_validation_skill_for_run(self.team.id, self.user.id)

        assert loaded.skill_name == REVIEW_HOG_VALIDATION_SKILL_NAME

    def test_falls_back_to_canonical_when_the_selected_skill_row_is_missing(self) -> None:
        # The user selected a custom validator whose skill row was later archived — the run falls
        # back to the canonical instead of failing until someone repairs the config.
        sync_canonical_validation(self.team)
        configs = ReviewSkillConfig.objects.for_team(self.team.id)
        register_missing_validation_config(self.team.id, self.user.id)
        configs.filter(user_id=self.user.id, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME).update(enabled=False)
        configs.create(
            team_id=self.team.id, user_id=self.user.id, skill_name=f"{REVIEW_HOG_VALIDATION_PREFIX}ghost", enabled=True
        )

        loaded = load_validation_skill_for_run(self.team.id, self.user.id)

        assert loaded.skill_name == REVIEW_HOG_VALIDATION_SKILL_NAME

    def test_raises_when_no_skill_synced(self) -> None:
        # No sync ran, so even the canonical fallback has no skill row — a real setup error.
        with pytest.raises(ValidationSkillNotFoundError):
            load_validation_skill_for_run(self.team.id, self.user.id)

    def test_selection_is_per_user(self) -> None:
        # Selecting a custom validator for one user must not affect another user's run.
        sync_canonical_validation(self.team)
        _author_validator_skill(self.team, _CUSTOM_VALIDATOR)
        other = User.objects.create(email="other-validator@example.com")
        configs = ReviewSkillConfig.objects.for_team(self.team.id)
        register_missing_validation_config(self.team.id, self.user.id)
        configs.filter(user_id=self.user.id, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME).update(enabled=False)
        configs.create(team_id=self.team.id, user_id=self.user.id, skill_name=_CUSTOM_VALIDATOR, enabled=True)

        mine = load_validation_skill_for_run(self.team.id, self.user.id)
        theirs = load_validation_skill_for_run(self.team.id, other.id)

        assert mine.skill_name == _CUSTOM_VALIDATOR
        assert theirs.skill_name == REVIEW_HOG_VALIDATION_SKILL_NAME


class TestColdStartSyncSeedsValidation(BaseTest):
    def test_cold_start_sync_seeds_the_validation_skill(self) -> None:
        # Guards that the run path's syncer list includes validation, not only perspectives.
        _sync_review_skills(self.team.id)
        assert LLMSkill.objects.filter(team=self.team, name=REVIEW_HOG_VALIDATION_SKILL_NAME, is_latest=True).exists()
