"""Lint for markdown links that will not resolve in the built bundle."""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import source_files

_MARKDOWN_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def _check_reference_links(entry: Path, repo_root: Path) -> list[str]:
    """Find markdown links to references/ or scripts/ files that will not exist in the built bundle.

    A skill ships its SKILL.md, references/, and scripts/ files, and the build strips the .j2 suffix
    from every rendered template. So a link to `references/x.md` resolves when the source holds either
    `references/x.md` or `references/x.md.j2`, but a link to `references/x.md.j2` never resolves,
    because the bundle only has the stripped `references/x.md`.
    """
    skill_dir = entry.parent
    bundle: set[str] = set()
    for subdir_name in sorted(source_files._ALLOWED_SUBDIRS):
        subdir = skill_dir / subdir_name
        if not subdir.is_dir():
            continue
        for root, dirs, filenames in os.walk(subdir):
            dirs[:] = sorted(dirs)
            for filename in sorted(filenames):
                # The build strips .j2 when it renders a template, so record the shipped path.
                rel = str((Path(root) / filename).relative_to(skill_dir))
                bundle.add(rel.removesuffix(".j2"))

    # Only the SKILL.md entry point is scanned. Reference files link to each other with paths
    # relative to the skill root, which do not resolve from inside references/, and their code
    # snippets hold `](...)` fragments that are not links.
    errors: list[str] = []
    text = entry.read_text()
    source_label = str(entry.relative_to(repo_root))
    for match in _MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1).split("#", 1)[0].split("?", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        resolved = (skill_dir / target).resolve()
        try:
            rel_to_skill = resolved.relative_to(skill_dir.resolve())
        except ValueError:
            continue  # Link points outside the skill; not part of the bundle.
        if not rel_to_skill.parts or rel_to_skill.parts[0] not in source_files._ALLOWED_SUBDIRS:
            continue  # Only references/ and scripts/ files ship in the bundle.
        if resolved.is_dir():
            continue  # A directory ships through its files.
        if str(rel_to_skill) not in bundle:
            line, _col = source_files._line_col(text, match.start(1))
            hint = (
                "Link to the built '.md' path, not the '.md.j2' template."
                if target.endswith(".j2")
                else "No file of that name ships in the skill."
            )
            errors.append(
                f"Broken reference link in {source_label}:{line}: '{target}' does not resolve to a bundled file. {hint}"
            )
    return errors
