"""The names of the skills this repository bundles.

`hogli build:skills` renders every skill under `products/*/skills/` into `dist/skills.zip`, which
ships to the agent hosts. A host loads those skills next to the store skills of the team it runs
for, in one flat name space, so the two sets cannot both hold a name: the skills store reads this
set to keep a store skill from taking a bundled one.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

# Skills authored in PostHog/context-mill. Every shipping consumer unzips this
# repo's skills first and then unzips the context-mill release on top, so a
# same-named skill here is overwritten instead of shipped — a failure that is
# silent without this check, because the copy still builds and still publishes.
OMNIBUS_SKILL_NAMES = frozenset(
    {
        "instrument-integration",
        "instrument-product-analytics",
        "instrument-feature-flags",
        "instrument-error-tracking",
        "instrument-llm-analytics",
        "instrument-logs",
    }
)

# The products tree, resolved from this file at products/skills/backend/bundled_skills.py.
_PRODUCTS_DIR = Path(__file__).resolve().parents[2]
# Markdown that sits beside skills without being a skill.
_NON_SKILL_FILES = frozenset({"README.md", "AGENTS.md", "CLAUDE.md"})
# Frontmatter opens the entry point, so a bounded read always holds it.
_FRONTMATTER_READ_BYTES = 4096


def _entry_point(path: Path) -> Path | None:
    """Return the file a skill is built from, or None when `path` holds no skill.

    Mirrors `SkillDiscoverer.discover` in products/posthog_ai/scripts/build_skills.py: a skill is
    a directory holding a SKILL.md(.j2), or a loose <name>.md(.j2) file. The two walks must agree,
    because a skill the build ships and this walk misses is a name the skills store hands out.
    """
    if path.is_dir():
        for candidate in (path / "SKILL.md.j2", path / "SKILL.md"):
            if candidate.is_file():
                return candidate
        return None
    if path.name in _NON_SKILL_FILES or not path.name.endswith((".md", ".md.j2")):
        return None
    return path


def _declared_name(entry_point: Path) -> str | None:
    """Return the `name` field of the entry point's YAML frontmatter, or None when it has none.

    `SkillBuilder.build_skill` ships a skill under its frontmatter name rather than its path name,
    and the two differ for a loose entry point: products/customer_analytics/skills/SKILL.md ships
    as `adding-warehouse-person-properties`.
    """
    try:
        with entry_point.open(encoding="utf-8", errors="replace") as handle:
            head = handle.read(_FRONTMATTER_READ_BYTES)
    except OSError:
        return None
    lines = head.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("name:"):
            return line.removeprefix("name:").strip().strip("\"'") or None
    return None


def _path_name(path: Path) -> str:
    return path.name if path.is_dir() else path.name.removesuffix(".j2").removesuffix(".md")


@cache
def bundled_skill_names() -> frozenset[str]:
    """Every bundled skill name, lowercased.

    Cached because the set is fixed for the life of the process: it only changes with a deploy.
    """
    names = {name.lower() for name in OMNIBUS_SKILL_NAMES}
    for skills_dir in _PRODUCTS_DIR.glob("*/skills"):
        for path in skills_dir.iterdir():
            entry_point = _entry_point(path)
            if entry_point is None:
                continue
            names.add((_declared_name(entry_point) or _path_name(path)).lower())
    return frozenset(names)
