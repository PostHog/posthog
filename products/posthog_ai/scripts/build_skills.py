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
from pydantic import BaseModel, Field, ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from jinja2 import Environment, StrictUndefined, TemplateSyntaxError
except ImportError:
    print("ERROR: jinja2 is required. Install with: pip install jinja2", file=sys.stderr)
    sys.exit(1)

MANIFEST_VERSION = "1.0.0"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillFrontmatter(BaseModel):
    name: str
    description: str


class DiscoveredSkill(BaseModel):
    name: str
    source_file: Path
    product_dir: Path
    depth: int


class SkillResourceContent(BaseModel):
    mimeType: str = "text/markdown"
    description: str
    text: str


class SkillResource(BaseModel):
    id: str
    name: str
    uri: str
    resource: SkillResourceContent
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

    def validate_depths(self, skills: list[DiscoveredSkill]) -> list[str]:
        """Check for depth 2+ violations (subdirectories inside depth-1 skill directories).

        Returns a list of error messages. Empty list means validation passed.
        """
        errors: list[str] = []
        for skill in skills:
            if skill.depth != 1:
                continue
            skill_dir = skill.source_file.parent
            for child in skill_dir.iterdir():
                if child.is_dir():
                    errors.append(
                        f"Nested subdirectory not allowed in skill directory: "
                        f"{child.relative_to(self.products_dir.parent)}"
                    )
        return errors


class SkillRenderer:
    """Renders skill source files to final markdown via Jinja2."""

    def __init__(self) -> None:
        from products.posthog_ai.scripts.pydantic_schema import pydantic_field_list, pydantic_fields, pydantic_schema

        self.env = Environment(
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            lstrip_blocks=True,
            trim_blocks=True,
        )
        self.env.globals["pydantic_schema"] = pydantic_schema
        self.env.globals["pydantic_fields"] = pydantic_fields
        self.env.globals["pydantic_field_list"] = pydantic_field_list

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

    def build_skill(self, skill: DiscoveredSkill, renderer: SkillRenderer) -> SkillResource:
        """Build a single skill and return a SkillResource."""
        rendered = renderer.render(skill.source_file)
        metadata, body = parse_frontmatter(rendered)

        display_name = metadata.get("name", skill.name)
        description = metadata.get("description", f"Skill: {skill.name}")

        return SkillResource(
            id=skill.name,
            name=display_name,
            uri=f"skill://posthog/{skill.name}",
            resource=SkillResourceContent(
                description=description,
                text=body.strip(),
            ),
            source=str(skill.source_file.relative_to(self.repo_root)),
        )

    def build_manifest(self, skills: list[DiscoveredSkill], renderer: SkillRenderer) -> SkillManifest:
        """Build the full SkillManifest from discovered skills."""
        resources = [self.build_skill(skill, renderer) for skill in skills]
        return SkillManifest(resources=resources)

    def build_all(self, *, dry_run: bool = False) -> SkillManifest:
        """Build all product skills and write the manifest."""
        skills = self.discoverer.discover()

        depth_errors = self.discoverer.validate_depths(skills)
        if depth_errors:
            for err in depth_errors:
                print(f"ERROR: {err}", file=sys.stderr)
            raise SystemExit(1)

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

            actual_ids = {r["id"] for r in actual_manifest.get("resources", [])}
            expected_ids = {r.id for r in expected_manifest.resources}
            for added in expected_ids - actual_ids:
                print(f"  + {added} (new)")
            for removed in actual_ids - expected_ids:
                print(f"  - {removed} (removed)")
            for skill_id in actual_ids & expected_ids:
                actual_r = next(r for r in actual_manifest["resources"] if r["id"] == skill_id)
                expected_r = next(r for r in expected_manifest.resources if r.id == skill_id)
                if actual_r != expected_r.model_dump():
                    print(f"  ~ {skill_id} (changed)")

            return False

        print(f"OK:      {manifest_path.relative_to(self.repo_root)} ({len(expected_manifest.resources)} skill(s))")
        return True

    def lint_all(self) -> bool:
        """Validate skill sources without rendering (no Django needed).

        Checks:
        - Depth validation (no depth 2+)
        - Duplicate skill name detection (across products)
        - Jinja2 syntax validation via parse-only
        - Frontmatter validation for static .md files (required: name, description)

        Returns True if all checks pass, False otherwise.
        """
        skills = self.discoverer.discover()
        errors: list[str] = []

        errors.extend(self.discoverer.validate_depths(skills))

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

        jinja_env = Environment(
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            lstrip_blocks=True,
            trim_blocks=True,
        )

        for skill in skills:
            raw = skill.source_file.read_text()
            source_label = str(skill.source_file.relative_to(self.repo_root))

            if skill.source_file.suffix == ".j2":
                try:
                    jinja_env.parse(raw)
                except TemplateSyntaxError as e:
                    errors.append(f"Jinja2 syntax error in {source_label}: {e}")
            else:
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
    """Set up Django (needed for importing product models during build/check)."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    try:
        import django

        django.setup()
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

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    products_dir = repo_root / "products"
    output_dir = repo_root / "services" / "mcp" / "skills"
    builder = SkillBuilder(repo_root, products_dir, output_dir)

    if args.lint:
        ok = builder.lint_all()
        if not ok:
            sys.exit(1)
        return

    if args.list:
        builder.list_skills()
        return

    _setup_django()

    if args.check:
        ok = builder.check_all()
        if not ok:
            print("\nSkills are out of date. Run `hogli build:skills` to rebuild.")
            sys.exit(1)
        else:
            print("\nAll product skills are up-to-date.")
        return

    manifest = builder.build_all()
    if not manifest.resources:
        print("No product skills found in products/*/skills/.")
        return

    manifest_path = output_dir / "manifest.json"
    print(f"Built {len(manifest.resources)} skill(s) → {manifest_path.relative_to(repo_root)}")
    for r in manifest.resources:
        print(f"  {r.id:<40} uri={r.uri}")


if __name__ == "__main__":
    main()
