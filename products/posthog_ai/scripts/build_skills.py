#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Build coding agent skills from products/*/skills/ into rendered files, per-skill
archives, and a registry index for distribution.

Skills can be:
- Plain markdown (SKILL.md) — copied as-is
- Jinja2 templates (SKILL.md.j2) — rendered with Python context including Pydantic schema helpers

Skills under products/community/skills/ are community-contributed and subject to
stricter rules: markdown only (no .j2, no scripts/). See
products/community/skills/CONTRIBUTING.md.

Each skill must have YAML frontmatter with ``name`` and ``description``, validated
against ``SkillFrontmatter``.

The build renders skills to dist/skills/{skill_name}/ (gitignored, human-readable)
and produces three sets of artifacts, all published as release assets by CI:
- dist/skills.zip              monolithic archive (preserved for existing consumers)
- dist/<skill-name>.zip        per-skill archive for granular install
- dist/skills-index.json       registry index consumed by agents, IDEs, and the MCP server

Requires the project's Python environment (managed by uv) for template rendering
that imports Pydantic models from product code.

Usage:
    hogli build:skills          # Build all product skills + registry artifacts
    hogli build:skills --list   # List discovered skills without building
    hogli lint:skills           # Validate skill sources without rendering
"""

from __future__ import annotations

import os
import re
import sys
import json
import shutil
import hashlib
import zipfile
import argparse
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError
from pydantic import BaseModel, Field, ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

MANIFEST_VERSION = "1.0.0"
INDEX_SCHEMA_VERSION = "1.0.0"
_ZIP_FIXED_TIME = (2025, 1, 1, 0, 0, 0)

# Stable URL prefix for per-skill archives published as release assets.
# The `agent-skills-latest` release is updated on every master build.
DEFAULT_ARCHIVE_URL_PREFIX = "https://github.com/PostHog/posthog/releases/download/agent-skills-latest"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_BINARY_CHECK_SIZE = 8192
_ALLOWED_SUBDIRS = {"references", "scripts"}

# Community skills live at products/community/skills/ and have stricter rules:
# markdown only, no Jinja2 templates, no scripts/.
# See products/community/skills/CONTRIBUTING.md.
_COMMUNITY_PRODUCT = "community"
_COMMUNITY_ALLOWED_SUBDIRS = {"references"}


def _create_jinja_env(**extra_globals: object) -> Environment:
    """Create a Jinja2 Environment with the standard skill rendering settings."""
    env = Environment(
        # nosemgrep: python.jinja2.security.audit.autoescape-disabled-false.incorrect-autoescape-disabled -- output is Markdown for a JSON manifest, not HTML
        autoescape=False,
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

    @property
    def is_community(self) -> bool:
        return self.product_dir.name == _COMMUNITY_PRODUCT


class SkillFile(BaseModel):
    path: str
    content: str


class SkillResource(BaseModel):
    name: str
    description: str
    files: list[SkillFile]
    source: str


class SkillIndexEntry(BaseModel):
    """Single entry in the registry index — metadata only, no file contents."""

    name: str
    description: str
    archive_url: str
    sha256: str
    source_path: str


class SkillsIndex(BaseModel):
    """Registry index of all published skills. Consumed by agents, IDEs,
    and the MCP server to list/filter skills without downloading archives."""

    version: str = INDEX_SCHEMA_VERSION
    generated_at: str
    skills: list[SkillIndexEntry] = Field(default_factory=list)


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
                # Skip hidden entries (e.g. .template/, .gitignore). This keeps
                # the community/skills/.template/ scaffold out of the registry.
                if entry.name.startswith("."):
                    continue
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
                elif (
                    entry.is_file()
                    and entry.name not in {"README.md", "CONTRIBUTING.md"}
                    and (entry.name.endswith(".md.j2") or entry.name.endswith(".md"))
                ):
                    if entry.name.endswith(".md") and (entry.parent / (entry.name + ".j2")).exists():
                        continue
                    skill_name = entry.name.removesuffix(".j2").removesuffix(".md")
                    skills.append(DiscoveredSkill(name=skill_name, source_file=entry, product_dir=product_dir, depth=0))

        return skills


class SkillRenderer:
    """Renders skill source files to final markdown via Jinja2."""

    def __init__(self) -> None:
        from products.posthog_ai.scripts.audit_constants import audit_constants
        from products.posthog_ai.scripts.hogql_example import render_hogql_example
        from products.posthog_ai.scripts.hogql_functions import hogql_functions
        from products.posthog_ai.scripts.pydantic_schema import pydantic_schema

        self.env = _create_jinja_env(
            pydantic_schema=pydantic_schema,
            render_hogql_example=render_hogql_example,
            hogql_functions=hogql_functions,
            audit_constants=audit_constants,
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
        self.dist_dir = output_dir / "dist"
        self.skills_dist_dir = self.dist_dir / "skills"
        self.discoverer = SkillDiscoverer(products_dir)

    def collect_skill_files(
        self,
        skill_dir: Path,
        renderer: SkillRenderer,
        *,
        is_community: bool = False,
    ) -> list[SkillFile]:
        """Collect and render files from a skill directory using an explicit allowlist.

        Only collects from three sources:
        1. Entry point: SKILL.md.j2 (preferred) or SKILL.md
        2. references/ directory (recursive)
        3. scripts/ directory (recursive) — disallowed for community skills

        Community skills (under ``products/community/skills/``) are restricted to
        markdown-only references so untrusted contributions can't smuggle in
        executable Python or Jinja2 templates with access to Django internals.

        .j2 files are rendered through Jinja2 and have the .j2 extension stripped.
        Returns a list of SkillFile with SKILL.md always first.
        """
        j2_entry = skill_dir / "SKILL.md.j2"
        md_entry = skill_dir / "SKILL.md"
        if is_community and j2_entry.exists():
            raise ValueError(
                f"Community skill {skill_dir.name} may not use SKILL.md.j2 (templates disabled for community). "
                "Use plain SKILL.md instead."
            )
        if j2_entry.exists():
            entry_path = j2_entry
        elif md_entry.exists():
            entry_path = md_entry
        else:
            raise ValueError(f"Missing SKILL.md entry point in {skill_dir.name}")

        _assert_text_file(entry_path)
        entry_content = renderer.render(entry_path)
        entry_point = SkillFile(path="SKILL.md", content=entry_content)

        allowed_subdirs = _COMMUNITY_ALLOWED_SUBDIRS if is_community else _ALLOWED_SUBDIRS

        if is_community and (skill_dir / "scripts").is_dir():
            raise ValueError(
                f"Community skill {skill_dir.name} may not contain a scripts/ directory. "
                "Community skills are markdown-only."
            )

        files: list[SkillFile] = []
        for subdir_name in sorted(allowed_subdirs):
            subdir = skill_dir / subdir_name
            if not subdir.is_dir():
                continue
            for root, dirs, filenames in os.walk(subdir):
                dirs[:] = sorted(dirs)
                for filename in sorted(filenames):
                    file_path = Path(root) / filename
                    _assert_text_file(file_path)
                    if is_community and file_path.suffix == ".j2":
                        raise ValueError(
                            f"Community skill {skill_dir.name} may not contain .j2 templates "
                            f"(found {file_path.relative_to(skill_dir)}). Use plain markdown instead."
                        )
                    content = renderer.render(file_path)
                    rel_path = str(file_path.relative_to(skill_dir)).removesuffix(".j2")
                    files.append(SkillFile(path=rel_path, content=content))

        return [entry_point, *files]

    def build_skill(self, skill: DiscoveredSkill, renderer: SkillRenderer) -> SkillResource:
        """Build a single skill and return a SkillResource.

        Skills missing the required frontmatter fail at build time rather than
        producing silently-underspecified index entries.
        """
        if skill.depth == 1:
            skill_dir = skill.source_file.parent
            skill_files = self.collect_skill_files(skill_dir, renderer, is_community=skill.is_community)
            entry_content = skill_files[0].content
            source = str(skill_dir.relative_to(self.repo_root))
            source_label = source
        else:
            if skill.is_community and skill.source_file.suffix == ".j2":
                raise ValueError(
                    f"Community skill {skill.name} may not use .j2 templates "
                    f"(found {skill.source_file.relative_to(self.repo_root)}). Use plain markdown."
                )
            rendered = renderer.render(skill.source_file)
            entry_content = rendered
            out_name = skill.source_file.name.removesuffix(".j2")
            skill_files = [SkillFile(path=out_name, content=rendered.strip())]
            source = str(skill.source_file.relative_to(self.repo_root))
            source_label = source

        frontmatter = validate_frontmatter(entry_content, source_label)

        return SkillResource(
            name=frontmatter.name,
            description=frontmatter.description,
            files=skill_files,
            source=source,
        )

    def build_manifest(self, skills: list[DiscoveredSkill], renderer: SkillRenderer) -> SkillManifest:
        """Build the full SkillManifest from discovered skills."""
        resources = [self.build_skill(skill, renderer) for skill in skills]
        return SkillManifest(resources=resources)

    def build_all(self, *, dry_run: bool = False) -> SkillManifest:
        """Build all product skills and write rendered files to skills_dist/."""
        skills = self.discoverer.discover()
        renderer = SkillRenderer()
        manifest = self.build_manifest(skills, renderer)

        if not dry_run and manifest.resources:
            if self.skills_dist_dir.exists():
                shutil.rmtree(self.skills_dist_dir)
            for resource in manifest.resources:
                for skill_file in resource.files:
                    file_path = self.skills_dist_dir / resource.name / skill_file.path
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(skill_file.content)

        return manifest

    def pack(self) -> Path:
        """Build skills and package skills_dist/ into dist/skills.zip."""
        self.build_all()
        return self._zip_skills_dist()

    def _zip_skills_dist(self) -> Path:
        """Create dist/skills.zip from the dist/skills/ directory.

        The monolithic zip is preserved as-is for backwards compatibility
        with existing consumers that download ``skills.zip`` directly.
        """
        zip_path = self.dist_dir / "skills.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(self.skills_dist_dir.rglob("*")):
                if file_path.is_file():
                    arcname = str(file_path.relative_to(self.skills_dist_dir))
                    info = zipfile.ZipInfo(arcname, date_time=_ZIP_FIXED_TIME)
                    zf.writestr(info, file_path.read_text())
        return zip_path

    def _zip_individual_skill(self, resource: SkillResource) -> tuple[Path, str]:
        """Create dist/<skill-name>.zip for a single skill and return (path, sha256).

        Per-skill zips let agents and the registry install a single skill without
        downloading the monolithic archive.
        """
        zip_path = self.dist_dir / f"{resource.name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for skill_file in resource.files:
                info = zipfile.ZipInfo(skill_file.path, date_time=_ZIP_FIXED_TIME)
                zf.writestr(info, skill_file.content)

        sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        return zip_path, sha

    def _build_index(
        self,
        resources: list[SkillResource],
        checksums: dict[str, str],
        *,
        archive_url_prefix: str,
        generated_at: str,
    ) -> SkillsIndex:
        """Build the SkillsIndex from built resources.

        ``archive_url_prefix`` points at the GitHub release that will host the
        per-skill zips. Defaults to the ``agent-skills-latest`` rolling release.
        Override via ``HOGLI_SKILLS_ARCHIVE_URL_PREFIX`` for staging/testing.
        """
        entries: list[SkillIndexEntry] = []
        for resource in resources:
            entries.append(
                SkillIndexEntry(
                    name=resource.name,
                    description=resource.description,
                    archive_url=f"{archive_url_prefix.rstrip('/')}/{resource.name}.zip",
                    sha256=checksums[resource.name],
                    source_path=resource.source,
                )
            )

        return SkillsIndex(generated_at=generated_at, skills=entries)

    def pack_registry(self, *, archive_url_prefix: str | None = None) -> tuple[Path, Path, list[Path]]:
        """Build skills and produce the full registry artifacts.

        Returns a tuple of:
          - the monolithic ``dist/skills.zip`` (unchanged layout, backwards compatible)
          - ``dist/skills-index.json`` (the registry index)
          - list of per-skill ``dist/<skill-name>.zip`` paths

        This is the artifact set published by the ``release-skills`` CI job.
        """
        manifest = self.build_all()
        monolithic = self._zip_skills_dist()

        prefix = archive_url_prefix or os.environ.get("HOGLI_SKILLS_ARCHIVE_URL_PREFIX", DEFAULT_ARCHIVE_URL_PREFIX)
        generated_at = os.environ.get("HOGLI_SKILLS_GENERATED_AT") or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        checksums: dict[str, str] = {}
        individual_zips: list[Path] = []
        for resource in manifest.resources:
            zip_path, sha = self._zip_individual_skill(resource)
            checksums[resource.name] = sha
            individual_zips.append(zip_path)

        index = self._build_index(
            manifest.resources,
            checksums,
            archive_url_prefix=prefix,
            generated_at=generated_at,
        )
        index_path = self.dist_dir / "skills-index.json"
        index_path.write_text(json.dumps(index.model_dump(), indent=2, sort_keys=False) + "\n")

        return monolithic, index_path, individual_zips

    def _collect_lint_files(self, skill: DiscoveredSkill) -> list[Path]:
        """Collect all files for linting from a skill using the allowlist.

        Only collects SKILL.md(.j2), references/, and scripts/.
        """
        if skill.depth == 0:
            return [skill.source_file]

        skill_dir = skill.source_file.parent
        result: list[Path] = [skill.source_file]
        for subdir_name in sorted(_ALLOWED_SUBDIRS):
            subdir = skill_dir / subdir_name
            if not subdir.is_dir():
                continue
            for root, dirs, filenames in os.walk(subdir):
                dirs[:] = sorted(dirs)
                for filename in sorted(filenames):
                    result.append(Path(root) / filename)
        return result

    def lint_all(self) -> bool:
        """Validate skill sources without rendering (no Django needed).

        Checks:
        - Binary file detection (only text files allowed)
        - Duplicate skill name detection (across products)
        - Jinja2 syntax validation via parse-only (all .j2 files)
        - Frontmatter validation for static .md entry points (schema + constraints)
        - Community-skill restrictions: no .j2 templates, no scripts/ subdirectory

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

            for file_path in lint_files:
                source_label = str(file_path.relative_to(self.repo_root))

                try:
                    _assert_text_file(file_path)
                except ValueError as e:
                    errors.append(str(e))
                    continue

                if file_path.suffix == ".j2":
                    raw = file_path.read_text()
                    try:
                        jinja_env.parse(raw)
                    except TemplateSyntaxError as e:
                        errors.append(f"Jinja2 syntax error in {source_label}: {e}")

            if skill.source_file.suffix != ".j2":
                raw = skill.source_file.read_text()
                source_label = str(skill.source_file.relative_to(self.repo_root))
                try:
                    validate_frontmatter(raw, source_label)
                except ValueError as e:
                    errors.append(str(e))
            elif skill.is_community:
                # .j2 already disallowed, but surface the error with a clearer message.
                errors.append(
                    f"Community skill {skill.name} ({skill.source_file.relative_to(self.repo_root)}) "
                    "may not use .j2 templates. Use plain SKILL.md."
                )

            errors.extend(self._lint_community_rules(skill))

        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return False

        print(f"OK: {len(skills)} skill(s) passed lint checks.")
        return True

    def _lint_community_rules(self, skill: DiscoveredSkill) -> list[str]:
        """Return any community-skill violations for a discovered skill.

        Called from lint_all so community PRs fail fast without Django, matching
        the stricter rules enforced at build time in ``collect_skill_files`` /
        ``build_skill``. Community vs official is determined solely by location
        (``products/community/skills/``).
        """
        errors: list[str] = []
        if not skill.is_community or skill.depth != 1:
            return errors

        source_label = str(skill.source_file.relative_to(self.repo_root))
        skill_dir = skill.source_file.parent
        if (skill_dir / "scripts").is_dir():
            errors.append(f"{source_label}: community skills may not contain a scripts/ directory (markdown-only).")
        # Any .j2 inside references/ is disallowed too.
        for subdir_name in sorted(_ALLOWED_SUBDIRS):
            subdir = skill_dir / subdir_name
            if not subdir.is_dir():
                continue
            for root, _dirs, filenames in os.walk(subdir):
                for filename in filenames:
                    if filename.endswith(".j2"):
                        errors.append(
                            f"{source_label}: community skills may not contain .j2 templates "
                            f"(found {Path(root, filename).relative_to(self.repo_root)})."
                        )
        return errors

    def init_skill(self, product_name: str, skill_name: str, *, template: bool = False) -> Path:
        """Scaffold a new skill directory with SKILL.md boilerplate.

        Creates products/{product}/skills/{skill-name}/ with a SKILL.md (or .md.j2)
        stub and a references/ subdirectory.

        Returns the path to the created skill file.
        """
        product_dir = self.products_dir / product_name
        if not product_dir.is_dir():
            raise FileNotFoundError(f"Product directory does not exist: products/{product_name}")

        skill_dir = product_dir / "skills" / skill_name
        if skill_dir.exists():
            raise FileExistsError(f"Skill directory already exists: {skill_dir.relative_to(self.repo_root)}")

        skill_dir.mkdir(parents=True)
        (skill_dir / "references").mkdir()

        display_name = skill_name.replace("-", " ").capitalize()
        filename = "SKILL.md.j2" if template else "SKILL.md"
        content = textwrap.dedent(f"""\
            ---
            name: {skill_name}
            description: TODO
            ---

            # {display_name}

            TODO: Describe when and how to use this skill.

            ## When to use this skill

            TODO

            ## Workflow

            TODO
        """)

        skill_file = skill_dir / filename
        skill_file.write_text(content)
        return skill_file

    # ------------------------------------------------------------------
    # Sync / unsync: copy built skills to .agents/skills/ for local testing
    # ------------------------------------------------------------------

    _SYNCED_SKILLS_MARKER = "# Synced product skills (managed by hogli sync:skill)"

    def sync_skill(self, skill_name: str) -> Path:
        """Build a skill and copy it to .agents/skills/ for local Claude Code testing.

        Returns the path to the synced skill directory.
        """
        skills = self.discoverer.discover()
        match = next((s for s in skills if s.name == skill_name), None)
        if match is None:
            available = ", ".join(s.name for s in skills)
            raise ValueError(f"Skill '{skill_name}' not found. Available: {available}")

        manifest = self.build_all()

        # Find the built resource — build order matches discovery order
        resource = next((r for s, r in zip(skills, manifest.resources) if s.name == skill_name), None)
        if resource is None:
            raise ValueError(f"Skill '{skill_name}' was discovered but not built")

        agents_skills_dir = self.repo_root / ".agents" / "skills"
        target_dir = agents_skills_dir / resource.name

        if target_dir.exists():
            shutil.rmtree(target_dir)

        source_dir = self.skills_dist_dir / resource.name
        shutil.copytree(source_dir, target_dir)

        self._ensure_gitignored(resource.name)
        return target_dir

    def unsync_skill(self, skill_name: str) -> None:
        """Remove a previously synced skill from .agents/skills/."""
        agents_skills_dir = self.repo_root / ".agents" / "skills"

        # Try the name directly, and also resolve via discovery for frontmatter name
        names_to_try = [skill_name]
        skills = self.discoverer.discover()
        match = next((s for s in skills if s.name == skill_name), None)
        if match is not None and match.source_file.suffix != ".j2":
            try:
                metadata, _ = parse_frontmatter(match.source_file.read_text())
                fm_name = metadata.get("name", skill_name)
                if fm_name != skill_name and fm_name not in names_to_try:
                    names_to_try.append(fm_name)
            except Exception:
                pass

        for name in names_to_try:
            target_dir = agents_skills_dir / name
            if target_dir.exists():
                shutil.rmtree(target_dir)
                self._remove_gitignore_entry(name)
                print(f"Removed synced skill: .agents/skills/{name}")
                return

        print(f"No synced skill found for '{skill_name}'", file=sys.stderr)
        sys.exit(1)

    def _ensure_gitignored(self, skill_name: str) -> None:
        """Add skill to .agents/skills/.gitignore if not already present."""
        gitignore_path = self.repo_root / ".agents" / "skills" / ".gitignore"
        entry = f"/{skill_name}"

        if gitignore_path.exists():
            content = gitignore_path.read_text()
            if entry in content.splitlines():
                return
        else:
            content = ""

        if not content:
            content = f"{self._SYNCED_SKILLS_MARKER}\n"

        if not content.endswith("\n"):
            content += "\n"

        content += f"{entry}\n"
        gitignore_path.write_text(content)

    def _remove_gitignore_entry(self, skill_name: str) -> None:
        """Remove skill from .agents/skills/.gitignore."""
        gitignore_path = self.repo_root / ".agents" / "skills" / ".gitignore"
        if not gitignore_path.exists():
            return
        entry = f"/{skill_name}"
        lines = gitignore_path.read_text().splitlines()
        lines = [line for line in lines if line != entry]
        remaining = [line for line in lines if line.strip() and not line.startswith("#")]
        if not remaining:
            gitignore_path.unlink()
        else:
            gitignore_path.write_text("\n".join(lines) + "\n")

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
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
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
        description=textwrap.dedent(__doc__ or ""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
    parser.add_argument(
        "--init",
        action="store_true",
        help="Scaffold a new skill directory with SKILL.md boilerplate",
    )
    parser.add_argument(
        "--product",
        help="Product name for --init (e.g. feature_flags)",
    )
    parser.add_argument(
        "--name",
        help="Skill name for --init (e.g. my-new-skill)",
    )
    parser.add_argument(
        "--j2",
        action="store_true",
        help="Create SKILL.md.j2 instead of SKILL.md (use with --init)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Build a skill and sync it to .agents/skills/ for local testing",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove a previously synced skill from .agents/skills/ (use with --sync)",
    )
    args = parser.parse_args()

    products_dir = REPO_ROOT / "products"
    output_dir = REPO_ROOT / "products" / "posthog_ai"
    builder = SkillBuilder(REPO_ROOT, products_dir, output_dir)

    if args.init:
        if not args.product or not args.name:
            parser.error("--init requires --product and --name")
        try:
            skill_file = builder.init_skill(args.product, args.name, template=args.j2)
            print(f"Created {skill_file.relative_to(REPO_ROOT)}")
        except (FileNotFoundError, FileExistsError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.lint:
        if not builder.lint_all():
            sys.exit(1)
        return

    if args.sync:
        if not args.name:
            builder.list_skills()
            print("\nUsage: hogli sync:skill -- --name <skill-name>")
            return
        if args.clean:
            builder.unsync_skill(args.name)
            return
        _setup_django()
        try:
            target = builder.sync_skill(args.name)
            print(f"Synced skill to {target.relative_to(REPO_ROOT)}")
            print(f"  Available via .claude/skills/{target.name}/ for Claude Code")
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.list:
        builder.list_skills()
        return

    _setup_django()

    monolithic, index_path, individual_zips = builder.pack_registry()
    if not individual_zips:
        print("No product skills found in products/*/skills/.")
        return

    print(f"Built {len(individual_zips)} skill(s):")
    print(f"  monolithic archive → {monolithic.relative_to(REPO_ROOT)}")
    print(f"  registry index     → {index_path.relative_to(REPO_ROOT)}")
    print(f"  per-skill archives → {builder.dist_dir.relative_to(REPO_ROOT)}/<skill>.zip")
    for zip_path in individual_zips:
        print(f"    {zip_path.name}")


if __name__ == "__main__":
    main()
