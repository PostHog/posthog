from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from posthog.test.base import BaseTest

from products.llm_analytics.backend.models.skills import LLMSkill
from products.signals.backend.agent_harness.lazy_seed import (
    CanonicalSkillParseError,
    discover_canonical_skills,
    seed_canonical_skills,
)
from products.signals.backend.agent_harness.skill_loader import load_skill_for_run


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

    def test_walks_signals_agent_prefix_skills_only(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-agent-foo",
            frontmatter="""
                ---
                name: signals-agent-foo
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
                description: not a signals-agent
                ---
            """,
            body="# nope\n",
        )
        skills = discover_canonical_skills(tmp_path)
        assert [s.name for s in skills] == ["signals-agent-foo"]

    def test_parses_allowed_tools_underscore_form(self, tmp_path: Path) -> None:
        # Backwards-compat form. The spec uses `allowed-tools`; we accept this too.
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-agent-bar",
            frontmatter="""
                ---
                name: signals-agent-bar
                description: bar skill
                allowed_tools:
                  - remember
                  - search_memory
                ---
            """,
            body="# Bar\n",
        )
        skills = discover_canonical_skills(tmp_path)
        assert skills[0].allowed_tools == ("remember", "search_memory")

    def test_parses_allowed_tools_hyphen_form_per_agentskills_spec(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-agent-bar",
            frontmatter="""
                ---
                name: signals-agent-bar
                description: bar skill
                allowed-tools:
                  - remember
                  - search_memory
                ---
            """,
            body="# Bar\n",
        )
        skills = discover_canonical_skills(tmp_path)
        assert skills[0].allowed_tools == ("remember", "search_memory")

    def test_rejects_both_allowed_tools_keys_set(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-agent-bar",
            frontmatter="""
                ---
                name: signals-agent-bar
                description: bar skill
                allowed-tools:
                  - remember
                allowed_tools:
                  - search_memory
                ---
            """,
            body="# Bar\n",
        )
        with pytest.raises(CanonicalSkillParseError, match="both 'allowed-tools' and 'allowed_tools'"):
            discover_canonical_skills(tmp_path)

    def test_parses_bundled_files_under_references_scripts_and_assets(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-agent-bar",
            frontmatter="""
                ---
                name: signals-agent-bar
                description: bar skill
                ---
            """,
            body="# Bar\n",
            bundled_files={
                "references/playbook.md": "# Playbook\n",
                "scripts/check.py": "print('hi')\n",
                "assets/template.txt": "hello {{name}}\n",
            },
        )
        skills = discover_canonical_skills(tmp_path)
        files_by_path = {f.path: f for f in skills[0].files}
        assert "references/playbook.md" in files_by_path
        assert files_by_path["references/playbook.md"].content == "# Playbook\n"
        assert "scripts/check.py" in files_by_path
        assert "assets/template.txt" in files_by_path
        assert files_by_path["assets/template.txt"].content == "hello {{name}}\n"

    def test_missing_frontmatter_raises(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "signals-agent-foo"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# no frontmatter\n", encoding="utf-8")
        with pytest.raises(CanonicalSkillParseError):
            discover_canonical_skills(tmp_path)

    def test_wrong_name_prefix_in_frontmatter_raises(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-agent-bar",
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
        assert any(s.name == "signals-agent-scout" for s in skills)


class TestSeedCanonicalSkills(BaseTest):
    def test_seeds_canonicals_when_team_has_no_signals_agent_skills(self) -> None:
        result = seed_canonical_skills(self.team)
        assert "signals-agent-scout" in result.created_skill_names
        seeded = LLMSkill.objects.get(team=self.team, name="signals-agent-scout")
        assert seeded.is_latest is True
        assert seeded.body  # body copied from SKILL.md
        assert seeded.metadata["seeded_by"] == "signals_agent_harness"

    def test_no_op_when_team_already_has_signals_agent_skill(self) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="signals-agent-existing",
            description="team-edited copy",
            body="team body",
        )
        result = seed_canonical_skills(self.team)
        assert result.created_skill_names == ()
        assert result.skipped_reason and "already has" in result.skipped_reason
        existing = LLMSkill.objects.get(team=self.team, name="signals-agent-existing")
        assert existing.body == "team body"

    def test_no_op_preserves_archived_team_copies(self) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="signals-agent-archived",
            description="team archived this",
            body="team body",
            deleted=True,
            is_latest=False,
        )
        # Re-seeding archived rows would resurrect content the team deliberately removed.
        result = seed_canonical_skills(self.team)
        assert result.created_skill_names == ()
        assert not LLMSkill.objects.filter(team=self.team, name="signals-agent-scout", deleted=False).exists()

    def test_idempotent_on_repeat_call(self) -> None:
        first = seed_canonical_skills(self.team)
        assert first.created_skill_names
        second = seed_canonical_skills(self.team)
        assert second.created_skill_names == ()
        count = LLMSkill.objects.filter(team=self.team, name__startswith="signals-agent-").count()
        assert count == len(first.created_skill_names)

    def test_seeded_skill_is_loadable_via_load_skill_for_run(self) -> None:
        seed_canonical_skills(self.team)
        loaded = load_skill_for_run(self.team, "signals-agent-scout")
        assert loaded.name == "signals-agent-scout"
        assert loaded.version == 1
        assert "Signals scout" in loaded.body
