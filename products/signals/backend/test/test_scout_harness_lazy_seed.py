from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from products.ai_observability.backend.models.skills import LLMSkill
from products.signals.backend.scout_harness.lazy_seed import (
    CanonicalSkill,
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

    @pytest.mark.parametrize(
        "frontmatter_key",
        [
            # Backwards-compat form. Predates the agentskills.io spec alignment in this
            # codebase and is still in use by other PHS skills.
            "allowed_tools",
            # Spec form per agentskills.io — preferred for new canonical skills.
            "allowed-tools",
        ],
    )
    def test_parses_allowed_tools_in_either_frontmatter_form(self, tmp_path: Path, frontmatter_key: str) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter=f"""
                ---
                name: signals-scout-bar
                description: bar skill
                {frontmatter_key}:
                  - remember
                  - search_scratchpad
                ---
            """,
            body="# Bar\n",
        )
        skills = discover_canonical_skills(tmp_path)
        assert skills[0].allowed_tools == ("remember", "search_scratchpad")

    def test_rejects_both_allowed_tools_keys_set(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter="""
                ---
                name: signals-scout-bar
                description: bar skill
                allowed-tools:
                  - remember
                allowed_tools:
                  - search_scratchpad
                ---
            """,
            body="# Bar\n",
        )
        with pytest.raises(CanonicalSkillParseError, match="both 'allowed-tools' and 'allowed_tools'"):
            discover_canonical_skills(tmp_path)

    @pytest.mark.parametrize(
        "allowed_tools_value",
        [
            # YAML null — `allowed-tools:` with no value.
            "",
            " false",
            ' ""',
        ],
    )
    def test_rejects_falsy_non_list_allowed_tools(self, tmp_path: Path, allowed_tools_value: str) -> None:
        # A falsy-but-invalid value must fail fast, not silently fall back to `[]`
        # (which means "no tool narrowing" and would broaden tool access).
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter=f"""
                ---
                name: signals-scout-bar
                description: bar skill
                allowed-tools:{allowed_tools_value}
                ---
            """,
            body="# Bar\n",
        )
        with pytest.raises(CanonicalSkillParseError, match="must be a list of strings"):
            discover_canonical_skills(tmp_path)

    def test_parses_bundled_files_under_allowed_subdirs(self, tmp_path: Path) -> None:
        # `_ALLOWED_BUNDLE_SUBDIRS` is kept in lockstep with `hogli build:skills` —
        # `references/` and `scripts/` only. `assets/` and any other subdir are intentionally
        # ignored: silently bundling them here while the AI plugin build skips them would
        # produce different runtime behavior from the same source skill.
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
                "assets/template.txt": "hello {{name}}\n",
                "extras/notes.txt": "ignored\n",
            },
        )
        skills = discover_canonical_skills(tmp_path)
        files_by_path = {f.path: f for f in skills[0].files}
        assert "references/playbook.md" in files_by_path
        assert files_by_path["references/playbook.md"].content == "# Playbook\n"
        assert "scripts/check.py" in files_by_path
        # Files outside the allowlist must not leak in — guards the consumer divergence.
        assert "assets/template.txt" not in files_by_path
        assert "extras/notes.txt" not in files_by_path

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

    def test_oversized_body_raises(self, tmp_path: Path) -> None:
        # Body byte limit mirrors the REST API contract (MAX_SKILL_BODY_BYTES = 1 MB).
        # A canonical too big to seed should fail at parse time, not on DB write.
        body = "x" * (1_000_001)
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-big-body",
            frontmatter="""
                ---
                name: signals-scout-big-body
                description: oversized body
                ---
            """,
            body=body,
        )
        with pytest.raises(CanonicalSkillParseError, match="byte limit"):
            discover_canonical_skills(tmp_path)

    def test_oversized_bundled_file_raises(self, tmp_path: Path) -> None:
        # Per-file byte limit mirrors MAX_SKILL_FILE_BYTES (1 MB).
        oversized = "x" * (1_000_001)
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-big-file",
            frontmatter="""
                ---
                name: signals-scout-big-file
                description: oversized bundled file
                ---
            """,
            body="# Body\n",
            bundled_files={"references/huge.md": oversized},
        )
        with pytest.raises(CanonicalSkillParseError, match="byte limit"):
            discover_canonical_skills(tmp_path)

    def test_too_many_bundled_files_raises(self, tmp_path: Path) -> None:
        # File count limit mirrors MAX_SKILL_FILE_COUNT (50).
        bundled = {f"references/file_{i:03d}.md": f"# file {i}\n" for i in range(51)}
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-too-many",
            frontmatter="""
                ---
                name: signals-scout-too-many
                description: too many files
                ---
            """,
            body="# Body\n",
            bundled_files=bundled,
        )
        with pytest.raises(CanonicalSkillParseError, match="exceeding the 50 limit"):
            discover_canonical_skills(tmp_path)

    def test_overlong_path_raises(self, tmp_path: Path) -> None:
        # Path length matches LLMSkillFile.path max_length (500). Friendly parse-time
        # error beats the Postgres `value too long for type character varying(500)`.
        # Nested-dir construction because macOS rejects single filename segments >255 chars.
        nested_seg = "a" * 170
        rel_path = f"references/{nested_seg}/{nested_seg}/{nested_seg}/file.md"
        assert len(rel_path) > 500
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-long-path",
            frontmatter="""
                ---
                name: signals-scout-long-path
                description: overlong path
                ---
            """,
            body="# Body\n",
            bundled_files={rel_path: "x"},
        )
        with pytest.raises(CanonicalSkillParseError, match="char limit"):
            discover_canonical_skills(tmp_path)


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

    def test_partial_failure_rolls_back_whole_seed_and_retries(self) -> None:
        # A mid-loop failure must roll back every insert, so the next run retries the full set
        # instead of getting wedged with a partial seed the "already seeded" guard treats as done.
        fakes = (
            CanonicalSkill("signals-scout-a", "d", "body", (), (), Path(".")),
            CanonicalSkill("signals-scout-b", "d", "body", (), (), Path(".")),
        )
        real_create = LLMSkill.objects.create
        seen = {"n": 0}

        def flaky_create(**kwargs: object) -> LLMSkill:
            seen["n"] += 1
            if seen["n"] == 2:
                raise RuntimeError("boom")
            return real_create(**kwargs)

        with patch("products.signals.backend.scout_harness.lazy_seed.discover_canonical_skills", return_value=fakes):
            with patch.object(LLMSkill.objects, "create", side_effect=flaky_create):
                with pytest.raises(RuntimeError):
                    seed_canonical_skills(self.team)
        assert not LLMSkill.objects.filter(team=self.team, name__startswith="signals-scout-").exists()

        with patch("products.signals.backend.scout_harness.lazy_seed.discover_canonical_skills", return_value=fakes):
            result = seed_canonical_skills(self.team)
        assert set(result.created_skill_names) == {"signals-scout-a", "signals-scout-b"}
