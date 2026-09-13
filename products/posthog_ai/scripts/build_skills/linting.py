# ruff: noqa: T201 allow print statements
"""Validating skill sources without rendering them."""

from __future__ import annotations

import sys
from pathlib import Path

from jinja2 import Environment, TemplateSyntaxError

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


class SkillLinter:
    """Validates skill sources without rendering (no Django needed).

    Checks:
    - Binary file detection (only text files allowed)
    - Duplicate skill name detection (across products)
    - Jinja2 syntax validation via parse-only (all .j2 files)
    - Frontmatter validation for product and project skill entry points
    - Tool/skill reference validation in markdown (against the MCP schema registries)
    """

    def __init__(self, repo_root: Path, skills: list[skill_manifest.DiscoveredSkill]) -> None:
        self.repo_root = repo_root
        self.skills = skills
        self.errors: list[str] = []
        self.findings: list[tool_references.ReferenceFinding] = []
        self.skill_names: set[str] = set()
        self.project_skill_files: list[Path] = []

    def run(self) -> bool:
        """Run every check and report. Returns True if all checks pass."""
        self._check_names()
        tool_names = tool_references._load_mcp_tool_names(self.repo_root)
        if tool_names is None:
            print("WARNING: MCP schema registries not found; skipping tool reference checks.", file=sys.stderr)
        self._collect_project_skills()
        self._check_project_skill_frontmatter()

        jinja_env = rendering._create_jinja_env()
        for skill in self.skills:
            self._check_skill(skill, jinja_env, tool_names)

        # Tool/skill reference findings are advisory: they are surfaced (as CI annotations on the
        # offending line, or plain warnings locally) but never fail the lint, because the check is a
        # heuristic that can misfire on prose.
        tool_references._emit_reference_findings(self.findings)
        return self._report()

    def _label(self, path: Path) -> str:
        return str(path.relative_to(self.repo_root))

    def _check_names(self) -> None:
        """Flag duplicate skill names and names context-mill owns."""
        seen: dict[str, skill_manifest.DiscoveredSkill] = {}
        for skill in self.skills:
            if skill.name in seen:
                self.errors.append(
                    f"Duplicate skill name '{skill.name}': "
                    f"{self._label(seen[skill.name].source_file)} and {self._label(skill.source_file)}"
                )
            else:
                seen[skill.name] = skill

            unrendered_name = discovery._unrendered_skill_name(skill)
            if unrendered_name in reserved_names.OMNIBUS_SKILL_NAMES:
                self.errors.append(
                    reserved_names.reserved_name_message(unrendered_name, self._label(skill.source_file))
                )
        self.skill_names = set(seen)

    def _collect_project_skills(self) -> None:
        """Record the .agents/skills/ names and entry points alongside the product skills."""
        agents_skills_dir = self.repo_root / ".agents" / "skills"
        if not agents_skills_dir.is_dir():
            return
        for entry in sorted(agents_skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            self.skill_names.add(entry.name)
            skill_file = entry / "SKILL.md"
            if skill_file.is_file():
                self.project_skill_files.append(skill_file)

    def _check_project_skill_frontmatter(self) -> None:
        for skill_file in self.project_skill_files:
            try:
                frontmatter.validate_frontmatter(skill_file.read_text(), self._label(skill_file))
            except ValueError as e:
                self.errors.append(str(e))

    def _check_skill(
        self, skill: skill_manifest.DiscoveredSkill, jinja_env: Environment, tool_names: set[str] | None
    ) -> None:
        if skill.depth == 1:
            self.errors.extend(reference_links._check_reference_links(skill.source_file, self.repo_root))

        for file_path in _lint_files(skill):
            self._check_file(file_path, jinja_env, tool_names)

        if skill.source_file.suffix != ".j2":
            try:
                frontmatter.validate_frontmatter(skill.source_file.read_text(), self._label(skill.source_file))
            except ValueError as e:
                self.errors.append(str(e))

    def _check_file(self, file_path: Path, jinja_env: Environment, tool_names: set[str] | None) -> None:
        source_label = self._label(file_path)
        try:
            source_files._assert_text_file(file_path)
        except ValueError as e:
            self.errors.append(str(e))
            return

        if file_path.suffix == ".j2":
            try:
                jinja_env.parse(file_path.read_text())
            except TemplateSyntaxError as e:
                self.errors.append(f"Jinja2 syntax error in {source_label}: {e}")

        if tool_names is not None and file_path.name.endswith((".md", ".md.j2")):
            self.findings.extend(
                tool_references._check_tool_references(
                    file_path.read_text(), source_label, tool_names, self.skill_names
                )
            )

    def _report(self) -> bool:
        if self.errors:
            for err in self.errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return False
        print(
            f"OK: {len(self.skills)} product skill(s) and "
            f"{len(self.project_skill_files)} project skill(s) passed lint checks."
        )
        return True


def _lint_files(skill: skill_manifest.DiscoveredSkill) -> list[Path]:
    """Collect the files to lint for a skill: SKILL.md(.j2), references/ and scripts/."""
    if skill.depth == 0:
        return [skill.source_file]

    return [skill.source_file, *source_files._bundle_files(skill.source_file.parent)]
