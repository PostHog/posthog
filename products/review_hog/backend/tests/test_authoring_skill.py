from posthog.test.base import BaseTest

from products.review_hog.backend.reviewer.lazy_seed import (
    REVIEW_HOG_SEEDED_BY,
    REVIEW_HOG_SKILL_CATEGORY,
    discover_canonical_authoring,
)
from products.review_hog.backend.reviewer.skill_loader import REVIEW_HOG_AUTHORING_SKILL_NAME
from products.review_hog.backend.temporal.activities import _sync_review_skills
from products.skills.backend.models.skills import LLMSkill


def test_discover_finds_the_authoring_skill() -> None:
    # The on-disk SKILL.md must parse and match the loader's canonical name — a renamed dir or a
    # frontmatter-name typo would make the "Create your own …" prompts point at a skill that never
    # seeds, so every authoring task starts blind.
    assert {s.name for s in discover_canonical_authoring()} == {REVIEW_HOG_AUTHORING_SKILL_NAME}


class TestAuthoringSkillSync(BaseTest):
    def test_run_sync_seeds_the_authoring_skill(self) -> None:
        # The run path is the recurring reconciliation moment — dropping the authoring sync from it
        # would freeze every team's guide at whatever version they first seeded.
        _sync_review_skills(self.team.id)

        row = LLMSkill.objects.get(team=self.team, name=REVIEW_HOG_AUTHORING_SKILL_NAME, is_latest=True)
        assert row.metadata["seeded_by"] == REVIEW_HOG_SEEDED_BY
        assert row.category == REVIEW_HOG_SKILL_CATEGORY
