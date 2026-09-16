from pathlib import Path

import pytest

from products.reaper_hog.backend.logic.constants import VERIFICATION_SKILL_NAME
from products.reaper_hog.backend.logic.skill import SEEDED_BY, load_canonical_skill, sync_skill
from products.skills.backend.models.skills import LLMSkill

NAME = "reaper-hog-verification-criteria"


def _canonical(tmp_path: Path, body: str):
    skill_dir = tmp_path / NAME
    skill_dir.mkdir(exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {NAME}\ndescription: The bar.\n---\n\n{body}\n")
    return load_canonical_skill(NAME, skills_dir=tmp_path)


def test_the_shipped_skill_parses() -> None:
    canonical = load_canonical_skill()

    assert canonical.name == VERIFICATION_SKILL_NAME
    assert "On the fence means alive" in canonical.description
    assert canonical.body.startswith("# Dead code verification criteria")


@pytest.mark.django_db
class TestSyncSkill:
    def test_creates_then_bumps_only_when_the_canonical_changes(self, team, tmp_path: Path):
        first = sync_skill(team.id, _canonical(tmp_path, "v1 body"))
        unchanged = sync_skill(team.id, _canonical(tmp_path, "v1 body"))
        bumped = sync_skill(team.id, _canonical(tmp_path, "v2 body"))

        assert (first.version, unchanged.version, bumped.version) == (1, 1, 2)
        rows = {row.version: row for row in LLMSkill.objects.filter(team=team, name=NAME)}
        assert (rows[1].is_latest, rows[2].is_latest) == (False, True)
        assert rows[2].metadata["seeded_by"] == SEEDED_BY
        assert rows[2].body == "v2 body"

    def test_hand_authored_row_is_used_as_is(self, team, tmp_path: Path):
        LLMSkill.objects.create(team=team, name=NAME, description="mine", body="mine", version=4, is_latest=True)

        pinned = sync_skill(team.id, _canonical(tmp_path, "canonical body"))

        assert pinned.version == 4
        assert LLMSkill.objects.filter(team=team, name=NAME).count() == 1

    def test_archived_skill_comes_back_at_the_next_version(self, team, tmp_path: Path):
        sync_skill(team.id, _canonical(tmp_path, "body"))
        LLMSkill.objects.filter(team=team, name=NAME).update(deleted=True)

        pinned = sync_skill(team.id, _canonical(tmp_path, "body"))

        assert pinned.version == 2
        assert LLMSkill.objects.get(team=team, name=NAME, deleted=False).version == 2
