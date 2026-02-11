"""Tests for the skill build system."""

from __future__ import annotations

import sys
import types
import zipfile
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

    assert result.name == "bar"
    assert result.description == "Bar skill"
    assert result.files[0].path == "SKILL.md"
    assert "# Skill body" in result.files[0].content
    assert "name: bar" in result.files[0].content
    assert result.source == "products/foo/skills/bar"


def test_build_skill_defaults_without_frontmatter(tmp_path: Path) -> None:
    md_file = tmp_path / "products" / "foo" / "skills" / "my-skill" / "SKILL.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("# No frontmatter\nJust body.\n")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(name="my-skill", source_file=md_file, product_dir=tmp_path / "products" / "foo", depth=1)
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    result = builder.build_skill(skill, renderer)

    assert result.name == "my-skill"
    assert result.description == "Skill: my-skill"
    assert "# No frontmatter" in result.files[0].content


def test_build_skill_collects_all_files(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "multi-file"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: multi\ndescription: Multi\n---\n# Main\n")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "example.md").write_text("# Example reference\n")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(
        name="multi-file", source_file=skill_dir / "SKILL.md", product_dir=tmp_path / "products" / "alpha", depth=1
    )
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    result = builder.build_skill(skill, renderer)

    paths = [f.path for f in result.files]
    assert paths[0] == "SKILL.md"
    assert "references/example.md" in paths
    assert len(result.files) == 2


def test_build_skill_ignores_non_allowed_subdirs(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "with-extras"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: t\ndescription: T\n---\n# Body\n")
    for subdir in ("test", "tests", "utils", "lib"):
        d = skill_dir / subdir
        d.mkdir()
        (d / "something.py").write_text("x = 1")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(
        name="with-extras", source_file=skill_dir / "SKILL.md", product_dir=tmp_path / "products" / "alpha", depth=1
    )
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    result = builder.build_skill(skill, renderer)

    paths = [f.path for f in result.files]
    assert paths == ["SKILL.md"]


def test_build_skill_ignores_root_files(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "root-files"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: rf\ndescription: RF\n---\n# Body\n")
    (skill_dir / "helper.py").write_text("x = 1")
    (skill_dir / "notes.txt").write_text("some notes")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(
        name="root-files", source_file=skill_dir / "SKILL.md", product_dir=tmp_path / "products" / "alpha", depth=1
    )
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    result = builder.build_skill(skill, renderer)

    paths = [f.path for f in result.files]
    assert paths == ["SKILL.md"]


def test_build_skill_renders_j2_references(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "j2-refs"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md.j2").write_text("---\nname: j2r\ndescription: J2R\n---\n# Main {{ 'content' }}\n")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "example.md.j2").write_text("# Rendered {{ 'value' }}\n")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(
        name="j2-refs", source_file=skill_dir / "SKILL.md.j2", product_dir=tmp_path / "products" / "alpha", depth=1
    )
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    result = builder.build_skill(skill, renderer)

    paths = [f.path for f in result.files]
    assert "SKILL.md" in paths
    assert "references/example.md" in paths
    ref_file = next(f for f in result.files if f.path == "references/example.md")
    assert "Rendered value" in ref_file.content


def test_build_skill_validates_entry_point(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "no-entry"
    skill_dir.mkdir(parents=True)
    (skill_dir / "README.md").write_text("not an entry point")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(
        name="no-entry", source_file=skill_dir / "SKILL.md", product_dir=tmp_path / "products" / "alpha", depth=1
    )
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")

    with pytest.raises(ValueError, match="Missing SKILL.md entry point"):
        builder.build_skill(skill, renderer)


def test_build_skill_entry_point_first(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "ordered"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: ord\ndescription: Ord\n---\n# Main\n")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "aaa.md").write_text("first alphabetically")
    (refs / "zzz.md").write_text("last alphabetically")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(
        name="ordered", source_file=skill_dir / "SKILL.md", product_dir=tmp_path / "products" / "alpha", depth=1
    )
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    result = builder.build_skill(skill, renderer)

    assert result.files[0].path == "SKILL.md"
    assert len(result.files) == 3


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
    assert manifest.resources[0].name == "skill-a"
    assert manifest.resources[1].name == "skill-b"
    assert manifest.resources[0].files[0].path == "SKILL.md"
    assert manifest.resources[0].description == "desc"


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
        assert resource.name == "e2e-skill"
        assert resource.description == "End-to-end test skill"
        assert resource.files[0].path == "SKILL.md"
        assert "| `title` |" in resource.files[0].content

        skills_dist = tmp_path / "output" / "dist" / "skills"
        assert skills_dist.exists()
        skill_file = skills_dist / "e2e-skill" / "SKILL.md"
        assert skill_file.exists()
        assert "| `title` |" in skill_file.read_text()

        zip_path = builder.pack()
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            assert "e2e-skill/SKILL.md" in zf.namelist()
            assert "| `title` |" in zf.read("e2e-skill/SKILL.md").decode()

    finally:
        del sys.modules["_test_e2e_models"]


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


def test_lint_all_passes_with_subdirectories(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "with-refs"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: with-refs\ndescription: Has refs\n---\n# Body\n")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "example.md").write_text("# Example\n")

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


def test_lint_all_catches_bad_jinja2_in_subdirectory(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "broken-ref-j2"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md.j2").write_text("---\nname: brj\ndescription: B\n---\n# {{ 'ok' }}\n")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "bad.md.j2").write_text("{% if unclosed %}\n")

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


def test_build_skill_rejects_binary_file(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "has-binary"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: hb\ndescription: HB\n---\n# Body\n")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(
        name="has-binary", source_file=skill_dir / "SKILL.md", product_dir=tmp_path / "products" / "alpha", depth=1
    )
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")

    with pytest.raises(ValueError, match="Binary file not supported"):
        builder.build_skill(skill, renderer)


def test_lint_catches_binary_file(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "has-binary"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: hb\ndescription: HB\n---\n# Body\n")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

    builder = SkillBuilder(
        repo_root=tmp_path,
        products_dir=tmp_path / "products",
        output_dir=tmp_path / "output",
    )
    assert builder.lint_all() is False


def test_build_skill_collects_scripts(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "with-scripts"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: ws\ndescription: WS\n---\n# Body\n")
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "setup.sh").write_text("#!/bin/bash\necho hello\n")
    (scripts / "run.py").write_text("print('hi')\n")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(
        name="with-scripts", source_file=skill_dir / "SKILL.md", product_dir=tmp_path / "products" / "alpha", depth=1
    )
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    result = builder.build_skill(skill, renderer)

    paths = [f.path for f in result.files]
    assert paths[0] == "SKILL.md"
    assert "scripts/setup.sh" in paths
    assert "scripts/run.py" in paths
    assert len(result.files) == 3


def test_build_skill_renders_j2_scripts(tmp_path: Path) -> None:
    skill_dir = tmp_path / "products" / "alpha" / "skills" / "j2-scripts"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: js\ndescription: JS\n---\n# Body\n")
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "template.sh.j2").write_text("echo {{ 'rendered' }}\n")

    renderer = SkillRenderer()
    skill = DiscoveredSkill(
        name="j2-scripts", source_file=skill_dir / "SKILL.md", product_dir=tmp_path / "products" / "alpha", depth=1
    )
    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    result = builder.build_skill(skill, renderer)

    paths = [f.path for f in result.files]
    assert "scripts/template.sh" in paths
    script_file = next(f for f in result.files if f.path == "scripts/template.sh")
    assert "echo rendered" in script_file.content


@pytest.mark.parametrize(
    "template,expected_filename",
    [
        (False, "SKILL.md"),
        (True, "SKILL.md.j2"),
    ],
    ids=["creates-md", "creates-j2"],
)
def test_init_skill_creates_file(tmp_path: Path, template: bool, expected_filename: str) -> None:
    product_dir = tmp_path / "products" / "my_product"
    product_dir.mkdir(parents=True)

    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    skill_file = builder.init_skill("my_product", "my-new-skill", template=template)

    assert skill_file.name == expected_filename
    assert skill_file.exists()

    content = skill_file.read_text()
    fm = validate_frontmatter(content, str(skill_file))
    assert fm.name == "my-new-skill"
    assert fm.description == "TODO"
    assert "# My new skill" in content

    refs_dir = skill_file.parent / "references"
    assert refs_dir.is_dir()


def test_init_skill_rejects_existing(tmp_path: Path) -> None:
    product_dir = tmp_path / "products" / "my_product"
    skill_dir = product_dir / "skills" / "existing-skill"
    skill_dir.mkdir(parents=True)

    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    with pytest.raises(FileExistsError, match="already exists"):
        builder.init_skill("my_product", "existing-skill")


def test_init_skill_rejects_missing_product(tmp_path: Path) -> None:
    (tmp_path / "products").mkdir()

    builder = SkillBuilder(repo_root=tmp_path, products_dir=tmp_path / "products", output_dir=tmp_path / "output")
    with pytest.raises(FileNotFoundError, match="does not exist"):
        builder.init_skill("nonexistent_product", "some-skill")
