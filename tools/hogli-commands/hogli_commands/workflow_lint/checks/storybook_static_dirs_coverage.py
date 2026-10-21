"""The Storybook ``frontend`` filter must cover every ``staticDirs`` source.

Storybook serves a ``staticDirs`` entry as plain files, so it never enters the
Vite module graph. When the ``frontend`` filter in ``ci-storybook.yml`` misses
one of those trees, a PR that changes only that tree skips Storybook, the merge
queue's ``trunk-merge/**`` run skips it for the same reason, and the visual
change reaches master without review. Every later queue run that does run
Storybook then fails on the unreviewed snapshots.

Entries under ``node_modules`` are skipped, because a dependency change reaches
the filter through ``package.json``.
"""

from __future__ import annotations

import re
from pathlib import Path

from hogli.manifest import REPO_ROOT

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow, parse_filters
from .mcp_filter_coverage import _covers, _repo_relative

STORYBOOK_MAIN = Path("common/storybook/.storybook/main.ts")
WORKFLOW = "ci-storybook.yml"
FILTER = "frontend"

STATIC_DIRS = re.compile(r"staticDirs:\s*\[(?P<body>.*?)\n\s*\]", re.DOTALL)
STATIC_DIR_STRING = re.compile(r"""(?P<to>\bto:\s*)?['"](?P<path>[^'"]+)['"]""")
LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)
BRACES = re.compile(r"\{([^{}]*)\}")
MAX_BRACE_EXPANSIONS = 256


class StorybookStaticDirsCoverageCheck(WorkflowCheck):
    id = "WF013-storybook-static-dirs-coverage"
    label = "Storybook filter covers staticDirs"
    description = "every staticDirs source in the Storybook config is covered by ci-storybook.yml's frontend filter"

    def __init__(self, repo_root: Path | None = None) -> None:
        self._repo_root = repo_root or REPO_ROOT

    @property
    def fix_hint(self) -> str | None:
        return (
            f"Add a '<dir>/**' pattern for each listed path to the '{FILTER}' filter in {WORKFLOW}, "
            "and add the path to FULL_RUN_PATTERNS in bin/find-affected-stories so the story "
            "selector does not narrow the run to zero stories."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        try:
            config = (self._repo_root / STORYBOOK_MAIN).read_text(encoding="utf-8")
        except OSError:
            return result
        sources = _static_dir_sources(config)
        if not sources:
            # Reading no sources would pass every filter without checking anything.
            result.issues.append(
                Issue(
                    workflow=WORKFLOW,
                    message=f"{STORYBOOK_MAIN} has no readable staticDirs entries, so this check verifies nothing",
                    file=str(STORYBOOK_MAIN),
                )
            )
            return result

        wf = next((w for w in workflows if w.path.name == WORKFLOW), None)
        if wf is None:
            result.issues.append(
                Issue(workflow=WORKFLOW, message="workflow not found; cannot verify staticDirs coverage")
            )
            return result
        patterns = _filter_patterns(wf)
        for source in sources:
            if any(_covers(pattern, source, needs_directory=True) for pattern in patterns):
                continue
            result.issues.append(
                Issue(
                    workflow=WORKFLOW,
                    message=(
                        f"Storybook serves '{source}' as a static dir, and no pattern in the "
                        f"'{FILTER}' filter covers it, so a change there skips Storybook"
                    ),
                    file=str(wf.path),
                )
            )
        return result


def _static_dir_sources(config: str) -> list[str]:
    """Repo-relative source directories of the ``staticDirs`` entries, ``node_modules`` excluded."""
    match = STATIC_DIRS.search(LINE_COMMENT.sub("", config))
    if match is None:
        return []
    sources: list[str] = []
    for entry in STATIC_DIR_STRING.finditer(match.group("body")):
        if entry.group("to"):
            continue
        # Storybook resolves staticDirs against the config directory.
        source = _repo_relative(STORYBOOK_MAIN.parent, entry.group("path"))
        if source is None or "node_modules" in source.split("/"):
            continue
        sources.append(source)
    return sources


def _filter_patterns(wf: Workflow) -> list[str]:
    """Positive globs of the ``frontend`` filter, with ``{a,b}`` groups expanded."""
    patterns: list[str] = []
    for job in wf.jobs:
        for step in job.steps:
            filters = parse_filters(step.with_.get("filters")) if step.with_ is not None else None
            entries = filters.get(FILTER) if filters is not None else None
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, str) and not entry.startswith("!"):
                    patterns.extend(_expand_braces(entry))
    return patterns


def _expand_braces(pattern: str) -> list[str]:
    # The filter comes from the PR under lint, so an entry with many brace groups must not
    # expand into millions of globs. An entry over the cap stays unexpanded and covers nothing.
    expansions = 1
    for group in BRACES.findall(pattern):
        expansions *= len(group.split(","))
        if expansions > MAX_BRACE_EXPANSIONS:
            return [pattern]
    match = BRACES.search(pattern)
    if match is None:
        return [pattern]
    head, tail = pattern[: match.start()], pattern[match.end() :]
    return [expanded for option in match.group(1).split(",") for expanded in _expand_braces(head + option + tail)]


__all__ = ["StorybookStaticDirsCoverageCheck"]
