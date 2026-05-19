from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from posthog.test.base import BaseTest

from products.llm_analytics.backend.models.skills import LLMSkill
from products.signals.backend.scout_harness.lazy_seed import (
    CanonicalSkillParseError,
    discover_canonical_skills,
    seed_canonical_skills,
)
from products.signals.backend.scout_harness.skill_loader import load_skill_for_run


def _write_canonical_skill(
    base: Path,
    *,
    dir_name: str,
    frontmatter: str,
    body: str = "# Body\n",
    bundled_files: dict[str, str] | None = None,
) -> Path:
    skill_dir = base / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = textwrap.dedent(frontmatter).strip() + "\n" + body
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    for rel_path, content in (bundled_files or {}).items():
        target = skill_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return skill_dir


class TestDiscoverCanonicalSkills:
    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        assert discover_canonical_skills(tmp_path / "does-not-exist") == ()

    def test_walks_signals_scout_prefix_skills_only(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-foo",
            frontmatter="""
                ---
                name: signals-scout-foo
                description: foo skill
                ---
            """,
            body="# Foo\n",
        )
        _write_canonical_skill(
            tmp_path,
            dir_name="some-other-skill",
            frontmatter="""
                ---
                name: some-other-skill
                description: not a signals-scout
                ---
            """,
            body="# nope\n",
        )
        skills = discover_canonical_skills(tmp_path)
        assert [s.name for s in skills] == ["signals-scout-foo"]

    def test_parses_allowed_tools_when_present(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter="""
                ---
                name: signals-scout-bar
                description: bar skill
                allowed_tools:
                  - remember
                  - search_scratchpad
                ---
            """,
            body="# Bar\n",
        )
        skills = discover_canonical_skills(tmp_path)
        assert skills[0].allowed_tools == ("remember", "search_scratchpad")

    def test_parses_bundled_files_under_references_and_scripts(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter="""
                ---
                name: signals-scout-bar
                description: bar skill
                ---
            """,
            body="# Bar\n",
            bundled_files={
                "references/playbook.md": "# Playbook\n",
                "scripts/check.py": "print('hi')\n",
            },
        )
        skills = discover_canonical_skills(tmp_path)
        files_by_path = {f.path: f for f in skills[0].files}
        assert "references/playbook.md" in files_by_path
        assert files_by_path["references/playbook.md"].content == "# Playbook\n"
        assert "scripts/check.py" in files_by_path

    def test_missing_frontmatter_raises(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "signals-scout-foo"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# no frontmatter\n", encoding="utf-8")
        with pytest.raises(CanonicalSkillParseError):
            discover_canonical_skills(tmp_path)

    def test_wrong_name_prefix_in_frontmatter_raises(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter="""
                ---
                name: not-prefixed
                description: bar skill
                ---
            """,
            body="# Bar\n",
        )
        with pytest.raises(CanonicalSkillParseError):
            discover_canonical_skills(tmp_path)

    def test_in_repo_canonical_set_parses_cleanly(self) -> None:
        # Exercises the production manifest at `products/signals/skills/` — growing the
        # canonical set is a deliberate edit, so this serves as the lock.
        skills = discover_canonical_skills()
        assert any(s.name == "signals-scout-general" for s in skills)


class TestSeedCanonicalSkills(BaseTest):
    def test_seeds_canonicals_when_team_has_no_signals_scout_skills(self) -> None:
        result = seed_canonical_skills(self.team)
        assert "signals-scout-general" in result.created_skill_names
        seeded = LLMSkill.objects.get(team=self.team, name="signals-scout-general")
        assert seeded.is_latest is True
        assert seeded.body  # body copied from SKILL.md
        assert seeded.metadata["seeded_by"] == "signals_scout_harness"

    def test_no_op_when_team_already_has_signals_scout_skill(self) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-existing",
            description="team-edited copy",
            body="team body",
        )
        result = seed_canonical_skills(self.team)
        assert result.created_skill_names == ()
        assert result.skipped_reason and "already has" in result.skipped_reason
        existing = LLMSkill.objects.get(team=self.team, name="signals-scout-existing")
        assert existing.body == "team body"

    def test_no_op_preserves_archived_team_copies(self) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-archived",
            description="team archived this",
            body="team body",
            deleted=True,
            is_latest=False,
        )
        # Re-seeding archived rows would resurrect content the team deliberately removed.
        result = seed_canonical_skills(self.team)
        assert result.created_skill_names == ()
        assert not LLMSkill.objects.filter(team=self.team, name="signals-scout-general", deleted=False).exists()

    def test_idempotent_on_repeat_call(self) -> None:
        first = seed_canonical_skills(self.team)
        assert first.created_skill_names
        second = seed_canonical_skills(self.team)
        assert second.created_skill_names == ()
        count = LLMSkill.objects.filter(team=self.team, name__startswith="signals-scout-").count()
        assert count == len(first.created_skill_names)

    def test_seeded_skill_is_loadable_via_load_skill_for_run(self) -> None:
        seed_canonical_skills(self.team)
        loaded = load_skill_for_run(self.team, "signals-scout-general")
        assert loaded.name == "signals-scout-general"
        assert loaded.version == 1
        assert "Signals scout" in loaded.body
