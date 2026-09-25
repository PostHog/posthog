from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.config_registry import register_missing_configs
from products.signals.backend.scout_harness.deprecation import ScoutDeprecation
from products.signals.backend.scout_harness.lazy_seed import (
    _MAX_SKILL_FILE_COUNT,
    CanonicalSkill,
    CanonicalSkillFile,
    CanonicalSkillParseError,
    ScoutRole,
    SyncResult,
    _compute_canonical_hash,
    _compute_row_hash,
    canonical_structured_output_schema_for,
    discover_canonical_skills,
    reset_canonical_caches,
    seed_canonical_skills,
    sync_canonical_skills,
)
from products.signals.backend.scout_harness.skill_loader import load_skill_for_run
from products.signals.backend.scout_harness.tools.structured_output import (
    InvalidStructuredOutputError,
    StructuredOutputRecord,
    _validate_records,
)
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile

_SCHEMA_JSON = '{"type": "object", "properties": {"verdict": {"type": "string"}}}'


@pytest.fixture(autouse=True)
def _forget_the_canonical_fleet():
    """Keep each test's idea of the shipped fleet out of the next one's.

    Several tests here read the real fleet on disk and several patch it, and the lookups over it
    are cached for the process, so without this the file passes or fails on test order alone.
    """
    reset_canonical_caches()
    yield
    reset_canonical_caches()


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
    config_tags: tuple[str, ...] = (),
    role: ScoutRole = "specialist",
    deprecation: ScoutDeprecation | None = None,
) -> CanonicalSkill:
    """Build a CanonicalSkill for a unit test without going through disk + frontmatter."""
    return CanonicalSkill(
        name=name,
        description=description,
        body=body,
        allowed_tools=allowed_tools,
        files=files,
        source_path=Path("/tmp/fake"),
        config_tags=config_tags,
        role=role,
        deprecation=deprecation,
    )


def _config(team_id: int, skill_name: str) -> SignalScoutConfig:
    return SignalScoutConfig.all_teams.get(team_id=team_id, skill_name=skill_name)


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

    def test_parses_and_normalizes_scout_tags(self, tmp_path: Path) -> None:
        # `scout-tags` is what lands a canonical scout in a product's own scout list, so a
        # dropped or unnormalized value silently empties that list.
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter="""
                ---
                name: signals-scout-bar
                description: bar skill
                scout-tags:
                  - AI Observability
                  - ai_observability
                  - on-call
                ---
            """,
            body="# Bar\n",
        )
        skills = discover_canonical_skills(tmp_path)
        assert skills[0].config_tags == ("ai-observability", "on-call")

    def test_defaults_to_no_scout_tags(self, tmp_path: Path) -> None:
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
        )
        assert discover_canonical_skills(tmp_path)[0].config_tags == ()

    @pytest.mark.parametrize(
        "scout_tags_yaml,expected_error",
        [
            ("scout-tags: ai-observability", "must be a list of strings"),
            ("scout-tags:", "must be a list of strings"),
            ("scout-tags:\n  - '!!!'", "empty once normalized"),
            (f"scout-tags:\n  - {'a' * 51}", "over the 50 limit"),
            ("scout-tags:\n" + "".join(f"  - tag-{i}\n" for i in range(11)), "over the 10 limit"),
        ],
    )
    def test_rejects_malformed_scout_tags(self, tmp_path: Path, scout_tags_yaml: str, expected_error: str) -> None:
        # A tag that doesn't survive validation must fail the parse: seeding a silently-different
        # tag (or none) is a scout missing from the product surface that claims it.
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter=f"---\nname: signals-scout-bar\ndescription: bar skill\n{scout_tags_yaml}\n---\n",
            body="# Bar\n",
        )
        with pytest.raises(CanonicalSkillParseError, match=expected_error):
            discover_canonical_skills(tmp_path)

    def test_rejects_scout_tags_on_companion_skill(self, tmp_path: Path) -> None:
        # A companion skill never gets a config, so there is nothing for its tags to land on.
        _write_canonical_skill(
            tmp_path,
            dir_name="authoring-scouts",
            frontmatter="""
                ---
                name: authoring-scouts
                description: companion authoring guide
                scout-tags:
                  - ai-observability
                ---
            """,
            body="# Authoring\n",
        )
        with pytest.raises(CanonicalSkillParseError, match="Only a signals-scout-\\* skill may declare 'scout-tags'"):
            discover_canonical_skills(tmp_path)

    @pytest.mark.parametrize(
        "display_name_yaml,expected",
        [
            ("scout-display-name: MCP tool calls", "MCP tool calls"),
            ("scout-display-name: '  APM  '", "APM"),
            ("", ""),
        ],
    )
    def test_parses_scout_display_name(self, tmp_path: Path, display_name_yaml: str, expected: str) -> None:
        # The label is how a canonical scout avoids reading as "Mcp tool calls", so a dropped key
        # silently hands every surface the sentence-cased slug again.
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter=f"---\nname: signals-scout-bar\ndescription: bar skill\n{display_name_yaml}\n---\n",
            body="# Bar\n",
        )
        assert discover_canonical_skills(tmp_path)[0].display_name == expected

    @pytest.mark.parametrize(
        "dir_name,display_name_yaml,expected_error",
        [
            ("signals-scout-bar", "scout-display-name: ''", "must be a non-empty string"),
            ("signals-scout-bar", "scout-display-name:", "must be a non-empty string"),
            ("signals-scout-bar", f"scout-display-name: {'a' * 201}", "character limit"),
            ("authoring-scouts", "scout-display-name: Authoring", "Only a signals-scout-\\* skill may declare"),
        ],
    )
    def test_rejects_malformed_scout_display_name(
        self, tmp_path: Path, dir_name: str, display_name_yaml: str, expected_error: str
    ) -> None:
        name = dir_name if dir_name == "authoring-scouts" else "signals-scout-bar"
        _write_canonical_skill(
            tmp_path,
            dir_name=dir_name,
            frontmatter=f"---\nname: {name}\ndescription: bar skill\n{display_name_yaml}\n---\n",
            body="# Bar\n",
        )
        with pytest.raises(CanonicalSkillParseError, match=expected_error):
            discover_canonical_skills(tmp_path)

    def test_parses_scout_role(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter="""
                ---
                name: signals-scout-bar
                description: bar skill
                scout-role: operational
                ---
            """,
            body="# Bar\n",
        )
        assert discover_canonical_skills(tmp_path)[0].role == "operational"

    def test_defaults_to_the_specialist_role(self, tmp_path: Path) -> None:
        # The default has to be the posture that keeps every control on.
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
        )
        assert discover_canonical_skills(tmp_path)[0].role == "specialist"

    @pytest.mark.parametrize("scout_role_yaml", ["scout-role: infrastructure", "scout-role:", "scout-role:\n  - ops"])
    def test_rejects_unknown_scout_role(self, tmp_path: Path, scout_role_yaml: str) -> None:
        # Falling back to `specialist` would silence the scout the role exists to protect.
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter=f"---\nname: signals-scout-bar\ndescription: bar skill\n{scout_role_yaml}\n---\n",
            body="# Bar\n",
        )
        with pytest.raises(CanonicalSkillParseError, match="'scout-role' must be one of"):
            discover_canonical_skills(tmp_path)

    def test_rejects_scout_role_on_companion_skill(self, tmp_path: Path) -> None:
        # A companion skill never gets a config, so there is no posture for a role to shape.
        _write_canonical_skill(
            tmp_path,
            dir_name="authoring-scouts",
            frontmatter="""
                ---
                name: authoring-scouts
                description: companion authoring guide
                scout-role: operational
                ---
            """,
            body="# Authoring\n",
        )
        with pytest.raises(CanonicalSkillParseError, match="Only a signals-scout-\\* skill may declare 'scout-role'"):
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
            # Companion owned by another product, resolved by file path. Moving or renaming
            # that directory drops it from every team's store, and a scout told to read it
            # would report it missing instead of failing.
            "exploring-replay-vision-observations",
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
        # File count limit mirrors MAX_SKILL_FILE_COUNT.
        bundled = {f"references/file_{i:03d}.md": f"# file {i}\n" for i in range(_MAX_SKILL_FILE_COUNT + 1)}
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
        with pytest.raises(CanonicalSkillParseError, match=f"exceeding the {_MAX_SKILL_FILE_COUNT} limit"):
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


class TestStructuredOutputSchemaFrontmatter:
    """`scout-structured-output-schema`: the record contract a measurement scout ships."""

    def test_parses_the_schema_from_the_named_bundled_file(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter="""
                ---
                name: signals-scout-bar
                description: bar skill
                scout-structured-output-schema: references/out.schema.json
                ---
            """,
            body="# Bar\n",
            bundled_files={"references/out.schema.json": _SCHEMA_JSON},
        )
        skill = discover_canonical_skills(tmp_path)[0]
        assert skill.structured_output_schema == {"type": "object", "properties": {"verdict": {"type": "string"}}}
        # The file also rides in the bundle, which is what folds the schema into the content
        # hash — without it a schema edit would never reach a team that already has the scout.
        assert "references/out.schema.json" in [f.path for f in skill.files]

    def test_defaults_to_no_schema(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter="---\nname: signals-scout-bar\ndescription: bar skill\n---\n",
            body="# Bar\n",
        )
        assert discover_canonical_skills(tmp_path)[0].structured_output_schema is None

    @pytest.mark.parametrize(
        "schema_yaml,schema_content,expected_error",
        [
            ("scout-structured-output-schema:", None, "must be a non-empty string"),
            ("scout-structured-output-schema: 17", None, "must be a non-empty string"),
            ("scout-structured-output-schema: out.schema.json", None, "must name a bundled file"),
            ("scout-structured-output-schema: ../out.schema.json", None, "must name a bundled file"),
            ("scout-structured-output-schema: references/../SKILL.md", None, "must name a bundled file"),
            ("scout-structured-output-schema: references/missing.json", None, "must name a bundled file"),
            ("scout-structured-output-schema: references/out.schema.json", "{not json", "not valid JSON"),
            ("scout-structured-output-schema: references/out.schema.json", '{"type": "array"}', "is invalid"),
            (
                "scout-structured-output-schema: references/out.schema.json",
                '{"type": "object", "properties": {"a": {"pattern": "^(a+)+$"}}}',
                "is invalid",
            ),
        ],
    )
    def test_rejects_a_malformed_declaration(
        self, tmp_path: Path, schema_yaml: str, schema_content: str | None, expected_error: str
    ) -> None:
        # A schema that does not survive validation must fail the harness sync once, rather than
        # seeding a contract that fails every record call of every run on every team. A path that
        # is not a bundled file fails the same way whether it is outside the bundle dirs, an
        # escape, or simply absent: the bundle is the only place the schema is looked for.
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-bar",
            frontmatter=f"---\nname: signals-scout-bar\ndescription: bar skill\n{schema_yaml}\n---\n",
            body="# Bar\n",
            bundled_files={"references/out.schema.json": schema_content} if schema_content else None,
        )
        with pytest.raises(CanonicalSkillParseError, match=expected_error):
            discover_canonical_skills(tmp_path)

    def test_rejects_the_key_on_a_companion_skill(self, tmp_path: Path) -> None:
        # A companion skill never gets a config, so there is nothing for the schema to land on.
        _write_canonical_skill(
            tmp_path,
            dir_name="authoring-scouts",
            frontmatter="""
                ---
                name: authoring-scouts
                description: companion authoring guide
                scout-structured-output-schema: references/out.schema.json
                ---
            """,
            body="# Authoring\n",
            bundled_files={"references/out.schema.json": _SCHEMA_JSON},
        )
        with pytest.raises(
            CanonicalSkillParseError,
            match="Only a signals-scout-\\* skill may declare 'scout-structured-output-schema'",
        ):
            discover_canonical_skills(tmp_path)


class TestShippedStructuredOutputSchemas:
    """The schemas the canonical fleet ships, checked against the contract the record endpoint
    enforces. Discovery already rejects an invalid schema; these pin what the valid one accepts."""

    def test_mcp_tool_calls_schema_accepts_one_record_of_each_kind(self) -> None:
        # Validated through the endpoint's own `_validate_records`, not a fresh validator: the
        # endpoint resolves references through a no-retrieval registry and applies its own size
        # caps, so a schema that only passes a bare validator can still fail every real record
        # call — and validation is all-or-nothing, so one rejected record loses the whole batch.
        schema = canonical_structured_output_schema_for("signals-scout-mcp-tool-calls")
        assert schema is not None

        rollup = {
            "mcp_record_kind": "category_rollup",
            "mcp_metrics_version": "1",
            "mcp_regime": "hono",
            "mcp_window_days": 7,
            "mcp_category": "all",
            "mcp_calls": 4000,
            "mcp_errors": 240,
            "mcp_sessions": 900,
            "mcp_users": 30,
            "mcp_error_rate_pct": 6.0,
            "mcp_struggle_session_pct": None,
            "mcp_p95_duration_ms": 1830.0,
            "mcp_problem_tools": 2,
            "mcp_share_of_project_calls_pct": 100.0,
            "mcp_report_action": "authored",
        }
        share = {
            "mcp_record_kind": "tool_session_share",
            "mcp_metrics_version": "1",
            "mcp_tool": "execute-sql",
            "mcp_source": "self_driving",
            "mcp_category": "SQL",
            "mcp_sessions_with_call": 1200,
            "mcp_sessions_total": 4000,
            "mcp_session_share_pct": 30.0,
            "mcp_calls_per_session": 1.5,
            "mcp_share_pct_prior_window": 12.0,
        }
        _validate_records([StructuredOutputRecord(payload=rollup), StructuredOutputRecord(payload=share)], schema)
        # Closed on both branches: a stray field is a typo nobody would otherwise see, and a
        # payload that satisfies both branches would make the discriminator meaningless.
        for rejected in (
            {**rollup, "mcp_unexpected": 1},
            {**share, "mcp_report_action": "authored"},
            {**rollup, "mcp_report_action": "filed"},
        ):
            with pytest.raises(InvalidStructuredOutputError):
                _validate_records([StructuredOutputRecord(payload=rejected)], schema)


class TestDeprecationFrontmatter:
    """`scout-status` / `scout-deprecation`: the marker a retirement PR adds to a SKILL.md."""

    def test_parses_the_retirement_marker(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-alpha",
            frontmatter="""
            ---
            name: signals-scout-alpha
            description: alpha
            scout-status: deprecated
            scout-deprecation:
              reason: Health checks now report to your inbox directly.
              superseded_by: signals-scout-general
              sunset_at: 2026-10-01
            ---
            """,
        )
        (skill,) = discover_canonical_skills(tmp_path)
        assert skill.deprecation is not None
        assert skill.deprecation.reason == "Health checks now report to your inbox directly."
        assert skill.deprecation.superseded_by == "signals-scout-general"
        # A bare date is read as midnight UTC, so the sunset is a fleet-wide instant.
        assert skill.deprecation.sunset_at == datetime(2026, 10, 1, tzinfo=UTC)

    def test_absent_keys_mean_the_scout_is_active(self, tmp_path: Path) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-alpha",
            frontmatter="""
            ---
            name: signals-scout-alpha
            description: alpha
            ---
            """,
        )
        (skill,) = discover_canonical_skills(tmp_path)
        assert skill.deprecation is None

    @pytest.mark.parametrize(
        "extra_frontmatter",
        [
            # A block with no status is a marker nobody meant to apply yet.
            "scout-deprecation:\n              reason: gone",
            # A status with no block is a retirement with no reason to show anyone.
            "scout-status: deprecated",
            # A reason is the one thing every surface renders, so it cannot be blank.
            "scout-status: deprecated\n            scout-deprecation:\n              reason: '  '",
            "scout-status: retired",
            "scout-status: deprecated\n            scout-deprecation:\n              reason: gone\n              sunset_at: soon",
            "scout-status: deprecated\n            scout-deprecation:\n              reason: gone\n              retired_by: me",
        ],
    )
    def test_rejects_a_marker_the_fleet_could_not_act_on(self, tmp_path: Path, extra_frontmatter: str) -> None:
        _write_canonical_skill(
            tmp_path,
            dir_name="signals-scout-alpha",
            frontmatter=f"""
            ---
            name: signals-scout-alpha
            description: alpha
            {extra_frontmatter}
            ---
            """,
        )
        with pytest.raises(CanonicalSkillParseError):
            discover_canonical_skills(tmp_path)

    def test_rejects_the_marker_on_a_companion_skill(self, tmp_path: Path) -> None:
        # A companion has no config to retire, so the keys would do nothing but mislead.
        _write_canonical_skill(
            tmp_path,
            dir_name="authoring-scouts",
            frontmatter="""
            ---
            name: authoring-scouts
            description: guide
            scout-status: deprecated
            scout-deprecation:
              reason: gone
            ---
            """,
        )
        with pytest.raises(CanonicalSkillParseError):
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

    def test_scout_tags_do_not_change_hash(self) -> None:
        # Tags live on the config, not the skill row, so folding them in would leave every
        # seeded row permanently diverged from its stored hash and freeze content updates.
        a = _make_canonical("signals-scout-foo", body="x")
        b = _make_canonical("signals-scout-foo", body="x", config_tags=("ai-observability",))
        assert _compute_canonical_hash(a) == _compute_canonical_hash(b)

    def test_scout_role_does_not_change_hash(self) -> None:
        # Like tags, the role shapes the config rather than the skill row, so folding it in would
        # leave every seeded row permanently diverged and freeze content updates.
        a = _make_canonical("signals-scout-foo", body="x")
        b = _make_canonical("signals-scout-foo", body="x", role="operational")
        assert _compute_canonical_hash(a) == _compute_canonical_hash(b)

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
        beta_before = LLMSkill.objects.get(team=self.team, name="signals-scout-beta", is_latest=True, deleted=False)

        # beta is deleted from disk — only alpha remains canonical.
        with self._patch_canonicals((alpha,)):
            result = sync_canonical_skills(self.team, prune=True)

        assert result.pruned_skill_names == ("signals-scout-beta",)
        assert result.updated_skill_names == ()
        # beta's live row is soft-deleted; alpha is untouched and still live.
        beta_row = LLMSkill.objects.get(team=self.team, name="signals-scout-beta")
        assert beta_row.deleted is True
        assert beta_row.is_latest is False
        # The queryset tombstone bypasses auto_now — it must bump updated_at itself, or the
        # marketplace plugin version (Max(updated_at) over all rows) never advances and the cached
        # repo keeps serving the pruned scout.
        assert beta_row.updated_at > beta_before.updated_at
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

    def test_marker_reaches_a_row_whose_content_did_not_change(self) -> None:
        # Deprecating a scout edits only frontmatter, so the content hashes still match and the
        # update path never fires. Without the marker reconcile the retirement would reach a
        # project only on the scout's next real content edit — that is, possibly never.
        alpha = _make_canonical("signals-scout-alpha", body="alpha body")
        with self._patch_canonicals((alpha,)):
            sync_canonical_skills(self.team)

        sunset = timezone.now() + timedelta(days=30)
        deprecated = _make_canonical(
            "signals-scout-alpha",
            body="alpha body",
            deprecation=ScoutDeprecation(reason="Nothing to watch here now.", sunset_at=sunset),
        )
        with self._patch_canonicals((deprecated,)):
            result = sync_canonical_skills(self.team, prune=True)

        row = LLMSkill.objects.get(team=self.team, name="signals-scout-alpha", is_latest=True)
        assert row.metadata["deprecation"] == {
            "reason": "Nothing to watch here now.",
            "superseded_by": "",
            "sunset_at": sunset.isoformat(),
        }
        # A marker is not a content edit, so no new version and nobody's copy was rewritten.
        assert row.version == 1
        assert result.updated_skill_names == ()

    def test_announced_scout_keeps_running_until_its_sunset(self) -> None:
        deprecated = _make_canonical(
            "signals-scout-alpha",
            deprecation=ScoutDeprecation(reason="gone soon", sunset_at=timezone.now() + timedelta(days=7)),
        )
        with self._patch_canonicals((deprecated,)):
            sync_canonical_skills(self.team, prune=True)
            register_missing_configs(self.team.id)
            SignalScoutConfig.objects.for_team(self.team.id).create(
                team_id=self.team.id, skill_name="signals-scout-alpha"
            )
            result = sync_canonical_skills(self.team, prune=True)

        assert result.retired_config_skill_names == ()
        config = _config(self.team.id, "signals-scout-alpha")
        assert config.status == SignalScoutConfig.Status.ACTIVE
        assert config.enabled is True

    def test_retires_the_config_once_the_sunset_has_passed(self) -> None:
        alpha = _make_canonical("signals-scout-alpha")
        with self._patch_canonicals((alpha,)):
            sync_canonical_skills(self.team)
            register_missing_configs(self.team.id)

        deprecated = _make_canonical(
            "signals-scout-alpha",
            deprecation=ScoutDeprecation(reason="gone", sunset_at=timezone.now() - timedelta(minutes=1)),
        )
        with self._patch_canonicals((deprecated,)):
            result = sync_canonical_skills(self.team, prune=True)
            # A second pass has nothing left to move, so a daily tick does not re-log forever.
            repeat = sync_canonical_skills(self.team, prune=True)

        assert result.retired_config_skill_names == ("signals-scout-alpha",)
        assert repeat.retired_config_skill_names == ()
        config = _config(self.team.id, "signals-scout-alpha")
        assert config.status == SignalScoutConfig.Status.PAUSED_BY_SYSTEM
        assert config.pause_reason == SignalScoutConfig.PauseReason.RETIRED
        # `enabled` is what dispatch filters on, so the pair has to agree or the scout keeps running.
        assert config.enabled is False

    def test_retires_the_config_of_a_scout_pruned_from_disk(self) -> None:
        # The ghost row: the prune tombstones the skill, dispatch is gated on a live skill, so
        # without this the scout silently stops while its roster row still reads as enabled.
        alpha = _make_canonical("signals-scout-alpha")
        beta = _make_canonical("signals-scout-beta")
        with self._patch_canonicals((alpha, beta)):
            sync_canonical_skills(self.team)
            register_missing_configs(self.team.id)

        with self._patch_canonicals((alpha,)):
            result = sync_canonical_skills(self.team, prune=True)

        assert result.pruned_skill_names == ("signals-scout-beta",)
        assert result.retired_config_skill_names == ("signals-scout-beta",)
        beta_config = _config(self.team.id, "signals-scout-beta")
        assert beta_config.enabled is False
        assert beta_config.pause_reason == SignalScoutConfig.PauseReason.RETIRED
        assert _config(self.team.id, "signals-scout-alpha").enabled is True

    def test_leaves_an_edited_fork_running_through_a_retirement(self) -> None:
        alpha = _make_canonical("signals-scout-alpha", body="alpha body")
        with self._patch_canonicals((alpha,)):
            sync_canonical_skills(self.team)
            register_missing_configs(self.team.id)

        row = LLMSkill.objects.get(team=self.team, name="signals-scout-alpha", is_latest=True)
        row.body = "the project's own version"
        row.save(update_fields=["body"])

        deprecated = _make_canonical(
            "signals-scout-alpha",
            body="alpha body",
            deprecation=ScoutDeprecation(reason="gone", sunset_at=timezone.now() - timedelta(days=1)),
        )
        with self._patch_canonicals((deprecated,)):
            result = sync_canonical_skills(self.team, prune=True)

        assert result.retired_config_skill_names == ()
        row.refresh_from_db()
        assert (row.metadata or {})["deprecation"] is None
        assert _config(self.team.id, "signals-scout-alpha").enabled is True

    def test_does_not_overrule_a_pause_a_person_made(self) -> None:
        alpha = _make_canonical("signals-scout-alpha")
        with self._patch_canonicals((alpha,)):
            sync_canonical_skills(self.team)
            register_missing_configs(self.team.id)

        config = _config(self.team.id, "signals-scout-alpha")
        config.enabled = False
        config.save(update_fields=["enabled"])

        deprecated = _make_canonical(
            "signals-scout-alpha",
            deprecation=ScoutDeprecation(reason="gone", sunset_at=timezone.now() - timedelta(days=1)),
        )
        with self._patch_canonicals((deprecated,)):
            result = sync_canonical_skills(self.team, prune=True)

        assert result.retired_config_skill_names == ()
        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.PAUSED_BY_USER

    def test_retirement_needs_the_deliberate_prune_path(self) -> None:
        # The runner's cold-start sync passes no `prune`, so one ad-hoc run must not reconcile
        # the rest of the project's fleet — the same rule the reap already follows.
        alpha = _make_canonical("signals-scout-alpha")
        with self._patch_canonicals((alpha,)):
            sync_canonical_skills(self.team)
            register_missing_configs(self.team.id)

        deprecated = _make_canonical(
            "signals-scout-alpha",
            deprecation=ScoutDeprecation(reason="gone", sunset_at=timezone.now() - timedelta(days=1)),
        )
        with self._patch_canonicals((deprecated,)):
            result = sync_canonical_skills(self.team)

        assert result.retired_config_skill_names == ()
        assert _config(self.team.id, "signals-scout-alpha").enabled is True

    def test_no_config_is_seeded_for_a_scout_being_retired(self) -> None:
        # Phase one stops intake: a project that never ran the scout does not acquire a row it
        # would only have to retire. A project that already has one keeps it (above).
        deprecated = _make_canonical(
            "signals-scout-alpha",
            deprecation=ScoutDeprecation(reason="gone", sunset_at=timezone.now() + timedelta(days=7)),
        )
        beta = _make_canonical("signals-scout-beta")
        with self._patch_canonicals((deprecated, beta)):
            sync_canonical_skills(self.team, prune=True)
            register_missing_configs(self.team.id)

        assert set(SignalScoutConfig.all_teams.filter(team=self.team).values_list("skill_name", flat=True)) == {
            "signals-scout-beta"
        }

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

    def test_real_fleet_operational_scout_seeds_enabled_and_exempt(self) -> None:
        # No mocking, so a dropped frontmatter key fails here and not by a pause weeks later.
        seed_canonical_skills(self.team)
        register_missing_configs(self.team.id)

        operational = SignalScoutConfig.all_teams.get(team=self.team, skill_name="signals-scout-inbox-validation")
        assert operational.enabled is True
        assert operational.auto_pause_exempt is True
        specialist = SignalScoutConfig.all_teams.get(team=self.team, skill_name="signals-scout-general")
        assert specialist.auto_pause_exempt is False

    def test_real_fleet_scout_tags_land_on_the_seeded_config(self) -> None:
        # The whole path a product surface depends on: `scout-tags` in the in-repo SKILL.md →
        # the tag column the AI observability tab filters its scout list on. No mocking, so
        # dropping the frontmatter key or the seed fails here rather than in the UI.
        seed_canonical_skills(self.team)
        register_missing_configs(self.team.id)

        tagged = SignalScoutConfig.all_teams.get(team=self.team, skill_name="signals-scout-ai-observability")
        assert tagged.tag_list == ["ai-observability"]
        untagged = SignalScoutConfig.all_teams.get(team=self.team, skill_name="signals-scout-general")
        assert untagged.tag_list == []

    def test_real_fleet_display_names_land_on_the_seeded_config(self) -> None:
        # The acronyms are the whole point of the frontmatter key: a slug sentence-cased at render
        # time reads as "Apm" and "Mcp tool calls", which is what this stops.
        seed_canonical_skills(self.team)
        register_missing_configs(self.team.id)

        named = SignalScoutConfig.all_teams.filter(team=self.team).values_list("skill_name", "display_name")
        assert dict(named)["signals-scout-apm"] == "APM"
        assert dict(named)["signals-scout-mcp-tool-calls"] == "MCP tool calls"
        assert all(display_name for _, display_name in named)

    def test_real_fleet_seeds_the_structured_output_schema_and_backfills_it_but_never_a_team_edit(self) -> None:
        # The schema's presence on the config is what switches the record channel on, so a dropped
        # frontmatter key means the scout records nothing and nobody notices. Every config of this
        # scout predates the key, so the backfill is the only way they acquire one — and it runs on
        # every tick, so it must lose to a team's own schema forever.
        seed_canonical_skills(self.team)
        register_missing_configs(self.team.id)
        configs = SignalScoutConfig.all_teams.filter(team=self.team)
        canonical_schema = canonical_structured_output_schema_for("signals-scout-mcp-tool-calls")

        assert configs.get(skill_name="signals-scout-mcp-tool-calls").structured_output_schema == canonical_schema
        assert configs.get(skill_name="signals-scout-general").structured_output_schema is None

        configs.filter(skill_name="signals-scout-mcp-tool-calls").update(structured_output_schema=None)
        register_missing_configs(self.team.id)
        assert configs.get(skill_name="signals-scout-mcp-tool-calls").structured_output_schema == canonical_schema

        team_schema = {"type": "object", "properties": {"ours": {"type": "string"}}}
        configs.filter(skill_name="signals-scout-mcp-tool-calls").update(structured_output_schema=team_schema)
        register_missing_configs(self.team.id)
        assert configs.get(skill_name="signals-scout-mcp-tool-calls").structured_output_schema == team_schema

    def test_reconcile_names_a_row_seeded_before_the_label_existed_but_never_a_rename(self) -> None:
        # Every canonical config predates the frontmatter key, so the backfill is the only way they
        # acquire a label — and it runs on every tick, so it must lose to a person's rename forever.
        seed_canonical_skills(self.team)
        register_missing_configs(self.team.id)
        configs = SignalScoutConfig.all_teams.filter(team=self.team)
        configs.filter(skill_name="signals-scout-apm").update(display_name="")
        configs.filter(skill_name="signals-scout-mcp-tool-calls").update(display_name="Our MCP watch")

        register_missing_configs(self.team.id)

        assert configs.get(skill_name="signals-scout-apm").display_name == "APM"
        assert configs.get(skill_name="signals-scout-mcp-tool-calls").display_name == "Our MCP watch"
