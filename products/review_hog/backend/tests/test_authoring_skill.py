from pathlib import Path

from posthog.test.base import BaseTest

from products.review_hog.backend.reviewer.lazy_seed import (
    REVIEW_HOG_SEEDED_BY,
    REVIEW_HOG_SKILL_CATEGORY,
    discover_canonical_authoring,
)
from products.review_hog.backend.reviewer.skill_loader import (
    REVIEW_HOG_AUTHORING_PREFIX,
    REVIEW_HOG_AUTHORING_SKILL_NAME,
)
from products.review_hog.backend.temporal.activities import _sync_review_skills
from products.skills.backend.models.skills import LLMSkill


def test_discover_finds_the_authoring_skill() -> None:
    # The on-disk SKILL.md must parse and match the loader's canonical name — a renamed dir or a
    # frontmatter-name typo would make the "Create your own …" prompts point at a skill that never
    # seeds, so every authoring task starts blind.
    assert {s.name for s in discover_canonical_authoring()} == {REVIEW_HOG_AUTHORING_SKILL_NAME}


def test_discover_skips_bytecode_caches_under_bundled_scripts(tmp_path: Path) -> None:
    skill_dir = tmp_path / f"{REVIEW_HOG_AUTHORING_PREFIX}-guide"
    (skill_dir / "scripts" / "__pycache__").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {REVIEW_HOG_AUTHORING_PREFIX}-guide\ndescription: guide\n---\n# Guide\n", encoding="utf-8"
    )
    (skill_dir / "scripts" / "check.py").write_text("print('hi')\n", encoding="utf-8")
    (skill_dir / "scripts" / "__pycache__" / "check.cpython-313.pyc").write_bytes(b"\x00\xff\x0d\x0a")

    (skill,) = discover_canonical_authoring(skills_dir=tmp_path)

    assert [f.path for f in skill.files] == ["scripts/check.py"]


class TestAuthoringSkillSync(BaseTest):
    def test_run_sync_seeds_the_authoring_skill(self) -> None:
        # The run path is the recurring reconciliation moment — dropping the authoring sync from it
        # would freeze every team's guide at whatever version they first seeded.
        _sync_review_skills(self.team.id)

        row = LLMSkill.objects.get(team=self.team, name=REVIEW_HOG_AUTHORING_SKILL_NAME, is_latest=True)
        assert row.metadata["seeded_by"] == REVIEW_HOG_SEEDED_BY
        assert row.category == REVIEW_HOG_SKILL_CATEGORY
