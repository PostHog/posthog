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
from products.skills.backend.api.skill_services import publish_skill_version
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


class TestLoadValidationSkillForRun(BaseTest):
    def test_resolves_pinned_version_after_sync(self) -> None:
        sync_canonical_validation(self.team)

        loaded = load_validation_skill_for_run(self.team.id)

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

        loaded = load_validation_skill_for_run(self.team.id)

        assert loaded.version == 2
        pinned = LLMSkill.objects.get(team=self.team, name=REVIEW_HOG_VALIDATION_SKILL_NAME, version=loaded.version)
        assert pinned.body == "only flag issues that block the merge"

    def test_raises_when_missing(self) -> None:
        # No sync ran, so the team has no validation row — a real setup error, not a soft miss.
        with pytest.raises(ValidationSkillNotFoundError):
            load_validation_skill_for_run(self.team.id)


class TestSyncCommandSeedsValidation(BaseTest):
    def test_command_seeds_the_validation_skill(self) -> None:
        # Guards that the generalized command runs the validation syncer, not only perspectives.
        call_command("sync_review_hog_skills", team_id=self.team.id)
        assert LLMSkill.objects.filter(team=self.team, name=REVIEW_HOG_VALIDATION_SKILL_NAME, is_latest=True).exists()
