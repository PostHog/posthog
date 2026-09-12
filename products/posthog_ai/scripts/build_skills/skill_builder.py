# ruff: noqa: T201 allow print statements
"""Building, packing, scaffolding and syncing skills."""

from __future__ import annotations

import os
import sys
import shutil
import zipfile
import textwrap
from pathlib import Path

from jinja2 import TemplateSyntaxError

from . import (
    discovery,
    frontmatter,
    reference_links,
    rendering,
    reserved_names,
    skill_manifest,
    source_files,
    tool_references,
)

_ZIP_FIXED_TIME = (2025, 1, 1, 0, 0, 0)


class SkillBuilder:
    """Orchestrates skill discovery, rendering, and manifest generation."""

    def __init__(self, repo_root: Path, products_dir: Path, output_dir: Path) -> None:
        self.repo_root = repo_root
        self.products_dir = products_dir
        self.output_dir = output_dir
        self.dist_dir = output_dir / "dist"
        self.skills_dist_dir = self.dist_dir / "skills"
        self.discoverer = discovery.SkillDiscoverer(products_dir)

    def collect_skill_files(self, skill_dir: Path, renderer: rendering.SkillRenderer) -> list[skill_manifest.SkillFile]:
        """Collect and render files from a skill directory using an explicit allowlist.

        Only collects from three sources:
        1. Entry point: SKILL.md.j2 (preferred) or SKILL.md
        2. references/ directory (recursive)
        3. scripts/ directory (recursive)

        .j2 files are rendered through Jinja2 and have the .j2 extension stripped.
        Returns a list of SkillFile with SKILL.md always first.
        """
        j2_entry = skill_dir / "SKILL.md.j2"
        md_entry = skill_dir / "SKILL.md"
        if j2_entry.exists():
            entry_path = j2_entry
        elif md_entry.exists():
            entry_path = md_entry
        else:
            raise ValueError(f"Missing SKILL.md entry point in {skill_dir.name}")

        source_files._assert_text_file(entry_path)
        entry_content = renderer.render(entry_path)
        entry_point = skill_manifest.SkillFile(path="SKILL.md", content=entry_content)

        files: list[skill_manifest.SkillFile] = []
        for subdir_name in sorted(source_files._ALLOWED_SUBDIRS):
            subdir = skill_dir / subdir_name
            if not subdir.is_dir():
                continue
            for root, dirs, filenames in os.walk(subdir):
                dirs[:] = sorted(dirs)
                for filename in sorted(filenames):
                    file_path = Path(root) / filename
                    source_files._assert_text_file(file_path)
                    content = renderer.render(file_path)
                    rel_path = str(file_path.relative_to(skill_dir))
                    if rel_path.endswith(".j2"):
                        rel_path = rel_path.removesuffix(".j2")
                    files.append(skill_manifest.SkillFile(path=rel_path, content=content))

        return [entry_point, *files]

    def build_skill(
        self, skill: skill_manifest.DiscoveredSkill, renderer: rendering.SkillRenderer
    ) -> skill_manifest.SkillResource:
        """Build a single skill and return a SkillResource."""
        if skill.depth == 1:
            skill_dir = skill.source_file.parent
            skill_files = self.collect_skill_files(skill_dir, renderer)
            rendered_entry_content = skill_files[0].content
            metadata, _body = frontmatter.parse_frontmatter(rendered_entry_content)
            source = str(skill_dir.relative_to(self.repo_root))
        else:
            rendered_entry_content = renderer.render(skill.source_file)
            metadata, _body = frontmatter.parse_frontmatter(rendered_entry_content)
            out_name = skill.source_file.name
            if out_name.endswith(".j2"):
                out_name = out_name.removesuffix(".j2")
            skill_files = [skill_manifest.SkillFile(path=out_name, content=rendered_entry_content.strip())]
            source = str(skill.source_file.relative_to(self.repo_root))

        if metadata:
            validated_metadata = frontmatter.validate_frontmatter(rendered_entry_content, source)
            display_name = validated_metadata.name
            description = validated_metadata.description
        else:
            display_name = skill.name
            description = f"Skill: {skill.name}"

        # lint_all reads the raw frontmatter, so a name that only becomes an
        # omnibus name after rendering slips past it. Here the name is rendered,
        # so catch that case before it builds into a context-mill-owned directory.
        if display_name in reserved_names.OMNIBUS_SKILL_NAMES:
            raise ValueError(
                f"'{display_name}' is owned by PostHog/context-mill, which every consumer "
                f"overlays on top of this repo's skills, so a copy here is overwritten "
                f"rather than shipped. Remove {source} and change the context-mill source instead."
            )

        return skill_manifest.SkillResource(
            name=display_name,
            description=description,
            files=skill_files,
            source=source,
        )

    def build_manifest(
        self, skills: list[skill_manifest.DiscoveredSkill], renderer: rendering.SkillRenderer
    ) -> skill_manifest.SkillManifest:
        """Build the full SkillManifest from discovered skills."""
        resources = [self.build_skill(skill, renderer) for skill in skills]
        return skill_manifest.SkillManifest(resources=resources)

    def build_all(self, *, dry_run: bool = False) -> skill_manifest.SkillManifest:
        """Build all product skills and write rendered files to skills_dist/."""
        skills = self.discoverer.discover()
        renderer = rendering.SkillRenderer()
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
        """Create dist/skills.zip from the dist/skills/ directory."""
        zip_path = self.dist_dir / "skills.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(self.skills_dist_dir.rglob("*")):
                if file_path.is_file():
                    arcname = str(file_path.relative_to(self.skills_dist_dir))
                    info = zipfile.ZipInfo(arcname, date_time=_ZIP_FIXED_TIME)
                    zf.writestr(info, file_path.read_text())
        return zip_path

    def _collect_lint_files(self, skill: skill_manifest.DiscoveredSkill) -> list[Path]:
        """Collect all files for linting from a skill using the allowlist.

        Only collects SKILL.md(.j2), references/, and scripts/.
        """
        if skill.depth == 0:
            return [skill.source_file]

        skill_dir = skill.source_file.parent
        result: list[Path] = [skill.source_file]
        for subdir_name in sorted(source_files._ALLOWED_SUBDIRS):
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
        - Frontmatter validation for product and project skill entry points
        - Tool/skill reference validation in markdown (against the MCP schema registries)

        Returns True if all checks pass, False otherwise.
        """
        skills = self.discoverer.discover()
        errors: list[str] = []
        reference_findings: list[tool_references.ReferenceFinding] = []

        seen: dict[str, skill_manifest.DiscoveredSkill] = {}
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

            unrendered_name = discovery._unrendered_skill_name(skill)
            if unrendered_name in reserved_names.OMNIBUS_SKILL_NAMES:
                errors.append(
                    f"'{unrendered_name}' is owned by PostHog/context-mill, which every consumer "
                    f"overlays on top of this repo's skills, so a copy here is overwritten "
                    f"rather than shipped. Remove {skill.source_file.relative_to(self.repo_root)} "
                    f"and change the context-mill source instead."
                )

        tool_names = tool_references._load_mcp_tool_names(self.repo_root)
        if tool_names is None:
            print("WARNING: MCP schema registries not found; skipping tool reference checks.", file=sys.stderr)
        skill_names = set(seen)
        agents_skills_dir = self.repo_root / ".agents" / "skills"
        project_skill_files: list[Path] = []
        if agents_skills_dir.is_dir():
            for entry in sorted(agents_skills_dir.iterdir()):
                if entry.is_dir():
                    skill_names.add(entry.name)
                    skill_file = entry / "SKILL.md"
                    if skill_file.is_file():
                        project_skill_files.append(skill_file)

        for skill_file in project_skill_files:
            source_label = str(skill_file.relative_to(self.repo_root))
            try:
                frontmatter.validate_frontmatter(skill_file.read_text(), source_label)
            except ValueError as e:
                errors.append(str(e))

        jinja_env = rendering._create_jinja_env()

        for skill in skills:
            lint_files = self._collect_lint_files(skill)

            if skill.depth == 1:
                errors.extend(reference_links._check_reference_links(skill.source_file, self.repo_root))

            for file_path in lint_files:
                source_label = str(file_path.relative_to(self.repo_root))

                try:
                    source_files._assert_text_file(file_path)
                except ValueError as e:
                    errors.append(str(e))
                    continue

                if file_path.suffix == ".j2":
                    raw = file_path.read_text()
                    try:
                        jinja_env.parse(raw)
                    except TemplateSyntaxError as e:
                        errors.append(f"Jinja2 syntax error in {source_label}: {e}")

                if tool_names is not None and (file_path.name.endswith(".md") or file_path.name.endswith(".md.j2")):
                    reference_findings.extend(
                        tool_references._check_tool_references(
                            file_path.read_text(), source_label, tool_names, skill_names
                        )
                    )

            if skill.source_file.suffix != ".j2":
                raw = skill.source_file.read_text()
                source_label = str(skill.source_file.relative_to(self.repo_root))
                try:
                    frontmatter.validate_frontmatter(raw, source_label)
                except ValueError as e:
                    errors.append(str(e))

        # Tool/skill reference findings are advisory: they are surfaced (as CI annotations on the
        # offending line, or plain warnings locally) but never fail the lint, because the check is a
        # heuristic that can misfire on prose.
        tool_references._emit_reference_findings(reference_findings)

        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return False

        print(f"OK: {len(skills)} product skill(s) and {len(project_skill_files)} project skill(s) passed lint checks.")
        return True

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
                metadata, _ = frontmatter.parse_frontmatter(match.source_file.read_text())
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
