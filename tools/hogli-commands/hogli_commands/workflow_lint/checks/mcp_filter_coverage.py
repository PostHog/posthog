"""The MCP path filters must cover every tree the MCP build compiles.

``services/mcp`` and ``products/*/mcp`` import source out of other trees through
the ``paths`` aliases in ``services/mcp/tsconfig.json``: the quill packages,
shared product frontend code, product data files. That code is compiled by
``tsgo`` under a stricter tsconfig than the frontend's
(``noUncheckedIndexedAccess``, among others), so the frontend lane can be green
on a file the MCP lane rejects.

When a filter misses one of those trees, a PR touching only that tree skips the
MCP jobs, the merge queue's ``trunk-merge/**`` run skips them for the same
reason, and the break lands on master, where it then fails every later PR whose
own diff does trigger the filter.

Imports are read from source rather than from a hand-kept list. A TypeScript
import must be covered by a **directory** pattern (``.../**``), because the
imported module pulls in its own relative imports and only a pattern covering
the enclosing tree brings those along. A data import (JSON) has no such tail, so
a pattern naming the file is enough.

``ci-mcp.yml`` compiles the whole service and ``ci-mcp-ui-apps.yml`` only the UI
apps, so each is judged against the imports of the sources it actually builds.
"""

from __future__ import annotations

import re
import json
import subprocess
from pathlib import Path

from hogli.manifest import REPO_ROOT

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow, parse_filters

MCP_TSCONFIG = Path("services/mcp/tsconfig.json")

# workflow file -> the MCP source roots that workflow compiles
COMPILED_SOURCES: dict[str, tuple[str, ...]] = {
    "ci-mcp.yml": ("services/mcp", "products/*/mcp"),
    "ci-mcp-ui-apps.yml": ("services/mcp/src/ui-apps", "products/*/mcp"),
}

IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*['"](?P<specifier>[^'"]+)['"]""")
JSON_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)
OWN_MCP_TREE = re.compile(r"^(?:services/mcp/|products/[^/]+/mcp/)")
DATA_SUFFIXES = (".json", ".css", ".svg")


class McpFilterCoverageCheck(WorkflowCheck):
    id = "WF009-mcp-filter-coverage"
    label = "MCP filter covers compiled trees"
    description = "every tree the MCP build imports is covered by the MCP workflows' path filters"

    def __init__(self, repo_root: Path | None = None) -> None:
        # Injected so tests can point at a fixture tree without monkeypatching env vars.
        self._repo_root = repo_root or REPO_ROOT

    @property
    def fix_hint(self) -> str | None:
        return (
            "Add a pattern covering each listed path to the named workflow's path filters. For a "
            "TypeScript import, widen to the enclosing directory ('packages/quill/**') rather than "
            "naming the file, so the module's own relative imports come along."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        aliases = _read_path_aliases(self._repo_root)
        if not aliases:
            return result

        for workflow_name, source_roots in COMPILED_SOURCES.items():
            wf = next((w for w in workflows if w.path.name == workflow_name), None)
            if wf is None:
                result.issues.append(
                    Issue(
                        workflow=workflow_name,
                        message="workflow not found; cannot verify that its path filters cover MCP's imports",
                    )
                )
                continue
            patterns = _positive_patterns(wf)
            for target, needs_directory in sorted(_imported(self._repo_root, source_roots, aliases).items()):
                if any(_covers(pattern, target, needs_directory) for pattern in patterns):
                    continue
                result.issues.append(
                    Issue(
                        workflow=workflow_name,
                        message=(
                            f"MCP imports '{target}', which no path filter in this workflow "
                            "covers, so a change there skips the MCP jobs"
                        ),
                        file=str(wf.path),
                    )
                )
        return result


def _read_path_aliases(repo_root: Path) -> dict[str, list[str]]:
    """``compilerOptions.paths`` from the MCP tsconfig, as repo-relative targets."""
    try:
        raw = (repo_root / MCP_TSCONFIG).read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        parsed = json.loads(JSON_LINE_COMMENT.sub("", raw))
    except json.JSONDecodeError:
        return {}
    paths = parsed.get("compilerOptions", {}).get("paths") if isinstance(parsed, dict) else None
    if not isinstance(paths, dict):
        return {}

    base = MCP_TSCONFIG.parent
    aliases: dict[str, list[str]] = {}
    for alias, targets in paths.items():
        if not isinstance(alias, str) or not isinstance(targets, list):
            continue
        resolved = [_repo_relative(base, target) for target in targets if isinstance(target, str)]
        aliases[alias] = [target for target in resolved if target is not None]
    return aliases


def _repo_relative(base: Path, target: str) -> str | None:
    """Resolve a tsconfig target against the tsconfig's dir. None if it escapes the repo."""
    parts: list[str] = []
    for part in Path(base, target).parts:
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def _imported(repo_root: Path, source_roots: tuple[str, ...], aliases: dict[str, list[str]]) -> dict[str, bool]:
    """Paths outside MCP's own trees that these sources import, each with whether a
    directory pattern is required to cover it."""
    required: dict[str, bool] = {}
    for source in _mcp_sources(repo_root, source_roots):
        try:
            text = (repo_root / source).read_text(encoding="utf-8")
        except OSError:
            continue
        for match in IMPORT.finditer(text):
            for resolved in _resolve(match.group("specifier"), aliases):
                if OWN_MCP_TREE.match(resolved) or "node_modules" in resolved.split("/"):
                    continue
                # A data file is a leaf. A module drags its own relative imports
                # along, so every tree the walk reaches has to be covered too.
                if resolved.endswith(DATA_SUFFIXES):
                    required.setdefault(resolved, False)
                    continue
                for module in _relative_closure(repo_root, resolved):
                    required[_enclosing_directory(module)] = True
    return required


def _relative_closure(repo_root: Path, entry: str) -> set[str]:
    """``entry`` plus every module reachable from it through relative imports.

    A module that does not resolve on disk still counts, because a generated or
    built target (quill's ``dist``) is absent from a fresh checkout and dropping it
    would quietly stop requiring coverage of the tree that produces it.
    """
    reached: set[str] = set()
    queue = [entry]
    while queue:
        current = queue.pop()
        if current in reached:
            continue
        reached.add(current)
        module = _resolve_on_disk(repo_root, current)
        if module is None:
            continue
        reached.add(module)
        for match in IMPORT.finditer((repo_root / module).read_text(encoding="utf-8")):
            specifier = match.group("specifier")
            if not specifier.startswith("."):
                continue
            neighbor = _repo_relative(Path(_enclosing_directory(module)), specifier)
            if neighbor is not None and not neighbor.endswith(DATA_SUFFIXES):
                queue.append(neighbor)
    return reached


def _resolve_on_disk(repo_root: Path, module: str) -> str | None:
    """The file a TypeScript module specifier names, extension and index forms included."""
    for candidate in (module, f"{module}.ts", f"{module}.tsx", f"{module}/index.ts", f"{module}/index.tsx"):
        if (repo_root / candidate).is_file():
            return candidate
    return None


def _mcp_sources(repo_root: Path, source_roots: tuple[str, ...]) -> list[str]:
    """TypeScript under the given roots, which may hold ``*`` path segments."""
    return [source for source in _tracked_typescript(repo_root) if _under_any(source, source_roots)]


def _tracked_typescript(repo_root: Path) -> list[str]:
    """Git-tracked TypeScript under the MCP trees, falling back to the filesystem.

    Only tracked files count: CI sees nothing else, and a working tree can carry
    build residue from another branch.
    """
    command = ["git", "ls-files", "-z", "--", "services/mcp", "products"]
    try:
        listing = subprocess.run(command, cwd=repo_root, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return sorted(
            path.relative_to(repo_root).as_posix()
            for root in ("services/mcp", "products")
            for path in repo_root.glob(f"{root}/**/*.ts*")
            if "node_modules" not in path.parts
        )
    return [entry for entry in listing.stdout.split("\0") if entry.endswith((".ts", ".tsx"))]


def _under_any(path: str, roots: tuple[str, ...]) -> bool:
    return any(re.fullmatch(rf"{_to_regex(root)}/.*", path) for root in roots)


def _resolve(specifier: str, aliases: dict[str, list[str]]) -> list[str]:
    """Repo-relative targets a bare import specifier resolves to, via tsconfig aliases."""
    for alias, targets in aliases.items():
        prefix, star, suffix = alias.partition("*")
        if not star:
            if specifier == alias:
                return targets
            continue
        if specifier.startswith(prefix) and specifier.endswith(suffix):
            # endswith already bounds len(suffix), so the end index cannot go negative.
            tail = specifier[len(prefix) : len(specifier) - len(suffix)]
            return [target.replace("*", tail) for target in targets]
    return []


def _enclosing_directory(target: str) -> str:
    """The imported module's directory, which is the unit a filter has to cover."""
    return target.rsplit("/", 1)[0] if "/" in target else target


def _positive_patterns(wf: Workflow) -> list[str]:
    """Every non-negated glob across the workflow's paths-filters."""
    patterns: list[str] = []
    for job in wf.jobs:
        for step in job.steps:
            if step.with_ is None:
                continue
            filters = parse_filters(step.with_.get("filters"))
            if filters is None:
                continue
            for entries in filters.values():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    values = entry.values() if isinstance(entry, dict) else [entry]
                    patterns.extend(v for v in values if isinstance(v, str) and not v.startswith("!"))
    return patterns


def _covers(pattern: str, target: str, needs_directory: bool) -> bool:
    """Does one filter glob cover ``target``?

    A directory glob covers the tree it names; anything else has to name the
    target exactly, and only where a whole tree is not required.
    """
    if pattern.endswith("/**"):
        regex = _to_regex(pattern.removesuffix("/**"))
        return re.fullmatch(regex, target) is not None or re.fullmatch(rf"{regex}/.*", target) is not None
    return not needs_directory and re.fullmatch(_to_regex(pattern), target) is not None


def _to_regex(pattern: str) -> str:
    return re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")


__all__ = ["McpFilterCoverageCheck"]
