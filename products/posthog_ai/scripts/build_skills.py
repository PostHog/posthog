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
    uv run python products/posthog_ai/scripts/build_skills.py          # Build all product skills
    uv run python products/posthog_ai/scripts/build_skills.py --check  # Check if built skills are up-to-date (for CI)
    uv run python products/posthog_ai/scripts/build_skills.py --list   # List discovered skills without building
"""

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import textwrap
import importlib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from jinja2 import Environment, StrictUndefined
except ImportError:
    print("ERROR: jinja2 is required. Install with: pip install jinja2", file=sys.stderr)
    sys.exit(1)

_django_setup_done = False


def _ensure_django() -> None:
    """Set up Django if not already initialized (needed for importing product models)."""
    global _django_setup_done
    if _django_setup_done:
        return
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    try:
        import django

        django.setup()
        _django_setup_done = True
    except Exception as e:
        print(
            f"WARNING: Django setup failed ({e}). Template functions that import models will not work.", file=sys.stderr
        )


# ---------------------------------------------------------------------------
# Pydantic helpers exposed to Jinja2 templates
# ---------------------------------------------------------------------------


def _import_model(dotted_path: str) -> type:
    """Import a class by its fully-qualified dotted path.

    Example: ``products.feature_flags.backend.max_tools.FeatureFlagCreationSchema``

    Triggers Django setup on first call since product modules depend on Django.
    """
    _ensure_django()
    module_path, _, class_name = dotted_path.rpartition(".")
    if not module_path:
        raise ImportError(f"Invalid model path (need module.ClassName): {dotted_path}")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"{class_name} not found in {module_path}")
    return cls


def pydantic_schema(dotted_path: str, indent: int = 2) -> str:
    """Return the JSON Schema of a Pydantic model as a formatted JSON string.

    Usage in a template::

        ```json
        {{ pydantic_schema("products.feature_flags.backend.max_tools.FeatureFlagCreationSchema") }}
        ```
    """
    model_cls = _import_model(dotted_path)
    schema = model_cls.model_json_schema()
    return json.dumps(schema, indent=indent)


def pydantic_fields(dotted_path: str) -> str:
    """Return a Markdown table describing the fields of a Pydantic model.

    Columns: Field | Type | Required | Description

    Usage in a template::

        {{ pydantic_fields("products.feature_flags.backend.max_tools.FeatureFlagCreationSchema") }}
    """
    model_cls = _import_model(dotted_path)
    schema = model_cls.model_json_schema()
    required_set = set(schema.get("required", []))
    properties = schema.get("properties", {})

    rows: list[str] = []
    rows.append("| Field | Type | Required | Description |")
    rows.append("|-------|------|----------|-------------|")

    for name, prop in properties.items():
        field_type = _json_schema_type_label(prop)
        required = "yes" if name in required_set else "no"
        description = prop.get("description", "").replace("\n", " ").replace("|", "\\|")
        rows.append(f"| `{name}` | {field_type} | {required} | {description} |")

    return "\n".join(rows)


def pydantic_field_list(dotted_path: str) -> str:
    """Return a bullet list of field names with their types.

    Usage in a template::

        {{ pydantic_field_list("products.surveys.backend.max_tools.CreateTemplateArgs") }}
    """
    model_cls = _import_model(dotted_path)
    schema = model_cls.model_json_schema()
    properties = schema.get("properties", {})

    lines: list[str] = []
    for name, prop in properties.items():
        field_type = _json_schema_type_label(prop)
        desc = prop.get("description", "")
        line = f"- **`{name}`** ({field_type})"
        if desc:
            line += f": {desc}"
        lines.append(line)
    return "\n".join(lines)


def _json_schema_type_label(prop: dict) -> str:
    """Derive a human-readable type label from a JSON Schema property."""
    if "anyOf" in prop:
        parts = []
        for option in prop["anyOf"]:
            parts.append(option.get("type", option.get("$ref", "?")))
        return " | ".join(parts)
    if "allOf" in prop:
        refs = [opt.get("$ref", "?") for opt in prop["allOf"]]
        return " & ".join(refs)
    t = prop.get("type", "any")
    if t == "array":
        items = prop.get("items", {})
        item_type = items.get("type", items.get("$ref", "any"))
        return f"array[{item_type}]"
    return t


# ---------------------------------------------------------------------------
# YAML frontmatter parsing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract YAML frontmatter and body from a skill file.

    Returns (metadata_dict, body_without_frontmatter).
    Parses simple ``key: value`` pairs — no nested YAML needed.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw_yaml = match.group(1)
    body = text[match.end() :]
    metadata: dict[str, str] = {}

    for line in raw_yaml.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        if value:
            metadata[key.strip()] = value.strip().strip("'\"")

    return metadata, body


# ---------------------------------------------------------------------------
# Skill discovery and build
# ---------------------------------------------------------------------------

PRODUCTS_DIR = REPO_ROOT / "products"
OUTPUT_DIR = REPO_ROOT / "services" / "mcp" / "dist-skills"

MANIFEST_VERSION = "1.0.0"


def discover_product_skills() -> list[tuple[str, Path, Path]]:
    """Discover skill sources from products/*/skills/.

    Returns list of (skill_name, source_file, product_dir) tuples.
    source_file is either SKILL.md or SKILL.md.j2.
    """
    skills: list[tuple[str, Path, Path]] = []

    if not PRODUCTS_DIR.exists():
        return skills

    for product_dir in sorted(PRODUCTS_DIR.iterdir()):
        if not product_dir.is_dir():
            continue
        skills_dir = product_dir / "skills"
        if not skills_dir.exists():
            continue

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            # Prefer .j2 template over plain .md
            j2_file = skill_dir / "SKILL.md.j2"
            md_file = skill_dir / "SKILL.md"
            if j2_file.exists():
                skills.append((skill_dir.name, j2_file, product_dir))
            elif md_file.exists():
                skills.append((skill_dir.name, md_file, product_dir))

    return skills


def _make_jinja_env() -> Environment:
    """Create a Jinja2 environment with skill-building helpers."""
    env = Environment(
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        lstrip_blocks=True,
        trim_blocks=True,
    )
    env.globals["pydantic_schema"] = pydantic_schema
    env.globals["pydantic_fields"] = pydantic_fields
    env.globals["pydantic_field_list"] = pydantic_field_list
    return env


def render_skill(source_file: Path, jinja_env: Environment) -> str:
    """Render a skill source file to its final markdown content."""
    raw = source_file.read_text()

    if source_file.suffix == ".j2":
        template = jinja_env.from_string(raw)
        return template.render()

    return raw


def build_skill(skill_name: str, source_file: Path, jinja_env: Environment) -> dict[str, Any]:
    """Build a single skill and return a ContextMillResource dict.

    Parses YAML frontmatter for name/description, renders the template,
    and produces a manifest resource entry with the skill text inlined.
    """
    rendered = render_skill(source_file, jinja_env)
    metadata, body = parse_frontmatter(rendered)

    display_name = metadata.get("name", skill_name)
    description = metadata.get("description", f"Skill: {skill_name}")

    return {
        "id": skill_name,
        "name": display_name,
        "uri": f"skill://posthog/{skill_name}",
        "resource": {
            "mimeType": "text/markdown",
            "description": description,
            "text": body.strip(),
        },
        "source": str(source_file.relative_to(REPO_ROOT)),
    }


def build_manifest(skills: list[tuple[str, Path, Path]], jinja_env: Environment) -> dict[str, Any]:
    """Build the full ContextMillManifest dict from discovered skills."""
    resources: list[dict[str, Any]] = []
    for skill_name, source_file, _product_dir in skills:
        resource = build_skill(skill_name, source_file, jinja_env)
        resources.append(resource)

    return {
        "version": MANIFEST_VERSION,
        "resources": resources,
    }


def build_all(*, dry_run: bool = False) -> dict[str, Any]:
    """Build all product skills and write the manifest.

    Returns the manifest dict.
    """
    skills = discover_product_skills()
    jinja_env = _make_jinja_env()
    manifest = build_manifest(skills, jinja_env)

    if not dry_run and manifest["resources"]:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path = OUTPUT_DIR / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    return manifest


def check_all() -> bool:
    """Check that the built manifest is up-to-date.

    Returns True if the manifest is current, False otherwise.
    """
    skills = discover_product_skills()
    jinja_env = _make_jinja_env()

    if not skills:
        print("No product skills found.")
        return True

    expected_manifest = build_manifest(skills, jinja_env)
    manifest_path = OUTPUT_DIR / "manifest.json"

    if not manifest_path.exists():
        print(f"MISSING: {manifest_path.relative_to(REPO_ROOT)}")
        return False

    actual_manifest = json.loads(manifest_path.read_text())
    if actual_manifest != expected_manifest:
        print(f"STALE:   {manifest_path.relative_to(REPO_ROOT)}")

        # Show which skills changed
        actual_ids = {r["id"] for r in actual_manifest.get("resources", [])}
        expected_ids = {r["id"] for r in expected_manifest.get("resources", [])}
        for added in expected_ids - actual_ids:
            print(f"  + {added} (new)")
        for removed in actual_ids - expected_ids:
            print(f"  - {removed} (removed)")
        for skill_id in actual_ids & expected_ids:
            actual_r = next(r for r in actual_manifest["resources"] if r["id"] == skill_id)
            expected_r = next(r for r in expected_manifest["resources"] if r["id"] == skill_id)
            if actual_r != expected_r:
                print(f"  ~ {skill_id} (changed)")

        return False

    print(f"OK:      {manifest_path.relative_to(REPO_ROOT)} ({len(expected_manifest['resources'])} skill(s))")
    return True


def list_skills() -> None:
    """List all discovered product skills."""
    skills = discover_product_skills()

    if not skills:
        print("No product skills found in products/*/skills/.")
        return

    print(f"Found {len(skills)} product skill(s):\n")
    for skill_name, source_file, product_dir in skills:
        product = product_dir.name
        is_template = source_file.suffix == ".j2"
        kind = "template" if is_template else "static"
        print(f"  {skill_name:<40} product={product:<20} ({kind})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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
    args = parser.parse_args()

    if args.list:
        list_skills()
        return

    if args.check:
        ok = check_all()
        if not ok:
            print("\nSkills are out of date. Run `python products/posthog_ai/scripts/build_skills.py` to rebuild.")
            sys.exit(1)
        else:
            print("\nAll product skills are up-to-date.")
        return

    manifest = build_all()
    resources = manifest.get("resources", [])
    if not resources:
        print("No product skills found in products/*/skills/.")
        return

    manifest_path = OUTPUT_DIR / "manifest.json"
    print(f"Built {len(resources)} skill(s) → {manifest_path.relative_to(REPO_ROOT)}")
    for r in resources:
        print(f"  {r['id']:<40} uri={r['uri']}")


if __name__ == "__main__":
    main()
