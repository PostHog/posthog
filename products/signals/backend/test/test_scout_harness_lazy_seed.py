from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.config_registry import register_missing_configs
from products.signals.backend.scout_harness.lazy_seed import (
    CanonicalSkill,
    CanonicalSkillFile,
    CanonicalSkillParseError,
    SyncResult,
    _compute_canonical_hash,
    _compute_row_hash,
    discover_canonical_skills,
    seed_canonical_skills,
    sync_canonical_skills,
)
from products.signals.backend.scout_harness.skill_loader import load_skill_for_run
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile


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


def _make_canonical(
    name: str,
    *,
    description: str = "test skill",
    body: str = "# Body\n",
    allowed_tools: tuple[str, ...] = (),
    files: tuple[CanonicalSkillFile, ...] = (),
) -> CanonicalSkill:
    """Build a CanonicalSkill for a unit test without going through disk + frontmatter."""
    return CanonicalSkill(
        name=name,
        description=description,
        body=body,
        allowed_tools=allowed_tools,
        files=files,
        source_path=Path("/tmp/fake"),
    )


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

    def test_discovers_companion_dirs_from_allowlist(self, tmp_path: Path) -> None:
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
            dir_name="authoring-scouts",
            frontmatter="""
                ---
                name: authoring-scouts
                description: companion authoring guide
                ---
            """,
            body="# Authoring\n",
        )
        # Not in the allowlist → still skipped, same as before companions existed.
        _write_canonical_skill(
            tmp_path,
            dir_name="some-other-skill",
            frontmatter="""
                ---
                name: some-other-skill
                description: not canonical
                ---
            """,
            body="# nope\n",
        )
        skills = discover_canonical_skills(tmp_path)
        assert [s.name for s in skills] == ["authoring-scouts", "signals-scout-foo"]

    def test_companion_name_with_scout_prefix_raises(self, tmp_path: Path) -> None:
        # A scout-prefixed name on a companion would get a SignalScoutConfig from
        # register_missing_configs and be dispatched as a scout — reject at parse time.
        _write_canonical_skill(
            tmp_path,
            dir_name="authoring-scouts",
            frontmatter="""
                ---
                name: signals-scout-authoring
                description: masquerading companion
                ---
            """,
        )
        with pytest.raises(CanonicalSkillParseError, match="must not start with"):
            discover_canonical_skills(tmp_path)

    def test_companion_name_must_match_directory(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="authoring-scouts",
            frontmatter="""
                ---
                name: authoring-scouts-renamed
                description: drifted frontmatter name
                ---
            """,
        )
        with pytest.raises(CanonicalSkillParseError, match="must match its directory"):
            discover_canonical_skills(tmp_path)

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

    def test_duplicate_frontmatter_name_raises(self, tmp_path: Path) -> None:
        # Two directories declaring the same `name` would make the sync flap the team's row
        # between both definitions every coordinator tick — reject it at discovery.
        for dir_name in ("signals-scout-dup-a", "signals-scout-dup-b"):
            _write_canonical_skill(
                tmp_path,
                dir_name=dir_name,
                frontmatter="""
                    ---
                    name: signals-scout-dup
                    description: dup skill
                    ---
                """,
                body=f"# {dir_name}\n",
            )
        with pytest.raises(CanonicalSkillParseError, match="Duplicate canonical skill name"):
            discover_canonical_skills(tmp_path)

    def test_in_repo_canonical_set_parses_cleanly(self) -> None:
        # Exercises the production manifest at `products/signals/skills/` — growing the
        # canonical set is a deliberate edit, so this serves as the lock.
        skills = discover_canonical_skills()
        names = {s.name for s in skills}
        # A subset lock on the canonical fleet: general (cross-product) + 4 focused
        # specialists. Each scout is self-contained (no deps between skills) and runs on
        # its own schedule. Adding a new specialist is a deliberate edit — extend this set
        # when shipping.
        expected = {
            "signals-scout-general",
            "signals-scout-ai-observability",
            "signals-scout-logs",
            "signals-scout-error-tracking",
            "signals-scout-revenue-analytics",
            # Companion (non-scout) skill, seeded so store-only agents can read the
            # authoring guide via llma-skill-get.
            "authoring-scouts",
        }
        assert expected.issubset(names), f"missing canonical skills: {expected - names}"

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


class TestComputeCanonicalHash:
    def test_same_input_yields_same_hash(self) -> None:
        a = _make_canonical("signals-scout-foo", body="hello", allowed_tools=("a", "b"))
        b = _make_canonical("signals-scout-foo", body="hello", allowed_tools=("a", "b"))
        assert _compute_canonical_hash(a) == _compute_canonical_hash(b)

    def test_body_change_changes_hash(self) -> None:
        a = _make_canonical("signals-scout-foo", body="v1")
        b = _make_canonical("signals-scout-foo", body="v2")
        assert _compute_canonical_hash(a) != _compute_canonical_hash(b)

    def test_description_change_changes_hash(self) -> None:
        a = _make_canonical("signals-scout-foo", description="alpha", body="x")
        b = _make_canonical("signals-scout-foo", description="beta", body="x")
        assert _compute_canonical_hash(a) != _compute_canonical_hash(b)

    def test_allowed_tools_reorder_does_not_change_hash(self) -> None:
        # Sorted internally so frontmatter-listing-order changes don't churn the hash.
        a = _make_canonical("signals-scout-foo", allowed_tools=("a", "b"))
        b = _make_canonical("signals-scout-foo", allowed_tools=("b", "a"))
        assert _compute_canonical_hash(a) == _compute_canonical_hash(b)

    def test_bundle_change_changes_hash(self) -> None:
        # References-only edits are the easy thing to forget; this is the lock.
        f1 = (CanonicalSkillFile(path="references/x.md", content="v1"),)
        f2 = (CanonicalSkillFile(path="references/x.md", content="v2"),)
        a = _make_canonical("signals-scout-foo", files=f1)
        b = _make_canonical("signals-scout-foo", files=f2)
        assert _compute_canonical_hash(a) != _compute_canonical_hash(b)

    def test_canonical_and_row_hashes_agree_when_content_matches(self) -> None:
        """When a row's content matches the canonical exactly, the two hashing helpers
        produce the same digest. This is the round-trip the sync function depends on."""
        canonical = _make_canonical(
            "signals-scout-foo",
            description="d",
            body="b",
            allowed_tools=("x", "y"),
            files=(CanonicalSkillFile(path="references/r.md", content="r"),),
        )
        # Build a fake LLMSkill / LLMSkillFile pair that mirrors the canonical exactly. We
        # avoid hitting the DB for this — _compute_row_hash only reads attributes.
        skill = LLMSkill(
            description=canonical.description,
            body=canonical.body,
            allowed_tools=list(canonical.allowed_tools),
        )
        files = [LLMSkillFile(path=f.path, content=f.content, content_type=f.content_type) for f in canonical.files]
        assert _compute_canonical_hash(canonical) == _compute_row_hash(skill, files)


class TestSyncCanonicalSkills(BaseTest):
    """End-to-end behavior of the canonical-sync function on a real DB.

    Each test patches `discover_canonical_skills` so we control what "canonical" means
    rather than depending on the in-repo fleet content. The in-repo behavior is locked
    by `test_in_repo_canonical_set_parses_cleanly` above.
    """

    def _patch_canonicals(self, canonicals: tuple[CanonicalSkill, ...]):
        return patch(
            "products.signals.backend.scout_harness.lazy_seed.discover_canonical_skills",
            return_value=canonicals,
        )

    def test_creates_rows_for_brand_new_team(self) -> None:
        canonical = _make_canonical("signals-scout-alpha", body="initial")
        with self._patch_canonicals((canonical,)):
            result = sync_canonical_skills(self.team)

        assert result.created_skill_names == ("signals-scout-alpha",)
        assert result.updated_skill_names == ()
        row = LLMSkill.objects.get(team=self.team, name="signals-scout-alpha", is_latest=True, deleted=False)
        assert row.body == "initial"
        assert row.metadata["seeded_by"] == "signals_scout_harness"
        # Hash is now stamped at create time so future syncs can compare.
        assert row.metadata["canonical_hash"] == _compute_canonical_hash(canonical)

    def test_companion_skill_seeds_without_scout_config(self) -> None:
        scout = _make_canonical("signals-scout-alpha")
        companion = _make_canonical("authoring-scouts", body="# Authoring guide\n")
        with self._patch_canonicals((scout, companion)):
            result = sync_canonical_skills(self.team)

        assert set(result.created_skill_names) == {"signals-scout-alpha", "authoring-scouts"}
        row = LLMSkill.objects.get(team=self.team, name="authoring-scouts", is_latest=True, deleted=False)
        assert row.metadata["seeded_by"] == "signals_scout_harness"

        # The companion never materializes a scout config — only prefix-matching skills do.
        live_skills = register_missing_configs(self.team.id)
        assert live_skills == {"signals-scout-alpha"}
        assert not SignalScoutConfig.all_teams.filter(team=self.team, skill_name="authoring-scouts").exists()

    def test_prune_skipped_when_no_scout_canonicals_discovered(self) -> None:
        # A disk read that surfaces only companions (broken checkout, partial deploy) must
        # not let the prune pass tombstone the team's entire seeded fleet.
        scout = _make_canonical("signals-scout-alpha")
        with self._patch_canonicals((scout,)):
            sync_canonical_skills(self.team)

        companion = _make_canonical("authoring-scouts")
        with self._patch_canonicals((companion,)):
            result = sync_canonical_skills(self.team, prune=True)

        assert result.pruned_skill_names == ()
        row = LLMSkill.objects.get(team=self.team, name="signals-scout-alpha", is_latest=True)
        assert row.deleted is False

    def test_no_op_when_team_row_already_matches_canonical(self) -> None:
        canonical = _make_canonical("signals-scout-alpha", body="initial")
        with self._patch_canonicals((canonical,)):
            sync_canonical_skills(self.team)
            # Second call against unchanged canonical produces no further work.
            result = sync_canonical_skills(self.team)

        assert result.created_skill_names == ()
        assert result.updated_skill_names == ()
        assert LLMSkill.objects.filter(team=self.team, name="signals-scout-alpha", is_latest=True).count() == 1

    def test_updates_when_canonical_changes_and_team_has_not_edited(self) -> None:
        # Initial sync writes v1 with the original content.
        v1 = _make_canonical("signals-scout-alpha", body="v1 body")
        with self._patch_canonicals((v1,)):
            sync_canonical_skills(self.team)

        # We ship a SKILL.md change. Same name, different body. Team hasn't touched theirs.
        v2 = _make_canonical("signals-scout-alpha", body="v2 body — improved scout calibration")
        with self._patch_canonicals((v2,)):
            result = sync_canonical_skills(self.team)

        assert result.updated_skill_names == ("signals-scout-alpha",)
        # Old row demoted, new row at version=2 with the new content.
        rows = LLMSkill.objects.filter(team=self.team, name="signals-scout-alpha").order_by("version")
        assert [r.version for r in rows] == [1, 2]
        latest = rows.get(version=2)
        assert latest.is_latest is True
        assert latest.body == "v2 body — improved scout calibration"
        assert latest.metadata["canonical_hash"] == _compute_canonical_hash(v2)
        # Old row is preserved as version history but no longer latest.
        old = rows.get(version=1)
        assert old.is_latest is False
        assert old.body == "v1 body"

    def test_leaves_diverged_team_edits_alone(self) -> None:
        v1 = _make_canonical("signals-scout-alpha", body="v1 body")
        with self._patch_canonicals((v1,)):
            sync_canonical_skills(self.team)

        # Simulate a user edit: bump the row's body without touching the canonical_hash
        # in metadata. Real PHS edits would do the version-bump dance; for the test we
        # mutate in place since the hash mismatch is what matters.
        row = LLMSkill.objects.get(team=self.team, name="signals-scout-alpha", is_latest=True)
        row.body = "team edited this"
        row.save()

        # Now we ship a v2 canonical. Team's content drifted from stored hash → diverged.
        v2 = _make_canonical("signals-scout-alpha", body="v2 body")
        with self._patch_canonicals((v2,)):
            result = sync_canonical_skills(self.team)

        assert result.diverged_skill_names == ("signals-scout-alpha",)
        assert result.updated_skill_names == ()
        # Team's edit survived.
        latest = LLMSkill.objects.get(team=self.team, name="signals-scout-alpha", is_latest=True)
        assert latest.body == "team edited this"

    def test_leaves_hand_authored_row_sharing_a_canonical_name_alone(self) -> None:
        # A team hand-authors a row whose name collides with a canonical, with no seeded_by
        # tag. We must never overwrite it: first sync reports it diverged, and a later
        # canonical change still leaves the content intact.
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-alpha",
            description="team's own",
            body="hand authored",
            is_latest=True,
        )

        v1 = _make_canonical("signals-scout-alpha", body="canonical v1")
        with self._patch_canonicals((v1,)):
            first = sync_canonical_skills(self.team)
        assert first.diverged_skill_names == ("signals-scout-alpha",)

        v2 = _make_canonical("signals-scout-alpha", body="canonical v2")
        with self._patch_canonicals((v2,)):
            second = sync_canonical_skills(self.team)
        assert second.diverged_skill_names == ("signals-scout-alpha",)
        assert second.updated_skill_names == ()

        latest = LLMSkill.objects.get(team=self.team, name="signals-scout-alpha", is_latest=True)
        assert latest.body == "hand authored"

    def test_skips_tombstoned_rows(self) -> None:
        # Team explicitly deleted the skill — no live row, just a soft-deleted archive.
        # The sync must respect that and not re-create the canonical content.
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-alpha",
            description="archived",
            body="team body",
            deleted=True,
            is_latest=False,
        )
        canonical = _make_canonical("signals-scout-alpha", body="latest canonical")
        with self._patch_canonicals((canonical,)):
            result = sync_canonical_skills(self.team)

        assert result.tombstoned_skill_names == ("signals-scout-alpha",)
        assert result.created_skill_names == ()
        assert not LLMSkill.objects.filter(
            team=self.team, name="signals-scout-alpha", deleted=False, is_latest=True
        ).exists()

    def test_creates_new_specialist_for_already_seeded_team(self) -> None:
        # A team got seeded before we shipped a new specialist. Per-canonical iteration
        # means the new one shows up; the existing ones are no-ops.
        existing = _make_canonical("signals-scout-alpha", body="alpha body")
        with self._patch_canonicals((existing,)):
            sync_canonical_skills(self.team)

        new_specialist = _make_canonical("signals-scout-beta", body="beta body")
        with self._patch_canonicals((existing, new_specialist)):
            result = sync_canonical_skills(self.team)

        assert result.created_skill_names == ("signals-scout-beta",)
        assert result.updated_skill_names == ()
        assert LLMSkill.objects.filter(team=self.team, name="signals-scout-beta", is_latest=True).exists()

    def test_prunes_rows_whose_canonical_was_removed_from_disk(self) -> None:
        # Two specialists seeded, then one is removed from the canonical fleet on disk. The
        # reverse-reconciliation pass must tombstone the orphaned live row so the coordinator
        # stops dispatching a scout that's no longer part of the fleet.
        alpha = _make_canonical("signals-scout-alpha", body="alpha body")
        beta = _make_canonical("signals-scout-beta", body="beta body")
        with self._patch_canonicals((alpha, beta)):
            sync_canonical_skills(self.team)
        assert LLMSkill.objects.filter(
            team=self.team, name="signals-scout-beta", is_latest=True, deleted=False
        ).exists()

        # beta is deleted from disk — only alpha remains canonical.
        with self._patch_canonicals((alpha,)):
            result = sync_canonical_skills(self.team, prune=True)

        assert result.pruned_skill_names == ("signals-scout-beta",)
        assert result.updated_skill_names == ()
        # beta's live row is soft-deleted; alpha is untouched and still live.
        beta_row = LLMSkill.objects.get(team=self.team, name="signals-scout-beta")
        assert beta_row.deleted is True
        assert beta_row.is_latest is False
        assert LLMSkill.objects.filter(
            team=self.team, name="signals-scout-alpha", is_latest=True, deleted=False
        ).exists()

    def test_prune_leaves_edited_fork_alone(self) -> None:
        # A team edits a scout we seeded (a "fork"), then we retire that canonical from disk.
        # Prune must NOT tombstone the fork — deleting a scout the team customized and chose to
        # keep would be a nasty surprise. Mirrors the fork-protection the update path applies.
        alpha = _make_canonical("signals-scout-alpha", body="alpha body")
        beta = _make_canonical("signals-scout-beta", body="beta body")
        with self._patch_canonicals((alpha, beta)):
            sync_canonical_skills(self.team)

        # Team edits their beta copy — body diverges from the stored canonical_hash, while
        # seeded_by and the old hash carry forward (what a real PHS edit produces).
        beta_row = LLMSkill.objects.get(team=self.team, name="signals-scout-beta", is_latest=True)
        beta_row.body = "team's customized beta body"
        beta_row.save(update_fields=["body"])

        # beta removed from disk; prune runs.
        with self._patch_canonicals((alpha,)):
            result = sync_canonical_skills(self.team, prune=True)

        assert "signals-scout-beta" not in result.pruned_skill_names
        assert "signals-scout-beta" in result.diverged_skill_names
        beta_row.refresh_from_db()
        assert beta_row.deleted is False
        assert beta_row.is_latest is True

    def test_prune_leaves_team_authored_scout_skills_alone(self) -> None:
        # A team hand-authors its own `signals-scout-*` skill — no `seeded_by` tag, and not in
        # the canonical fleet. Prune must NOT tombstone it: we only reap rows we seeded, never a
        # user-defined scout that happens to share the reserved prefix.
        alpha = _make_canonical("signals-scout-alpha", body="alpha body")
        with self._patch_canonicals((alpha,)):
            sync_canonical_skills(self.team)
        team_authored = LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-custom",
            description="team's own scout",
            body="custom body",
            is_latest=True,
        )

        with self._patch_canonicals((alpha,)):
            result = sync_canonical_skills(self.team, prune=True)

        assert "signals-scout-custom" not in result.pruned_skill_names
        team_authored.refresh_from_db()
        assert team_authored.deleted is False
        assert team_authored.is_latest is True

    def test_does_not_prune_when_disk_read_is_empty(self) -> None:
        # Defensive: a broken / empty canonical dir must NOT tombstone the whole fleet, even
        # with prune on. The `not canonicals` early-return guards this — an empty discover
        # result is treated as "couldn't read", not "delete everything".
        alpha = _make_canonical("signals-scout-alpha", body="alpha body")
        with self._patch_canonicals((alpha,)):
            sync_canonical_skills(self.team)

        with self._patch_canonicals(()):
            result = sync_canonical_skills(self.team, prune=True)

        assert result.pruned_skill_names == ()
        assert result.skipped_reason is not None
        assert LLMSkill.objects.filter(
            team=self.team, name="signals-scout-alpha", is_latest=True, deleted=False
        ).exists()

    def test_does_not_prune_by_default(self) -> None:
        # The runner's cold-start sync calls without `prune`, so an ad-hoc run must NOT reap
        # the rest of the team's fleet — it only ensures its own skill exists / is current.
        alpha = _make_canonical("signals-scout-alpha", body="alpha body")
        beta = _make_canonical("signals-scout-beta", body="beta body")
        with self._patch_canonicals((alpha, beta)):
            sync_canonical_skills(self.team)

        # beta removed from disk, but prune defaults off → beta's live row survives.
        with self._patch_canonicals((alpha,)):
            result = sync_canonical_skills(self.team)

        assert result.pruned_skill_names == ()
        assert LLMSkill.objects.filter(
            team=self.team, name="signals-scout-beta", is_latest=True, deleted=False
        ).exists()

    def test_leaves_pre_hash_harness_row_alone(self) -> None:
        # A harness-seeded row missing `canonical_hash` (only reachable for rows seeded before
        # hash tracking, e.g. an existing dogfood team). We can't tell whether the team edited
        # it, so leave it alone rather than risk clobbering — diverged, never updated.
        row = LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-alpha",
            description="legacy",
            body="legacy body",
            metadata={"seeded_by": "signals_scout_harness", "source": "products/signals/skills"},
            is_latest=True,
        )
        v2 = _make_canonical("signals-scout-alpha", description="legacy", body="new canonical body")
        with self._patch_canonicals((v2,)):
            result = sync_canonical_skills(self.team)

        assert result.diverged_skill_names == ("signals-scout-alpha",)
        assert result.updated_skill_names == ()
        row.refresh_from_db()
        assert row.body == "legacy body"

    def test_bundle_only_change_triggers_update(self) -> None:
        # Editing only references/* should still propagate. Easy to miss if the hash
        # only covered SKILL.md body.
        v1 = _make_canonical(
            "signals-scout-alpha",
            body="same body",
            files=(CanonicalSkillFile(path="references/calib.md", content="v1"),),
        )
        with self._patch_canonicals((v1,)):
            sync_canonical_skills(self.team)

        v2 = _make_canonical(
            "signals-scout-alpha",
            body="same body",
            files=(CanonicalSkillFile(path="references/calib.md", content="v2"),),
        )
        with self._patch_canonicals((v2,)):
            result = sync_canonical_skills(self.team)

        assert result.updated_skill_names == ("signals-scout-alpha",)
        latest = LLMSkill.objects.get(team=self.team, name="signals-scout-alpha", is_latest=True)
        bundle = {f.path: f.content for f in latest.files.all()}
        assert bundle["references/calib.md"] == "v2"

    def test_returns_skipped_reason_when_no_canonicals_on_disk(self) -> None:
        with self._patch_canonicals(()):
            result = sync_canonical_skills(self.team)
        assert result.skipped_reason == "no canonical signals-scout-* skills on disk"
        assert result.created_skill_names == ()

    def test_unrelated_team_skill_is_not_touched(self) -> None:
        # A row whose name doesn't match any canonical (and isn't even prefix-matched)
        # is invisible to the sync — the whole loop is keyed on canonical.name.
        LLMSkill.objects.create(
            team=self.team,
            name="custom-team-skill",
            description="custom",
            body="custom body",
        )
        canonical = _make_canonical("signals-scout-alpha", body="canonical body")
        with self._patch_canonicals((canonical,)):
            sync_canonical_skills(self.team)
        custom = LLMSkill.objects.get(team=self.team, name="custom-team-skill")
        assert custom.body == "custom body"

    def test_returns_sync_result_dataclass(self) -> None:
        # Light shape lock so external callers (management command, coordinator) keep
        # access to all five outcome buckets.
        canonical = _make_canonical("signals-scout-alpha", body="x")
        with self._patch_canonicals((canonical,)):
            result = sync_canonical_skills(self.team)
        assert isinstance(result, SyncResult)
        assert hasattr(result, "created_skill_names")
        assert hasattr(result, "updated_skill_names")
        assert hasattr(result, "diverged_skill_names")
        assert hasattr(result, "tombstoned_skill_names")

    def test_withheld_skill_is_not_seeded(self) -> None:
        # A scout on the per-team holdback denylist never materializes a row for that team.
        allowed = _make_canonical("signals-scout-alpha", body="x")
        withheld = _make_canonical("signals-scout-error-tracking", body="y")
        with self._patch_canonicals((allowed, withheld)):
            result = sync_canonical_skills(self.team, withheld_skill_names={"signals-scout-error-tracking"})

        assert result.created_skill_names == ("signals-scout-alpha",)
        assert LLMSkill.objects.filter(team=self.team, name="signals-scout-alpha", deleted=False).exists()
        assert not LLMSkill.objects.filter(team=self.team, name="signals-scout-error-tracking").exists()

    def test_withheld_skill_does_not_update_existing_row(self) -> None:
        # Seed a row, then withhold the skill and change canonical content: the existing row is
        # left untouched (no update, no version bump) rather than tombstoned.
        v1 = _make_canonical("signals-scout-error-tracking", body="v1")
        with self._patch_canonicals((v1,)):
            sync_canonical_skills(self.team)
        v2 = _make_canonical("signals-scout-error-tracking", body="v2")
        with self._patch_canonicals((v2,)):
            result = sync_canonical_skills(self.team, withheld_skill_names={"signals-scout-error-tracking"})

        assert result.updated_skill_names == ()
        row = LLMSkill.objects.get(team=self.team, name="signals-scout-error-tracking", is_latest=True, deleted=False)
        assert row.body == "v1"

    def test_withheld_skill_not_pruned_as_orphan(self) -> None:
        # A withheld skill is still on disk, so the prune pass must not reap it as an orphan.
        v1 = _make_canonical("signals-scout-error-tracking", body="v1")
        with self._patch_canonicals((v1,)):
            sync_canonical_skills(self.team)
        with self._patch_canonicals((v1,)):
            result = sync_canonical_skills(self.team, prune=True, withheld_skill_names={"signals-scout-error-tracking"})

        assert result.pruned_skill_names == ()
        row = LLMSkill.objects.get(team=self.team, name="signals-scout-error-tracking", is_latest=True)
        assert row.deleted is False

    def test_register_missing_configs_excludes_withheld(self) -> None:
        # Even if a withheld scout's skill row exists (e.g. a team previously allowed), no config
        # is seeded for it and it's dropped from the returned live-skill set the coordinator
        # dispatches from — so it can never run.
        allowed = _make_canonical("signals-scout-alpha")
        withheld = _make_canonical("signals-scout-error-tracking")
        with self._patch_canonicals((allowed, withheld)):
            sync_canonical_skills(self.team)  # no withholding at seed: both rows exist

        live = register_missing_configs(self.team.id, withheld_skill_names={"signals-scout-error-tracking"})

        assert live == {"signals-scout-alpha"}
        assert SignalScoutConfig.all_teams.filter(team=self.team, skill_name="signals-scout-alpha").exists()
        assert not SignalScoutConfig.all_teams.filter(
            team=self.team, skill_name="signals-scout-error-tracking"
        ).exists()


class TestSeedCanonicalSkillsAlias(BaseTest):
    """`seed_canonical_skills` is kept as a thin alias for `sync_canonical_skills` so older
    callsites and external consumers don't break. These tests pin that contract."""

    def test_alias_returns_sync_result(self) -> None:
        result = seed_canonical_skills(self.team)
        assert isinstance(result, SyncResult)

    def test_alias_seeds_real_in_repo_canonicals(self) -> None:
        # No mocking — exercises the real `products/signals/skills/` manifest end-to-end
        # so the in-repo fleet stays loadable and seedable. Equivalent to the legacy
        # "first seed creates rows" invariant.
        result = seed_canonical_skills(self.team)
        assert "signals-scout-general" in result.created_skill_names
        seeded = LLMSkill.objects.get(team=self.team, name="signals-scout-general", is_latest=True)
        assert seeded.body
        assert seeded.metadata["seeded_by"] == "signals_scout_harness"
        assert seeded.metadata.get("canonical_hash")

    def test_seeded_skill_is_loadable_via_load_skill_for_run(self) -> None:
        seed_canonical_skills(self.team)
        loaded = load_skill_for_run(self.team, "signals-scout-general")
        assert loaded.name == "signals-scout-general"
        assert loaded.version == 1
        assert "Signals scout" in loaded.body
