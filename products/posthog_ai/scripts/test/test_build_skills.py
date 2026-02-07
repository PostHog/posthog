"""Tests for the skill build system."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from products.posthog_ai.scripts.build_skills import (
    DiscoveredSkill,
    _json_schema_type_label,
    _make_jinja_env,
    build_manifest,
    build_skill,
    discover_product_skills,
    lint_all,
    parse_frontmatter,
    render_skill,
    validate_skill_depths,
)

# ---------------------------------------------------------------------------
# _json_schema_type_label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prop,expected",
    [
        ({"type": "string"}, "string"),
        ({"type": "integer"}, "integer"),
        ({"type": "boolean"}, "boolean"),
        ({"type": "array", "items": {"type": "string"}}, "array[string]"),
        ({"type": "array", "items": {"$ref": "#/$defs/Variant"}}, "array[#/$defs/Variant]"),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "string | null"),
        ({"allOf": [{"$ref": "#/$defs/Foo"}]}, "#/$defs/Foo"),
        ({}, "any"),
    ],
    ids=[
        "string",
        "integer",
        "boolean",
        "array-of-strings",
        "array-of-refs",
        "anyOf-nullable",
        "allOf-ref",
        "empty-prop",
    ],
)
def test_json_schema_type_label(prop: dict, expected: str) -> None:
    assert _json_schema_type_label(prop) == expected


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_meta,expected_body_starts_with",
    [
        (
            "---\nname: my-skill\ndescription: A skill\n---\n# Body\n",
            {"name": "my-skill", "description": "A skill"},
            "# Body",
        ),
        (
            "No frontmatter here\n# Just body\n",
            {},
            "No frontmatter here",
        ),
        (
            "---\nname: 'quoted-name'\ndescription: \"double-quoted\"\n---\nBody\n",
            {"name": "quoted-name", "description": "double-quoted"},
            "Body",
        ),
    ],
    ids=["with-frontmatter", "no-frontmatter", "quoted-values"],
)
def test_parse_frontmatter(text: str, expected_meta: dict, expected_body_starts_with: str) -> None:
    meta, body = parse_frontmatter(text)
    assert meta == expected_meta
    assert body.startswith(expected_body_starts_with)


# ---------------------------------------------------------------------------
# discover_product_skills — depth 1 (directories)
# ---------------------------------------------------------------------------


def test_discover_finds_j2_and_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    products = tmp_path / "products"

    # Product A: has a .j2 template
    skill_a = products / "alpha" / "skills" / "skill-one"
    skill_a.mkdir(parents=True)
    (skill_a / "SKILL.md.j2").write_text("template content")

    # Product B: has plain .md
    skill_b = products / "beta" / "skills" / "skill-two"
    skill_b.mkdir(parents=True)
    (skill_b / "SKILL.md").write_text("static content")

    # Product C: has both — .j2 takes priority
    skill_c = products / "gamma" / "skills" / "skill-three"
    skill_c.mkdir(parents=True)
    (skill_c / "SKILL.md.j2").write_text("j2 wins")
    (skill_c / "SKILL.md").write_text("md loses")

    # Product D: empty skills dir — no results
    (products / "delta" / "skills").mkdir(parents=True)

    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", products)

    skills = discover_product_skills()

    names = [(s.name, s.source_file.name, s.depth) for s in skills]
    assert names == [
        ("skill-one", "SKILL.md.j2", 1),
        ("skill-two", "SKILL.md", 1),
        ("skill-three", "SKILL.md.j2", 1),
    ]


def test_discover_no_products_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "nonexistent")
    assert discover_product_skills() == []


# ---------------------------------------------------------------------------
# discover_product_skills — depth 0 (loose files)
# ---------------------------------------------------------------------------


def test_discover_depth_0_loose_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    products = tmp_path / "products"
    skills_dir = products / "alpha" / "skills"
    skills_dir.mkdir(parents=True)

    (skills_dir / "loose-skill.md").write_text("---\nname: loose\ndescription: Loose\n---\nBody\n")
    (skills_dir / "template-skill.md.j2").write_text("---\nname: tmpl\ndescription: T\n---\nBody\n")

    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", products)

    skills = discover_product_skills()

    names = [(s.name, s.source_file.name, s.depth) for s in skills]
    assert names == [
        ("loose-skill", "loose-skill.md", 0),
        ("template-skill", "template-skill.md.j2", 0),
    ]


def test_discover_depth_0_j2_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    products = tmp_path / "products"
    skills_dir = products / "alpha" / "skills"
    skills_dir.mkdir(parents=True)

    (skills_dir / "my-skill.md").write_text("md content")
    (skills_dir / "my-skill.md.j2").write_text("j2 content")

    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", products)

    skills = discover_product_skills()

    assert len(skills) == 1
    assert skills[0].source_file.name == "my-skill.md.j2"
    assert skills[0].depth == 0


def test_discover_mixed_depths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    products = tmp_path / "products"
    skills_dir = products / "alpha" / "skills"
    skills_dir.mkdir(parents=True)

    # Depth 0: loose file
    (skills_dir / "loose.md").write_text("---\nname: loose\ndescription: L\n---\nBody\n")

    # Depth 1: directory
    dir_skill = skills_dir / "dir-skill"
    dir_skill.mkdir()
    (dir_skill / "SKILL.md").write_text("---\nname: dir\ndescription: D\n---\nBody\n")

    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", products)

    skills = discover_product_skills()

    names = [(s.name, s.depth) for s in skills]
    # Directories come before files in sorted order since 'd' < 'l'
    assert names == [("dir-skill", 1), ("loose", 0)]


# ---------------------------------------------------------------------------
# validate_skill_depths — depth 2+ detection
# ---------------------------------------------------------------------------


def test_validate_depth_2_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")

    skill_dir = tmp_path / "products" / "alpha" / "skills" / "nested-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("content")
    nested = skill_dir / "sub"
    nested.mkdir()

    skill = DiscoveredSkill(
        name="nested-skill",
        source_file=skill_dir / "SKILL.md",
        product_dir=tmp_path / "products" / "alpha",
        depth=1,
    )
    errors = validate_skill_depths([skill])
    assert len(errors) == 1
    assert "Nested subdirectory not allowed" in errors[0]
    assert "sub" in errors[0]


def test_validate_depth_0_skips_validation(tmp_path: Path) -> None:
    skills_dir = tmp_path / "products" / "alpha" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "loose.md").write_text("content")

    skill = DiscoveredSkill(
        name="loose",
        source_file=skills_dir / "loose.md",
        product_dir=tmp_path / "products" / "alpha",
        depth=0,
    )
    errors = validate_skill_depths([skill])
    assert errors == []


# ---------------------------------------------------------------------------
# render_skill — static
# ---------------------------------------------------------------------------


def test_render_static_skill(tmp_path: Path) -> None:
    md_file = tmp_path / "SKILL.md"
    md_file.write_text("# Hello\nThis is a skill.\n")
    env = _make_jinja_env()
    result = render_skill(md_file, env)
    assert result == "# Hello\nThis is a skill.\n"


# ---------------------------------------------------------------------------
# render_skill — Jinja2 templates
# ---------------------------------------------------------------------------


def test_render_j2_basic(tmp_path: Path) -> None:
    j2_file = tmp_path / "SKILL.md.j2"
    j2_file.write_text("Hello {{ name }}!\n")
    env = _make_jinja_env()
    env.globals["name"] = "World"
    result = render_skill(j2_file, env)
    assert result == "Hello World!\n"


def test_render_j2_with_conditionals(tmp_path: Path) -> None:
    j2_file = tmp_path / "SKILL.md.j2"
    j2_file.write_text("{% if show %}visible{% else %}hidden{% endif %}\n")
    env = _make_jinja_env()
    env.globals["show"] = True
    result = render_skill(j2_file, env)
    # trim_blocks strips newline after block tags
    assert result == "visible"


def test_render_j2_strict_undefined_raises(tmp_path: Path) -> None:
    j2_file = tmp_path / "SKILL.md.j2"
    j2_file.write_text("{{ missing_var }}")
    env = _make_jinja_env()
    with pytest.raises(Exception):
        render_skill(j2_file, env)


# ---------------------------------------------------------------------------
# build_skill — produces ContextMillResource dict
# ---------------------------------------------------------------------------


def test_build_skill_extracts_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)

    md_file = tmp_path / "products" / "foo" / "skills" / "bar" / "SKILL.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("---\nname: bar\ndescription: Bar skill\n---\n# Skill body\n")

    env = _make_jinja_env()
    skill = DiscoveredSkill(name="bar", source_file=md_file, product_dir=tmp_path / "products" / "foo", depth=1)
    result = build_skill(skill, env)

    assert result["id"] == "bar"
    assert result["name"] == "bar"
    assert result["uri"] == "skill://posthog/bar"
    assert result["resource"]["mimeType"] == "text/markdown"
    assert result["resource"]["description"] == "Bar skill"
    assert result["resource"]["text"] == "# Skill body"
    assert result["source"] == "products/foo/skills/bar/SKILL.md"


def test_build_skill_defaults_without_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)

    md_file = tmp_path / "products" / "foo" / "skills" / "my-skill" / "SKILL.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("# No frontmatter\nJust body.\n")

    env = _make_jinja_env()
    skill = DiscoveredSkill(name="my-skill", source_file=md_file, product_dir=tmp_path / "products" / "foo", depth=1)
    result = build_skill(skill, env)

    assert result["name"] == "my-skill"
    assert result["resource"]["description"] == "Skill: my-skill"
    assert "# No frontmatter" in result["resource"]["text"]


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------


def test_build_manifest_produces_valid_structure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")

    for skill_name in ("skill-a", "skill-b"):
        skill_dir = tmp_path / "products" / "alpha" / "skills" / skill_name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"---\nname: {skill_name}\ndescription: desc\n---\n# Body\n")

    skills = discover_product_skills()
    env = _make_jinja_env()
    manifest = build_manifest(skills, env)

    assert manifest["version"] == "1.0.0"
    assert len(manifest["resources"]) == 2
    assert manifest["resources"][0]["id"] == "skill-a"
    assert manifest["resources"][1]["id"] == "skill-b"
    assert manifest["resources"][0]["uri"] == "skill://posthog/skill-a"


# ---------------------------------------------------------------------------
# pydantic helpers (with a test model, no Django needed)
# ---------------------------------------------------------------------------


def test_pydantic_schema_renders_json() -> None:
    from pydantic import BaseModel, Field

    class SampleModel(BaseModel):
        name: str = Field(description="The name")
        count: int = Field(default=0, description="A counter")

    import sys
    import types

    fake_module = types.ModuleType("_test_skill_models")
    fake_module.SampleModel = SampleModel  # type: ignore
    sys.modules["_test_skill_models"] = fake_module

    try:
        from products.posthog_ai.scripts.build_skills import pydantic_schema

        result = pydantic_schema("_test_skill_models.SampleModel")
        schema = json.loads(result)
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"
        assert "name" in schema.get("required", [])
    finally:
        del sys.modules["_test_skill_models"]


def test_pydantic_fields_renders_table() -> None:
    from pydantic import BaseModel, Field

    class TinyModel(BaseModel):
        x: str = Field(description="The x field")
        y: int = Field(default=0, description="The y field")

    import sys
    import types

    fake_module = types.ModuleType("_test_skill_models2")
    fake_module.TinyModel = TinyModel  # type: ignore
    sys.modules["_test_skill_models2"] = fake_module

    try:
        from products.posthog_ai.scripts.build_skills import pydantic_fields

        result = pydantic_fields("_test_skill_models2.TinyModel")
        assert "| `x` |" in result
        assert "| `y` |" in result
        assert "| Field | Type | Required | Description |" in result
    finally:
        del sys.modules["_test_skill_models2"]


def test_pydantic_field_list_renders_bullets() -> None:
    from pydantic import BaseModel, Field

    class BulletModel(BaseModel):
        alpha: str = Field(description="First")
        beta: int = Field(description="Second")

    import sys
    import types

    fake_module = types.ModuleType("_test_skill_models3")
    fake_module.BulletModel = BulletModel  # type: ignore
    sys.modules["_test_skill_models3"] = fake_module

    try:
        from products.posthog_ai.scripts.build_skills import pydantic_field_list

        result = pydantic_field_list("_test_skill_models3.BulletModel")
        assert "- **`alpha`** (string): First" in result
        assert "- **`beta`** (integer): Second" in result
    finally:
        del sys.modules["_test_skill_models3"]


# ---------------------------------------------------------------------------
# End-to-end: template with pydantic_fields → manifest
# ---------------------------------------------------------------------------


def test_end_to_end_template_with_pydantic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import BaseModel, Field

    class E2EModel(BaseModel):
        title: str = Field(description="A title")

    import sys
    import types

    fake_module = types.ModuleType("_test_e2e_models")
    fake_module.E2EModel = E2EModel  # type: ignore
    sys.modules["_test_e2e_models"] = fake_module

    try:
        monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
        monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")
        monkeypatch.setattr("products.posthog_ai.scripts.build_skills.OUTPUT_DIR", tmp_path / "output")

        # Create a product skill source
        skill_src = tmp_path / "products" / "testprod" / "skills" / "e2e-skill"
        skill_src.mkdir(parents=True)
        (skill_src / "SKILL.md.j2").write_text(
            textwrap.dedent("""\
            ---
            name: e2e-skill
            description: End-to-end test skill
            ---
            # E2E test

            {{ pydantic_fields("_test_e2e_models.E2EModel") }}
            """)
        )

        from products.posthog_ai.scripts.build_skills import build_all, check_all

        # Build
        manifest = build_all()
        assert len(manifest["resources"]) == 1

        resource = manifest["resources"][0]
        assert resource["id"] == "e2e-skill"
        assert resource["name"] == "e2e-skill"
        assert resource["uri"] == "skill://posthog/e2e-skill"
        assert "| `title` |" in resource["resource"]["text"]

        # Verify manifest.json was written
        manifest_path = tmp_path / "output" / "manifest.json"
        assert manifest_path.exists()
        written = json.loads(manifest_path.read_text())
        assert written == manifest

        # Check should pass after build
        assert check_all() is True
    finally:
        del sys.modules["_test_e2e_models"]


def test_check_detects_stale_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.OUTPUT_DIR", tmp_path / "output")

    # Create source
    skill_src = tmp_path / "products" / "alpha" / "skills" / "stale-skill"
    skill_src.mkdir(parents=True)
    (skill_src / "SKILL.md").write_text("---\nname: stale-skill\ndescription: Stale\n---\nVersion 2\n")

    # Create stale manifest
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True)
    stale_manifest = {
        "version": "1.0.0",
        "resources": [
            {
                "id": "stale-skill",
                "name": "stale-skill",
                "uri": "skill://posthog/stale-skill",
                "resource": {
                    "mimeType": "text/markdown",
                    "description": "Stale",
                    "text": "Version 1",
                },
                "source": "products/alpha/skills/stale-skill/SKILL.md",
            }
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(stale_manifest))

    from products.posthog_ai.scripts.build_skills import check_all

    assert check_all() is False


def test_check_detects_missing_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.OUTPUT_DIR", tmp_path / "output")

    # Create source but no manifest
    skill_src = tmp_path / "products" / "alpha" / "skills" / "missing-skill"
    skill_src.mkdir(parents=True)
    (skill_src / "SKILL.md").write_text("---\nname: missing\ndescription: Missing\n---\nContent\n")

    from products.posthog_ai.scripts.build_skills import check_all

    assert check_all() is False


# ---------------------------------------------------------------------------
# lint_all
# ---------------------------------------------------------------------------


def test_lint_all_passes_for_valid_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")

    skill_dir = tmp_path / "products" / "alpha" / "skills" / "good-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: good-skill\ndescription: A good skill\n---\n# Body\n")

    j2_dir = tmp_path / "products" / "alpha" / "skills" / "template-skill"
    j2_dir.mkdir(parents=True)
    (j2_dir / "SKILL.md.j2").write_text("---\nname: tmpl\ndescription: T\n---\n# {{ 'hello' }}\n")

    assert lint_all() is True


def test_lint_all_catches_missing_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")

    skill_dir = tmp_path / "products" / "alpha" / "skills" / "bad-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# No frontmatter at all\n")

    assert lint_all() is False


def test_lint_all_catches_bad_jinja2_syntax(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")

    skill_dir = tmp_path / "products" / "alpha" / "skills" / "broken-j2"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md.j2").write_text("{% if unclosed %}\n")

    assert lint_all() is False


def test_lint_all_catches_duplicate_skill_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")

    for product in ("alpha", "beta"):
        skill_dir = tmp_path / "products" / product / "skills" / "same-name"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: same\ndescription: Duplicate\n---\nBody\n")

    assert lint_all() is False


def test_lint_all_catches_depth_2_violations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")

    skill_dir = tmp_path / "products" / "alpha" / "skills" / "nested"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: nested\ndescription: N\n---\nBody\n")
    (skill_dir / "subdir").mkdir()

    assert lint_all() is False
