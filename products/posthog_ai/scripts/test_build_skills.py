"""Tests for the skill build system."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from products.posthog_ai.scripts.build_skills import (
    _json_schema_type_label,
    _make_jinja_env,
    build_skill,
    discover_product_skills,
    render_skill,
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
# discover_product_skills
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

    # Product E: skills dir with a file (not directory) — skip
    (products / "epsilon" / "skills").mkdir(parents=True)
    (products / "epsilon" / "skills" / "not-a-dir.md").write_text("skip me")

    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", products)

    skills = discover_product_skills()

    names = [(name, src.name) for name, src, _ in skills]
    assert names == [
        ("skill-one", "SKILL.md.j2"),
        ("skill-two", "SKILL.md"),
        ("skill-three", "SKILL.md.j2"),
    ]


def test_discover_no_products_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "nonexistent")
    assert discover_product_skills() == []


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
# build_skill — header generation
# ---------------------------------------------------------------------------


def test_build_skill_adds_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)

    md_file = tmp_path / "products" / "foo" / "skills" / "bar" / "SKILL.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("Skill body.\n")

    env = _make_jinja_env()
    result = build_skill("bar", md_file, env)

    assert result.startswith("<!-- AUTO-GENERATED from products/foo/skills/bar/SKILL.md")
    assert "do not edit by hand" in result
    assert result.endswith("Skill body.\n")


# ---------------------------------------------------------------------------
# pydantic helpers (with a test model, no Django needed)
# ---------------------------------------------------------------------------


def test_pydantic_schema_renders_json() -> None:
    from pydantic import BaseModel, Field

    class SampleModel(BaseModel):
        name: str = Field(description="The name")
        count: int = Field(default=0, description="A counter")

    # Register as importable
    import types

    fake_module = types.ModuleType("_test_skill_models")
    fake_module.SampleModel = SampleModel  # type: ignore
    import sys

    sys.modules["_test_skill_models"] = fake_module

    try:
        from products.posthog_ai.scripts.build_skills import pydantic_schema

        result = pydantic_schema("_test_skill_models.SampleModel")
        import json

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
# End-to-end: template with pydantic_fields
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
            ---
            # E2E test

            {{ pydantic_fields("_test_e2e_models.E2EModel") }}
            """)
        )

        from products.posthog_ai.scripts.build_skills import build_all, check_all

        # Build
        results = build_all()
        assert len(results) == 1
        skill_name, output_path, content = results[0]
        assert skill_name == "e2e-skill"
        assert output_path.exists()
        assert "| `title` |" in content
        assert "AUTO-GENERATED" in content

        # Check should pass after build
        assert check_all() is True
    finally:
        del sys.modules["_test_e2e_models"]


def test_check_detects_stale_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.OUTPUT_DIR", tmp_path / "output")

    # Create source
    skill_src = tmp_path / "products" / "alpha" / "skills" / "stale-skill"
    skill_src.mkdir(parents=True)
    (skill_src / "SKILL.md").write_text("Version 2\n")

    # Create stale output
    output_dir = tmp_path / "output" / "stale-skill"
    output_dir.mkdir(parents=True)
    (output_dir / "SKILL.md").write_text("Version 1\n")

    from products.posthog_ai.scripts.build_skills import check_all

    assert check_all() is False


def test_check_detects_missing_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.REPO_ROOT", tmp_path)
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.PRODUCTS_DIR", tmp_path / "products")
    monkeypatch.setattr("products.posthog_ai.scripts.build_skills.OUTPUT_DIR", tmp_path / "output")

    # Create source but no output
    skill_src = tmp_path / "products" / "alpha" / "skills" / "missing-skill"
    skill_src.mkdir(parents=True)
    (skill_src / "SKILL.md").write_text("Content\n")

    from products.posthog_ai.scripts.build_skills import check_all

    assert check_all() is False
