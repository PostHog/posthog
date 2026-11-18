"""Lint for markdown links that will not resolve in the built bundle."""

from __future__ import annotations

import re
from pathlib import Path

from . import source_files

_MARKDOWN_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def _bundled_paths(skill_dir: Path) -> set[str]:
    """The references/ and scripts/ paths a skill ships, as they appear in the built bundle."""
    # The build strips .j2 when it renders a template, so record the shipped path.
    return {
        str(file_path.relative_to(skill_dir)).removesuffix(".j2") for file_path in source_files._bundle_files(skill_dir)
    }


def _bundled_link_target(target: str, skill_dir: Path) -> str | None:
    """The bundle-relative path a markdown link points at, or None if the bundle does not carry it."""
    if not target or "://" in target or target.startswith("mailto:"):
        return None
    resolved = (skill_dir / target).resolve()
    try:
        rel_to_skill = resolved.relative_to(skill_dir.resolve())
    except ValueError:
        return None  # Link points outside the skill; not part of the bundle.
    if not rel_to_skill.parts or rel_to_skill.parts[0] not in source_files._ALLOWED_SUBDIRS:
        return None  # Only references/ and scripts/ files ship in the bundle.
    if resolved.is_dir():
        return None  # A directory ships through its files.
    return str(rel_to_skill)


def _check_reference_links(entry: Path, repo_root: Path) -> list[str]:
    """Find markdown links to references/ or scripts/ files that will not exist in the built bundle.

    A skill ships its SKILL.md, references/, and scripts/ files, and the build strips the .j2 suffix
    from every rendered template. So a link to `references/x.md` resolves when the source holds either
    `references/x.md` or `references/x.md.j2`, but a link to `references/x.md.j2` never resolves,
    because the bundle only has the stripped `references/x.md`.
    """
    skill_dir = entry.parent
    bundle = _bundled_paths(skill_dir)

    # Only the SKILL.md entry point is scanned. Reference files link to each other with paths
    # relative to the skill root, which do not resolve from inside references/, and their code
    # snippets hold `](...)` fragments that are not links.
    errors: list[str] = []
    text = entry.read_text()
    source_label = str(entry.relative_to(repo_root))
    for match in _MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1).split("#", 1)[0].split("?", 1)[0]
        rel_to_skill = _bundled_link_target(target, skill_dir)
        if rel_to_skill is None or rel_to_skill in bundle:
            continue
        position = source_files._line_col(text, match.start(1))
        hint = (
            "Link to the built '.md' path, not the '.md.j2' template."
            if target.endswith(".j2")
            else "No file of that name ships in the skill."
        )
        errors.append(
            f"Broken reference link in {source_label}:{position.line}: "
            f"'{target}' does not resolve to a bundled file. {hint}"
        )
    return errors
