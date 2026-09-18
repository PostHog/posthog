"""File-size nudge, scoped to changed files.

An agent reads a file, never a function, so file length is what decides how many
tokens a change costs to make. This reports two things and never fails a build:

* a warning when the diff itself pushed a file past ``CROSSED_AT``, which is the
  only case the author can act on in the change they are making.
* a single note when the diff touches a file already past ``NOTE_AT``, so the
  reading cost is visible without repeating it for every such file.

Reporting every oversized file instead would fire on about three quarters of
commits, which is how a warning turns into wallpaper.

    hogli lint:size                     # changed files vs origin/master
    hogli lint:size path/to/file.py     # explicit files
    hogli lint:size --against <ref>     # explicit diff base
"""

from __future__ import annotations

import os
import json
import subprocess
from dataclasses import asdict, dataclass
from typing import Final

import click
from hogli.manifest import REPO_ROOT

from hogli_commands.change_detection import changed_files, matches_globs

CROSSED_AT: Final = 1000
NOTE_AT: Final = 1500

# Code in this repo tokenizes at roughly 11 to 13 tokens per line. The estimate only
# has to be good enough to tell a 3k-token file from a 60k-token one.
TOKENS_PER_LINE: Final = 12

SCOPE: Final = (
    "posthog/*.py",
    "ee/*.py",
    "products/*.py",
    "frontend/*.ts",
    "frontend/*.tsx",
    "ee/*.ts",
    "ee/*.tsx",
    "products/*.ts",
    "products/*.tsx",
)

# Generated and vendored trees have no author to nudge, and splitting them is wrong.
# products/desktop is linted by its own Biome setup.
EXCLUDED: Final = (
    "*/migrations/*",
    "*/generated/*",
    "*/node_modules/*",
    "*.d.ts",
    "products/desktop/*",
    "posthog/schema.py",
    "posthog/schema_enums.py",
)


@dataclass(frozen=True, kw_only=True, slots=True)
class RenameMaps:
    """Where a path came from, one hop per namespace.

    The two maps stay apart because they describe different namespaces. Merging them
    would join two unrelated files whenever a rename reuses a pathname another rename
    just vacated.
    """

    staged: dict[str, str]  # index path -> its name at HEAD
    committed: dict[str, str]  # HEAD path -> its name at the merge base

    def path_at_base(self, path: str) -> str:
        at_head = self.staged.get(path, path)
        return self.committed.get(at_head, at_head)


@dataclass(frozen=True, kw_only=True, slots=True)
class Finding:
    file: str
    lines: int
    was: int  # line count at the merge base; 0 when the file is new there
    crossed: bool


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


def _merge_base(against: str | None) -> str | None:
    """The commit the branch forked from, or None when no base ref is available.

    Without a base there is no "before" size, so the crossed check cannot run. That
    happens in single-branch clones and bare sandboxes.
    """
    for ref in [against] if against is not None else ["origin/master", "master"]:
        result = _git("merge-base", ref, "HEAD")
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _rename_map(*diff_args: str) -> dict[str, str]:
    result = _git("diff", "-M", "--name-status", "-z", *diff_args)
    if result.returncode != 0:
        return {}
    fields = [field for field in result.stdout.split("\0") if field]
    sources: dict[str, str] = {}
    index = 0
    while index < len(fields):
        # Renames and copies carry two paths; every other status carries one.
        if fields[index].startswith(("R", "C")) and index + 2 < len(fields):
            sources[fields[index + 2]] = fields[index + 1]
            index += 3
        else:
            index += 2
    return sources


def _rename_maps(base: str) -> RenameMaps:
    """Rename sources for the two hops between the merge base and the index.

    Nearly half of all threshold crossings are file moves. Without them, relocating a
    large file reads as creating one, and every product migration gets nudged for
    tidying up. The index is read as well as the committed range, because a staged
    `git mv` has no committed rename to find yet. A move that is neither committed nor
    staged stays undetectable, because git has no rename to report until one side is
    recorded.
    """
    return RenameMaps(staged=_rename_map("--cached", "HEAD"), committed=_rename_map(f"{base}...HEAD"))


def _lines_at(rev: str, path: str) -> int:
    result = _git("show", f"{rev}:{path}")
    return 0 if result.returncode != 0 else len(result.stdout.splitlines())


def _line_count(path: str, rev: str | None) -> int:
    """Size of *path*, read from *rev* when one is named and from disk otherwise.

    Which copy to read follows the caller's scope. A pre-push run carries only commits,
    so it reads the commit and an uncommitted edit cannot move the number away from
    what gets pushed. A run that includes the working tree measures the working tree,
    so growth that is not committed yet is still reported. A path with no blob at *rev*
    is not committed at all, so it counts as zero and drops out rather than falling
    back to disk, which would report content the caller did not ask about.
    """
    if rev is not None:
        result = _git("show", f"{rev}:{path}")
        return 0 if result.returncode != 0 else len(result.stdout.splitlines())
    return len((REPO_ROOT / path).read_text(errors="replace").splitlines())


def _findings(files: list[str], base: str | None, rev: str | None = None) -> list[Finding]:
    """Every crossing, plus at most one note for the largest already-oversized file."""
    renames = _rename_maps(base) if base is not None else RenameMaps(staged={}, committed={})
    crossings: list[Finding] = []
    already_large: list[Finding] = []
    for path in files:
        lines = _line_count(path, rev)
        # CROSSED_AT is the lower of the two thresholds, so nothing under it is reportable.
        if lines <= CROSSED_AT:
            continue
        was = _lines_at(base, renames.path_at_base(path)) if base is not None else 0
        # Without a base there is no "before" size, so nothing can be called a crossing.
        if base is not None and was <= CROSSED_AT:
            crossings.append(Finding(file=path, lines=lines, was=was, crossed=True))
        elif lines > NOTE_AT:
            already_large.append(Finding(file=path, lines=lines, was=was, crossed=False))
    worst = max(already_large, key=lambda finding: finding.lines, default=None)
    return crossings + ([worst] if worst is not None else [])


def _tokens(lines: int) -> str:
    tokens = lines * TOKENS_PER_LINE
    return f"~{tokens // 1000}k tokens" if tokens >= 1000 else f"~{tokens} tokens"


def _message(finding: Finding) -> str:
    # The path is already in the `file:line:col:` prefix, so it is not repeated here.
    if not finding.crossed:
        return f"{finding.lines} lines ({_tokens(finding.lines)} to read)"
    grew = "new file" if finding.was == 0 else f"up from {finding.was}"
    return (
        f"now {finding.lines} lines ({grew}), past {CROSSED_AT} ({_tokens(finding.lines)} to read). "
        "Consider splitting it: /splitting-oversized-modules"
    )


def _report(finding: Finding) -> None:
    label = "warning" if finding.crossed else "note"
    message = _message(finding)
    click.echo(f"{finding.file}:1:1: {label}: {message}")
    # Only a crossing is this diff's doing, so only a crossing annotates the diff.
    if finding.crossed and os.environ.get("GITHUB_ACTIONS") == "true":
        click.echo(f"::warning file={finding.file},line=1,col=1,title=lint:size::{message}")


@click.command(name="lint:size", help="Check the size of changed Python/TypeScript files (warn-only).")
@click.argument("files", nargs=-1)
@click.option("--against", default=None, help="Diff against this base ref instead of the branch default.")
@click.option(
    "--committed",
    is_flag=True,
    help="Measure the committed file at HEAD instead of the working tree, for pre-push checks.",
)
@click.option(
    "--report",
    "report_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Also write the findings as JSON to this path (used by the CI report poster).",
)
def cmd_lint_size(files: tuple[str, ...], against: str | None, committed: bool, report_path: str | None) -> None:
    base = _merge_base(against)
    # Explicit files skip changed_files, which is what would otherwise reject a bad ref.
    # Degrading here instead would turn crossing detection off without saying so, and a
    # ref that resolves but shares no history fails the same way a typo does.
    if against is not None and base is None:
        raise click.UsageError(f"no merge base with {against!r}: check the ref exists and shares history")
    # Committed-only mode must not discover uncommitted work either, or a staged file
    # would be selected and then measured as zero, which reads as a silent skip.
    paths = list(files) if files else changed_files(against, include_worktree=not committed)
    in_scope = [
        path
        for path in paths
        if (REPO_ROOT / path).is_file() and matches_globs(path, SCOPE) and not matches_globs(path, EXCLUDED)
    ]

    if in_scope and base is None:
        # Printed to stdout so a soft preflight check reports a degraded run as a
        # warning rather than a silent pass.
        click.echo(f"size: no base ref, so only files over {NOTE_AT} lines are reported")

    findings = _findings(in_scope, base, rev="HEAD" if committed else None)
    for finding in findings:
        _report(finding)
    click.echo(f"size: {len(in_scope)} file(s) checked, {len(findings)} finding(s)", err=True)
    if report_path is not None:
        with open(report_path, "w") as report_file:
            json.dump([asdict(finding) for finding in findings], report_file)
