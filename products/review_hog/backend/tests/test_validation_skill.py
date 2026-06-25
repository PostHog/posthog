import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command

from products.review_hog.backend.reviewer.lazy_seed import (
    REVIEW_HOG_SKILL_CATEGORY,
    discover_canonical_validation,
    sync_canonical_validation,
)
from products.review_hog.backend.reviewer.skill_loader import (
    REVIEW_HOG_VALIDATION_SKILL_NAME,
    ValidationSkillNotFoundError,
    load_validation_skill_for_run,
)
from products.skills.backend.models.skills import LLMSkill


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


class TestLoadValidationSkillForRun(BaseTest):
    def test_resolves_pinned_version_after_sync(self) -> None:
        sync_canonical_validation(self.team)

        loaded = load_validation_skill_for_run(self.team.id)

        assert loaded.skill_name == REVIEW_HOG_VALIDATION_SKILL_NAME
        assert loaded.version == 1

    def test_raises_when_missing(self) -> None:
        # No sync ran, so the team has no validation row — a real setup error, not a soft miss.
        with pytest.raises(ValidationSkillNotFoundError):
            load_validation_skill_for_run(self.team.id)


class TestSyncCommandSeedsValidation(BaseTest):
    def test_command_seeds_the_validation_skill(self) -> None:
        # Guards that the generalized command runs the validation syncer, not only perspectives.
        call_command("sync_review_hog_skills", team_id=self.team.id)
        assert LLMSkill.objects.filter(team=self.team, name=REVIEW_HOG_VALIDATION_SKILL_NAME, is_latest=True).exists()
