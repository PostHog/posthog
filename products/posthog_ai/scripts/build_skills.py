#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Build coding agent skills from products/*/skills/ into a context-mill-compatible
manifest for MCP resource distribution.

Skills can be:
- Plain markdown (SKILL.md) — copied as-is
- Jinja2 templates (SKILL.md.j2) — rendered with Python context including Pydantic schema helpers

Each skill must have YAML frontmatter with at least ``name`` and ``description`` fields.
The build produces a manifest.json in the ContextMillManifest format consumed by
the MCP server at services/mcp/.

Requires the project's Python environment (managed by uv) for template rendering
that imports Pydantic models from product code.

Usage:
    hogli build:skills          # Build all product skills
    hogli build:skills --check  # Check if built skills are up-to-date (for CI)
    hogli build:skills --list   # List discovered skills without building
    hogli lint:skills           # Validate skill sources without rendering
"""

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import textwrap
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError
from pydantic import BaseModel, Field, ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

MANIFEST_VERSION = "1.0.0"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TEST_DIR_NAMES = {"test", "tests"}
_TEST_FILE_RE = re.compile(r"^test_.*\.py$|.*_test\.py$")
_BINARY_CHECK_SIZE = 8192


def _create_jinja_env(**extra_globals: object) -> Environment:
    """Create a Jinja2 Environment with the standard skill rendering settings."""
    env = Environment(
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        lstrip_blocks=True,
        trim_blocks=True,
    )
    env.globals.update(extra_globals)
    return env


def _assert_text_file(file_path: Path) -> None:
    """Raise ValueError if file appears to be binary (contains null bytes)."""
    with open(file_path, "rb") as f:
        chunk = f.read(_BINARY_CHECK_SIZE)
    if b"\x00" in chunk:
        raise ValueError(
            f"Binary file not supported in skill directory: {file_path.name}. Only text-based files are allowed."
        )


class SkillFrontmatter(BaseModel):
    name: str
    description: str


class DiscoveredSkill(BaseModel):
    name: str
    source_file: Path
    product_dir: Path
    depth: int


class SkillFile(BaseModel):
    path: str
    content: str


class SkillResource(BaseModel):
    name: str
    description: str
    files: list[SkillFile]
    source: str


class SkillManifest(BaseModel):
    version: str = MANIFEST_VERSION
    resources: list[SkillResource] = Field(default_factory=list)


def validate_frontmatter(text: str, source_label: str = "<unknown>") -> SkillFrontmatter:
    """Parse and validate frontmatter from rendered skill text.

    Raises ``ValueError`` if frontmatter is missing or invalid.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"Missing YAML frontmatter in {source_label}")
    raw_yaml = match.group(1)
    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML frontmatter in {source_label}: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError(f"Frontmatter must be a YAML mapping in {source_label}")
    try:
        return SkillFrontmatter.model_validate(parsed)
    except ValidationError as e:
        raise ValueError(f"Invalid frontmatter in {source_label}: {e}") from e


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract YAML frontmatter and body from a skill file.

    Returns (metadata_dict, body_without_frontmatter).
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw_yaml = match.group(1)
    body = text[match.end() :]
    parsed = yaml.safe_load(raw_yaml)
    if not isinstance(parsed, dict):
        return {}, text

    metadata: dict[str, str] = {str(k): str(v) for k, v in parsed.items()}
    return metadata, body


class SkillDiscoverer:
    """Discovers skill source files from products/*/skills/."""

    def __init__(self, products_dir: Path) -> None:
        self.products_dir = products_dir

    def discover(self) -> list[DiscoveredSkill]:
        """Discover skill sources from products/*/skills/.

        Supports two depth levels relative to products/*/skills/:
        - Depth 0: Loose files directly in skills/ (e.g., my-skill.md or my-skill.md.j2).
          Skill name = filename stem (without .md or .md.j2 extension).
        - Depth 1: Directories containing SKILL.md(.j2) (e.g., my-skill/SKILL.md).
          Skill name = directory name.

        For both depths, .j2 files take priority over plain .md when both exist.
        """
        skills: list[DiscoveredSkill] = []

        if not self.products_dir.exists():
            return skills

        for product_dir in sorted(self.products_dir.iterdir()):
            if not product_dir.is_dir():
                continue
            skills_dir = product_dir / "skills"
            if not skills_dir.exists():
                continue

            for entry in sorted(skills_dir.iterdir()):
                if entry.is_dir():
                    j2_file = entry / "SKILL.md.j2"
                    md_file = entry / "SKILL.md"
                    if j2_file.exists():
                        skills.append(
                            DiscoveredSkill(name=entry.name, source_file=j2_file, product_dir=product_dir, depth=1)
                        )
                    elif md_file.exists():
                        skills.append(
                            DiscoveredSkill(name=entry.name, source_file=md_file, product_dir=product_dir, depth=1)
                        )
                elif entry.is_file() and (entry.name.endswith(".md.j2") or entry.name.endswith(".md")):
                    if entry.name.endswith(".md") and (entry.parent / (entry.name + ".j2")).exists():
                        continue
                    skill_name = entry.name.removesuffix(".j2").removesuffix(".md")
                    skills.append(DiscoveredSkill(name=skill_name, source_file=entry, product_dir=product_dir, depth=0))

        return skills


class SkillRenderer:
    """Renders skill source files to final markdown via Jinja2."""

    def __init__(self) -> None:
        from products.posthog_ai.scripts.pydantic_schema import pydantic_field_list, pydantic_fields, pydantic_schema

        self.env = _create_jinja_env(
            pydantic_schema=pydantic_schema,
            pydantic_fields=pydantic_fields,
            pydantic_field_list=pydantic_field_list,
        )

    def render(self, source_file: Path) -> str:
        """Render a skill source file to its final markdown content."""
        raw = source_file.read_text()
        if source_file.suffix == ".j2":
            template = self.env.from_string(raw)
            return template.render()
        return raw


class SkillBuilder:
    """Orchestrates skill discovery, rendering, and manifest generation."""

    def __init__(self, repo_root: Path, products_dir: Path, output_dir: Path) -> None:
        self.repo_root = repo_root
        self.products_dir = products_dir
        self.output_dir = output_dir
        self.discoverer = SkillDiscoverer(products_dir)

    def collect_skill_files(self, skill_dir: Path, renderer: SkillRenderer) -> list[SkillFile]:
        """Collect and render all files from a skill directory.

        Walks the directory recursively, excluding test directories and test files.
        Validates that .j2 files are at most 1 level deep within the skill dir.
        Returns a list of SkillFile with SKILL.md always first.
        """
        files: list[SkillFile] = []
        entry_point: SkillFile | None = None

        for root, dirs, filenames in os.walk(skill_dir):
            dirs[:] = [d for d in sorted(dirs) if d not in _TEST_DIR_NAMES]
            rel_root = Path(root).relative_to(skill_dir)
            depth = len(rel_root.parts)

            for filename in sorted(filenames):
                if _TEST_FILE_RE.match(filename):
                    continue

                file_path = Path(root) / filename
                rel_path = file_path.relative_to(skill_dir)

                _assert_text_file(file_path)

                if filename.endswith(".j2") and depth > 1:
                    raise ValueError(f"Jinja2 template too deep (max 1 level): {rel_path} in {skill_dir.name}")

                content = renderer.render(file_path)
                out_path = str(rel_path)
                if out_path.endswith(".j2"):
                    out_path = out_path.removesuffix(".j2")

                skill_file = SkillFile(path=out_path, content=content)
                if out_path == "SKILL.md":
                    entry_point = skill_file
                else:
                    files.append(skill_file)

        if entry_point is None:
            raise ValueError(f"Missing SKILL.md entry point in {skill_dir.name}")

        return [entry_point, *files]

    def build_skill(self, skill: DiscoveredSkill, renderer: SkillRenderer) -> SkillResource:
        """Build a single skill and return a SkillResource."""
        if skill.depth == 1:
            skill_dir = skill.source_file.parent
            skill_files = self.collect_skill_files(skill_dir, renderer)
            entry_content = skill_files[0].content
            metadata, _body = parse_frontmatter(entry_content)
            source = str(skill_dir.relative_to(self.repo_root))
        else:
            rendered = renderer.render(skill.source_file)
            metadata, _body = parse_frontmatter(rendered)
            out_name = skill.source_file.name
            if out_name.endswith(".j2"):
                out_name = out_name.removesuffix(".j2")
            skill_files = [SkillFile(path=out_name, content=rendered.strip())]
            source = str(skill.source_file.relative_to(self.repo_root))

        display_name = metadata.get("name", skill.name)
        description = metadata.get("description", f"Skill: {skill.name}")

        return SkillResource(
            name=display_name,
            description=description,
            files=skill_files,
            source=source,
        )

    def build_manifest(self, skills: list[DiscoveredSkill], renderer: SkillRenderer) -> SkillManifest:
        """Build the full SkillManifest from discovered skills."""
        resources = [self.build_skill(skill, renderer) for skill in skills]
        return SkillManifest(resources=resources)

    def build_all(self, *, dry_run: bool = False) -> SkillManifest:
        """Build all product skills and write the manifest."""
        skills = self.discoverer.discover()
        renderer = SkillRenderer()
        manifest = self.build_manifest(skills, renderer)

        if not dry_run and manifest.resources:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = self.output_dir / "manifest.json"
            manifest_path.write_text(json.dumps(manifest.model_dump(), indent=2) + "\n")

        return manifest

    def check_all(self) -> bool:
        """Check that the built manifest is up-to-date.

        Returns True if the manifest is current, False otherwise.
        """
        skills = self.discoverer.discover()

        if not skills:
            manifest_path = self.output_dir / "manifest.json"
            if manifest_path.exists():
                print(f"STALE:   {manifest_path.relative_to(self.repo_root)} (no skills found, but manifest exists)")
                return False
            print("No product skills found.")
            return True

        renderer = SkillRenderer()
        expected_manifest = self.build_manifest(skills, renderer)
        manifest_path = self.output_dir / "manifest.json"

        if not manifest_path.exists():
            print(f"MISSING: {manifest_path.relative_to(self.repo_root)}")
            return False

        actual_manifest = json.loads(manifest_path.read_text())
        expected_dict = expected_manifest.model_dump()
        if actual_manifest != expected_dict:
            print(f"STALE:   {manifest_path.relative_to(self.repo_root)}")

            actual_names = {r["name"] for r in actual_manifest.get("resources", [])}
            expected_names = {r.name for r in expected_manifest.resources}
            for added in expected_names - actual_names:
                print(f"  + {added} (new)")
            for removed in actual_names - expected_names:
                print(f"  - {removed} (removed)")
            for skill_name in actual_names & expected_names:
                actual_r = next(r for r in actual_manifest["resources"] if r["name"] == skill_name)
                expected_r = next(r for r in expected_manifest.resources if r.name == skill_name)
                if actual_r != expected_r.model_dump():
                    print(f"  ~ {skill_name} (changed)")

            return False

        print(f"OK:      {manifest_path.relative_to(self.repo_root)} ({len(expected_manifest.resources)} skill(s))")
        return True

    def _collect_lint_files(self, skill: DiscoveredSkill) -> list[tuple[Path, int]]:
        """Collect all files for linting from a skill, with their depth relative to skill dir.

        Returns list of (file_path, depth) tuples. Excludes test dirs/files.
        """
        if skill.depth == 0:
            return [(skill.source_file, 0)]

        skill_dir = skill.source_file.parent
        result: list[tuple[Path, int]] = []
        for root, dirs, filenames in os.walk(skill_dir):
            dirs[:] = [d for d in sorted(dirs) if d not in _TEST_DIR_NAMES]
            rel_root = Path(root).relative_to(skill_dir)
            depth = len(rel_root.parts)
            for filename in sorted(filenames):
                if _TEST_FILE_RE.match(filename):
                    continue
                result.append((Path(root) / filename, depth))
        return result

    def lint_all(self) -> bool:
        """Validate skill sources without rendering (no Django needed).

        Checks:
        - Binary file detection (only text files allowed)
        - Duplicate skill name detection (across products)
        - Jinja2 syntax validation via parse-only (all .j2 files)
        - Jinja2 template depth validation (.j2 files must be at most 1 level deep)
        - Frontmatter validation for static .md entry points (required: name, description)

        Returns True if all checks pass, False otherwise.
        """
        skills = self.discoverer.discover()
        errors: list[str] = []

        seen: dict[str, DiscoveredSkill] = {}
        for skill in skills:
            if skill.name in seen:
                first = seen[skill.name]
                errors.append(
                    f"Duplicate skill name '{skill.name}': "
                    f"{first.source_file.relative_to(self.repo_root)} and "
                    f"{skill.source_file.relative_to(self.repo_root)}"
                )
            else:
                seen[skill.name] = skill

        jinja_env = _create_jinja_env()

        for skill in skills:
            lint_files = self._collect_lint_files(skill)

            for file_path, depth in lint_files:
                source_label = str(file_path.relative_to(self.repo_root))

                try:
                    _assert_text_file(file_path)
                except ValueError as e:
                    errors.append(str(e))
                    continue

                if file_path.suffix == ".j2":
                    if depth > 1:
                        errors.append(f"Jinja2 template too deep (max 1 level): {source_label}")
                    raw = file_path.read_text()
                    try:
                        jinja_env.parse(raw)
                    except TemplateSyntaxError as e:
                        errors.append(f"Jinja2 syntax error in {source_label}: {e}")

            # Frontmatter validation only on the entry point when it's a static .md
            if skill.source_file.suffix != ".j2":
                raw = skill.source_file.read_text()
                source_label = str(skill.source_file.relative_to(self.repo_root))
                try:
                    validate_frontmatter(raw, source_label)
                except ValueError as e:
                    errors.append(str(e))

        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return False

        print(f"OK: {len(skills)} skill(s) passed lint checks.")
        return True

    def list_skills(self) -> None:
        """List all discovered product skills."""
        skills = self.discoverer.discover()

        if not skills:
            print("No product skills found in products/*/skills/.")
            return

        print(f"Found {len(skills)} product skill(s):\n")
        for skill in skills:
            product = skill.product_dir.name
            is_template = skill.source_file.suffix == ".j2"
            kind = "template" if is_template else "static"
            depth_label = f"depth={skill.depth}"
            print(f"  {skill.name:<40} product={product:<20} ({kind}, {depth_label})")


def _setup_django() -> None:
    """Set up Django (needed for importing product models during build/check).

    Sets dummy values for infrastructure env vars (Redis, etc.) that the settings
    module requires at import time. The build script never connects to these services
    — it only needs the Django ORM metadata and model imports to work.
    """
    try:
        import django

        django.setup()
    except SystemExit as e:
        print(
            f"ERROR: Django setup called sys.exit({e.code}). "
            "This usually means a required setting (e.g. SECRET_KEY) is missing. "
            "Skill building requires a working Django environment because Jinja2 "
            "templates import Pydantic models from product code.\n"
            "Hint: set SECRET_KEY in your environment or .env file.",
            file=sys.stderr,
        )
        raise SystemExit(1) from e
    except Exception as e:
        print(
            f"WARNING: Django setup failed ({e}). Template functions that import models will not work.",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=textwrap.dedent(__doc__),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if built manifest is up-to-date (exit 1 if not)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List discovered product skills without building",
    )
    parser.add_argument(
        "--lint",
        action="store_true",
        help="Validate skill sources without rendering (no Django needed)",
    )
    args = parser.parse_args()

    products_dir = REPO_ROOT / "products"
    output_dir = REPO_ROOT / "services" / "mcp" / "skills"
    builder = SkillBuilder(REPO_ROOT, products_dir, output_dir)

    if args.lint:
        if not builder.lint_all():
            sys.exit(1)
        return

    if args.list:
        builder.list_skills()
        return

    _setup_django()

    if args.check:
        if not builder.check_all():
            print("\nSkills are out of date. Run `hogli build:skills` to rebuild.")
            sys.exit(1)
        print("\nAll product skills are up-to-date.")
        return

    manifest = builder.build_all()
    if not manifest.resources:
        print("No product skills found in products/*/skills/.")
        return

    manifest_path = output_dir / "manifest.json"
    print(f"Built {len(manifest.resources)} skill(s) → {manifest_path.relative_to(REPO_ROOT)}")
    for r in manifest.resources:
        print(f"  {r.name:<40} source={r.source}")


if __name__ == "__main__":
    main()
