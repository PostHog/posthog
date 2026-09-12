"""Finding skill sources under products/*/skills/."""

from __future__ import annotations

from pathlib import Path

import yaml

from . import frontmatter, skill_manifest


def _unrendered_skill_name(skill: skill_manifest.DiscoveredSkill) -> str:
    """Return the entry point's raw frontmatter ``name``, or the path name.

    Not the shipped name. ``SkillBuilder.build_skill`` writes each skill to
    ``dist/skills/<name>`` using the *rendered* frontmatter ``name``, and the lint
    runs without rendering, so a Jinja name such as ``instrument-{{ 'logs' }}``
    comes back here verbatim. ``build_skill`` checks the rendered name against
    ``OMNIBUS_SKILL_NAMES`` (see ``display_name`` there), which is what catches a
    templated reserved name; this function only gives the lint an earlier, cheaper
    shot at the plain case.
    """
    try:
        metadata, _ = frontmatter.parse_frontmatter(skill.source_file.read_text())
    except (OSError, yaml.YAMLError):
        return skill.name
    return metadata.get("name") or skill.name


class SkillDiscoverer:
    """Discovers skill source files from products/*/skills/."""

    def __init__(self, products_dir: Path) -> None:
        self.products_dir = products_dir

    def discover(self) -> list[skill_manifest.DiscoveredSkill]:
        """Discover skill sources from products/*/skills/.

        Supports two depth levels relative to products/*/skills/:
        - Depth 0: Loose files directly in skills/ (e.g., my-skill.md or my-skill.md.j2).
          Skill name = filename stem (without .md or .md.j2 extension).
        - Depth 1: Directories containing SKILL.md(.j2) (e.g., my-skill/SKILL.md).
          Skill name = directory name.

        For both depths, .j2 files take priority over plain .md when both exist.
        """
        skills: list[skill_manifest.DiscoveredSkill] = []

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
                            skill_manifest.DiscoveredSkill(
                                name=entry.name, source_file=j2_file, product_dir=product_dir, depth=1
                            )
                        )
                    elif md_file.exists():
                        skills.append(
                            skill_manifest.DiscoveredSkill(
                                name=entry.name, source_file=md_file, product_dir=product_dir, depth=1
                            )
                        )
                elif (
                    entry.is_file()
                    # Convention docs that can live alongside skills — not skills themselves.
                    and entry.name not in ("README.md", "AGENTS.md", "CLAUDE.md")
                    and (entry.name.endswith(".md.j2") or entry.name.endswith(".md"))
                ):
                    if entry.name.endswith(".md") and (entry.parent / (entry.name + ".j2")).exists():
                        continue
                    skill_name = entry.name.removesuffix(".j2").removesuffix(".md")
                    skills.append(
                        skill_manifest.DiscoveredSkill(
                            name=skill_name, source_file=entry, product_dir=product_dir, depth=0
                        )
                    )

        return skills
