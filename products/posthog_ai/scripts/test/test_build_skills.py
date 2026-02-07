"""Tests for the skill build system."""

from __future__ import annotations

import sys
import json
import types
import textwrap
from pathlib import Path

import pytest

from products.posthog_ai.scripts.build_skills import (
    DiscoveredSkill,
    SkillBuilder,
    SkillDiscoverer,
    SkillRenderer,
    parse_frontmatter,
    validate_frontmatter,
)


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


def test_validate_frontmatter_valid() -> None:
    text = "---\nname: my-skill\ndescription: A good skill\n---\n# Body\n"
    fm = validate_frontmatter(text, "test.md")
    assert fm.name == "my-skill"
    assert fm.description == "A good skill"


@pytest.mark.parametrize(
    "text,error_fragment",
    [
        ("No frontmatter\n", "Missing YAML frontmatter"),
        ("---\nname: only-name\n---\nBody\n", "description"),
        ("---\ndescription: only-desc\n---\nBody\n", "name"),
    ],
    ids=["no-frontmatter", "missing-description", "missing-name"],
)
def test_validate_frontmatter_invalid(text: str, error_fragment: str) -> None:
    with pytest.raises(ValueError, match=error_fragment):
        validate_frontmatter(text, "test.md")


def test_discover_finds_j2_and_md(tmp_path: Path) -> None:
    products = tmp_path / "products"

    skill_a = products / "alpha" / "skills" / "skill-one"
    skill_a.mkdir(parents=True)
    (skill_a / "SKILL.md.j2").write_text("template content")

    skill_b = products / "beta" / "skills" / "skill-two"
    skill_b.mkdir(parents=True)
    (skill_b / "SKILL.md").write_text("static content")

    skill_c = products / "gamma" / "skills" / "skill-three"
    skill_c.mkdir(parents=True)
    (skill_c / "SKILL.md.j2").write_text("j2 wins")
    (skill_c / "SKILL.md").write_text("md loses")

    (products / "delta" / "skills").mkdir(parents=True)

    discoverer = SkillDiscoverer(products_dir=products)
    skills = discoverer.discover()

    names = [(s.name, s.source_file.name, s.depth) for s in skills]
    assert names == [
        ("skill-one", "SKILL.md.j2", 1),
        ("skill-two", "SKILL.md", 1),
        ("skill-three", "SKILL.md.j2", 1),
    ]


def test_discover_no_products_dir(tmp_path: Path) -> None:
    discoverer = SkillDiscoverer(products_dir=tmp_path / "nonexistent")
    assert discoverer.discover() == []


def test_discover_depth_0_loose_files(tmp_path: Path) -> None:
    products = tmp_path / "products"
    skills_dir = products / "alpha" / "skills"
    skills_dir.mkdir(parents=True)

    (skills_dir / "loose-skill.md").write_text("---\nname: loose\ndescription: Loose\n---\nBody\n")
    (skills_dir / "template-skill.md.j2").write_text("---\nname: tmpl\ndescription: T\n---\nBody\n")

    discoverer = SkillDiscoverer(products_dir=products)
    skills = discoverer.discover()

    names = [(s.name, s.source_file.name, s.depth) for s in skills]
    assert names == [
        ("loose-skill", "loose-skill.md", 0),
        ("template-skill", "template-skill.md.j2", 0),
    ]


def test_discover_depth_0_j2_priority(tmp_path: Path) -> None:
    products = tmp_path / "products"
    skills_dir = products / "alpha" / "skills"
    skills_dir.mkdir(parents=True)

    (skills_dir / "my-skill.md").write_text("md content")
    (skills_dir / "my-skill.md.j2").write_text("j2 content")

    discoverer = SkillDiscoverer(products_dir=products)
    skills = discoverer.discover()

    assert len(skills) == 1
    assert skills[0].source_file.name == "my-skill.md.j2"
    assert skills[0].depth == 0


def test_discover_mixed_depths(tmp_path: Path) -> None:
    products = tmp_path / "products"
    skills_dir = products / "alpha" / "skills"
    skills_dir.mkdir(parents=True)

    (skills_dir / "loose.md").write_text("---\nname: loose\ndescription: L\n---\nBody\n")

    dir_skill = skills_dir / "dir-skill"
    dir_skill.mkdir()
    (dir_skill / "SKILL.md").write_text("---\nname: dir\ndescription: D\n---\nBody\n")

    discoverer = SkillDiscoverer(products_dir=products)
    skills = discoverer.discover()

    names = [(s.name, s.depth) for s in skills]
    assert names == [("dir-skill", 1), ("loose", 0)]


def test_validate_depth_2_raises(tmp_path: Path) -> None:
    products = tmp_path / "products"
    skill_dir = products / "alpha" / "skills" / "nested-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("content")
    (skill_dir / "sub").mkdir()

    skill = DiscoveredSkill(
        name="nested-skill",
        source_file=skill_dir / "SKILL.md",
        product_dir=products / "alpha",
        depth=1,
    )
    discoverer = SkillDiscoverer(products_dir=products)
    errors = discoverer.validate_depths([skill])
    assert len(errors) == 1
    assert "Nested subdirectory not allowed" in errors[0]
    assert "sub" in errors[0]


def test_validate_depth_0_skips_validation(tmp_path: Path) -> None:
    products = tmp_path / "products"
    skills_dir = products / "alpha" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "loose.md").write_text("content")

    skill = DiscoveredSkill(
        name="loose",
        source_file=skills_dir / "loose.md",
        product_dir=products / "alpha",
        depth=0,
    )
    discoverer = SkillDiscoverer(products_dir=products)
    errors = discoverer.validate_depths([skill])
    assert errors == []


def test_render_static_skill(tmp_path: Path) -> None:
    md_file = tmp_path / "SKILL.md"
    md_file.write_text("# Hello\nThis is a skill.\n")
    renderer = SkillRenderer()
    result = renderer.render(md_file)
    assert result == "# Hello\nThis is a skill.\n"


def test_render_j2_basic(tmp_path: Path) -> None:
    j2_file = tmp_path / "SKILL.md.j2"
    j2_file.write_text("Hello {{ name }}!\n")
    renderer = SkillRenderer()
    renderer.env.globals["name"] = "World"
    result = renderer.render(j2_file)
    assert result == "Hello World!\n"


def test_render_j2_with_conditionals(tmp_path: Path) -> None:
    j2_file = tmp_path / "SKILL.md.j2"
    j2_file.write_text("{% if show %}visible{% else %}hidden{% endif %}\n")
    renderer = SkillRenderer()
    renderer.env.globals["show"] = True
    result = renderer.render(j2_file)
    assert result == "visible"


def test_render_j2_strict_undefined_raises(tmp_path: Path) -> None:
    j2_file = tmp_path / "SKILL.md.j2"
    j2_file.write_text("{{ missing_var }}")
    renderer = SkillRenderer()
    with pytest.raises(Exception):
        renderer.render(j2_file)


def test_build_skill_extracts_frontmatter(tmp_path: Path) -> None:
    md_file = tmp_path / "products" / "foo" / "skills" / "bar" / "SKILL.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("---\nname: bar\ndescription: Bar skill\n---\n# Skill body\n")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(name="bar", source_file=md_file, product_dir=tmp_path / "products" / "foo", depth=1)
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    result = builder.build_skill(skill, renderer)

    assert result.id == "bar"
    assert result.name == "bar"
    assert result.uri == "skill://posthog/bar"
    assert result.resource.mimeType == "text/markdown"
    assert result.resource.description == "Bar skill"
    assert result.resource.text == "# Skill body"
    assert result.source == "products/foo/skills/bar/SKILL.md"


def test_build_skill_defaults_without_frontmatter(tmp_path: Path) -> None:
    md_file = tmp_path / "products" / "foo" / "skills" / "my-skill" / "SKILL.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("# No frontmatter\nJust body.\n")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(name="my-skill", source_file=md_file, product_dir=tmp_path / "products" / "foo", depth=1)
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    result = builder.build_skill(skill, renderer)

    assert result.name == "my-skill"
    assert result.resource.description == "Skill: my-skill"
    assert "# No frontmatter" in result.resource.text


def test_build_manifest_produces_valid_structure(tmp_path: Path) -> None:
    products = tmp_path / "products"
    for skill_name in ("skill-a", "skill-b"):
        skill_dir = products / "alpha" / "skills" / skill_name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"---\nname: {skill_name}\ndescription: desc\n---\n# Body\n")

    discoverer = SkillDiscoverer(products_dir=products)
    skills = discoverer.discover()
    renderer = SkillRenderer()
    builder = SkillBuilder(repo_root=tmp_path, products_dir=products, output_dir=tmp_path / "output")
    manifest = builder.build_manifest(skills, renderer)

    assert manifest.version == "1.0.0"
    assert len(manifest.resources) == 2
    assert manifest.resources[0].id == "skill-a"
    assert manifest.resources[1].id == "skill-b"
    assert manifest.resources[0].uri == "skill://posthog/skill-a"


def test_end_to_end_template_with_pydantic(tmp_path: Path) -> None:
    from pydantic import BaseModel, Field

    class E2EModel(BaseModel):
        title: str = Field(description="A title")

    fake_module = types.ModuleType("_test_e2e_models")
    fake_module.E2EModel = E2EModel  # type: ignore
    sys.modules["_test_e2e_models"] = fake_module

    try:
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

        builder = SkillBuilder(
            repo_root=tmp_path,
            products_dir=tmp_path / "products",
            output_dir=tmp_path / "output",
        )

        manifest = builder.build_all()
        assert len(manifest.resources) == 1

        resource = manifest.resources[0]
        assert resource.id == "e2e-skill"
        assert resource.name == "e2e-skill"
        assert resource.uri == "skill://posthog/e2e-skill"
        assert "| `title` |" in resource.resource.text

        manifest_path = tmp_path / "output" / "manifest.json"
        assert manifest_path.exists()
        written = json.loads(manifest_path.read_text())
        assert written == manifest.model_dump()

        assert builder.check_all() is True
    finally:
        del sys.modules["_test_e2e_models"]


def test_check_detects_stale_manifest(tmp_path: Path) -> None:
    skill_src = tmp_path / "products" / "alpha" / "skills" / "stale-skill"
    skill_src.mkdir(parents=True)
    (skill_src / "SKILL.md").write_text("---\nname: stale-skill\ndescription: Stale\n---\nVersion 2\n")

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

    builder = SkillBuilder(
        repo_root=tmp_path,
        products_dir=tmp_path / "products",
        output_dir=output_dir,
    )
    assert builder.check_all() is False


def test_check_detects_missing_manifest(tmp_path: Path) -> None:
    skill_src = tmp_path / "products" / "alpha" / "skills" / "missing-skill"
    skill_src.mkdir(parents=True)
    (skill_src / "SKILL.md").write_text("---\nname: missing\ndescription: Missing\n---\nContent\n")

    builder = SkillBuilder(
        repo_root=tmp_path,
        products_dir=tmp_path / "products",
        output_dir=tmp_path / "output",
    )
    assert builder.check_all() is False


def test_lint_all_passes_for_valid_skills(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "good-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: good-skill\ndescription: A good skill\n---\n# Body\n")

    j2_dir = tmp_path / "products" / "alpha" / "skills" / "template-skill"
    j2_dir.mkdir(parents=True)
    (j2_dir / "SKILL.md.j2").write_text("---\nname: tmpl\ndescription: T\n---\n# {{ 'hello' }}\n")

    builder = SkillBuilder(
        repo_root=tmp_path,
        products_dir=tmp_path / "products",
        output_dir=tmp_path / "output",
    )
    assert builder.lint_all() is True


def test_lint_all_catches_missing_frontmatter(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "bad-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# No frontmatter at all\n")

    builder = SkillBuilder(
        repo_root=tmp_path,
        products_dir=tmp_path / "products",
        output_dir=tmp_path / "output",
    )
    assert builder.lint_all() is False


def test_lint_all_catches_bad_jinja2_syntax(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "broken-j2"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md.j2").write_text("{% if unclosed %}\n")

    builder = SkillBuilder(
        repo_root=tmp_path,
        products_dir=tmp_path / "products",
        output_dir=tmp_path / "output",
    )
    assert builder.lint_all() is False


def test_lint_all_catches_duplicate_skill_names(tmp_path: Path) -> None:
    for product in ("alpha", "beta"):
        skill_dir = tmp_path / "products" / product / "skills" / "same-name"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: same\ndescription: Duplicate\n---\nBody\n")

    builder = SkillBuilder(
        repo_root=tmp_path,
        products_dir=tmp_path / "products",
        output_dir=tmp_path / "output",
    )
    assert builder.lint_all() is False


def test_lint_all_catches_depth_2_violations(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "nested"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: nested\ndescription: N\n---\nBody\n")
    (skill_dir / "subdir").mkdir()

    builder = SkillBuilder(
        repo_root=tmp_path,
        products_dir=tmp_path / "products",
        output_dir=tmp_path / "output",
    )
    assert builder.lint_all() is False
