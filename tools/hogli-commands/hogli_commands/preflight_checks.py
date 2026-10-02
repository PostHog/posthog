"""``ci:preflight`` checks that read the diff itself instead of running one command over it."""

from __future__ import annotations

import os
import re
import json
import shutil
import tempfile
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hogli.manifest import REPO_ROOT

from hogli_commands.change_detection import matches_globs

Status = Literal["pass", "fail", "warning", "advisory", "skipped"]
Outcome = tuple[Status, str]


@dataclass(frozen=True, kw_only=True, slots=True)
class Scope:
    """What a push carries: the matched files, the commit they are diffed from, and which copy to read."""

    files: list[str]
    changed: list[str]
    merge_base: str
    committed_only: bool


@dataclass(frozen=True, kw_only=True, slots=True)
class FunctionCheck:
    key: str
    label: str
    triggers: list[str]
    run: Callable[[Scope], Outcome]


def _git(*args: str, timeout: float = 20.0) -> bytes | None:
    try:
        result = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _head_copy(path: str, committed_only: bool) -> bytes | None:
    if committed_only:
        return _git("show", f"HEAD:{path}")
    target = REPO_ROOT / path
    return target.read_bytes() if target.is_file() else None


def _renamed_from(merge_base: str) -> dict[str, str]:
    """New path to old path, for every file the branch's commits renamed."""
    out = _git("diff", "--name-status", "-z", "-M", merge_base, "HEAD")
    if out is None:
        return {}
    fields = out.decode(errors="replace").split("\0")
    renames: dict[str, str] = {}
    index = 0
    while index < len(fields):
        if fields[index].startswith(("R", "C")) and index + 2 < len(fields):
            if fields[index].startswith("R"):
                renames[fields[index + 2]] = fields[index + 1]
            index += 3
        else:
            index += 2
    return renames


SNAPSHOT_MANIFEST = "frontend/snapshots.yml"
# A story identifier comes from the story file's title and export names, and the Storybook
# config decides which story files load. A removal that touches none of these deleted no story.
STORY_SOURCES = ["*.stories.*", ".storybook/*", "common/storybook/*"]
_SNAPSHOT_ENTRY = re.compile(r"^    ([^\s#:][^:\n]*):[ \t]*$", re.MULTILINE)


def _snapshot_identifiers(manifest: bytes) -> set[str]:
    return set(_SNAPSHOT_ENTRY.findall(manifest.decode(errors="replace")))


def check_snapshot_baselines(scope: Scope) -> Outcome:
    before = _git("show", f"{scope.merge_base}:{SNAPSHOT_MANIFEST}")
    after = _head_copy(SNAPSHOT_MANIFEST, scope.committed_only)
    if before is None or after is None:
        return "skipped", f"could not read {SNAPSHOT_MANIFEST} on both sides"

    removed = sorted(_snapshot_identifiers(before) - _snapshot_identifiers(after))
    if not removed:
        return "pass", "no baseline entries removed"
    count = f"{len(removed)} baseline {'entry' if len(removed) == 1 else 'entries'} removed"
    if any(matches_globs(path, STORY_SOURCES) for path in scope.changed):
        return "pass", f"{count} alongside a story change"
    return (
        "fail",
        f"{count} but no story file changed (e.g. {removed[0]}). "
        "The stories still render, so the merge queue fails every batch that carries this file. "
        f"Restore the entries from `git show {scope.merge_base[:12]}:{SNAPSHOT_MANIFEST}`",
    )


SEMGREP_WORKFLOW = ".github/workflows/ci-security.yaml"
SEMGREP_RULES = ".semgrep/rules/devex"
# The directories the `semgrep-devex` CI job scans.
SEMGREP_SCOPE = [
    f"{root}/*"
    for root in (
        "bin",
        "common",
        "docs/onboarding",
        "ee",
        "frontend",
        "packages",
        "posthog",
        "products",
        "services",
        "tools",
    )
]
# CI excludes this tree from its blocking pass over ERROR rules.
SEMGREP_EXCLUDED = ["products/desktop/*"]
_SEMGREP_IMAGE = re.compile(r"SEMGREP_IMAGE:\s*semgrep/semgrep:([0-9][0-9A-Za-z.\-]*)")
_SEMGREP_TIMEOUT_SECONDS = 300

# One finding: the rule, the file, and the source text it matched.
Finding = tuple[str, str, str]


def _semgrep_version() -> str | None:
    """The version CI pins, so a local run and the CI job apply the same rule semantics."""
    try:
        match = _SEMGREP_IMAGE.search((REPO_ROOT / SEMGREP_WORKFLOW).read_text())
    except OSError:
        return None
    return match.group(1) if match else None


def _semgrep_findings(semgrep: list[str], root: Path) -> dict[Finding, list[int]] | None:
    """Findings under *root*, each with the lines it starts on. None when the scan did not run.

    The target is the directory and not the files in it. Semgrep applies its default
    ignore list (``tests/``, ``node_modules/``, minified files) to a directory it walks,
    which is how CI scans, and skips that list for a file named on the command line.
    """
    try:
        result = subprocess.run(
            [
                *semgrep,
                "--config",
                str(REPO_ROOT / SEMGREP_RULES),
                "--severity=WARNING",
                "--severity=ERROR",
                "--metrics=off",
                "--quiet",
                "--json",
                ".",
            ],
            cwd=root,
            env={**os.environ, "SEMGREP_ENABLE_VERSION_CHECK": "false"},
            capture_output=True,
            text=True,
            timeout=_SEMGREP_TIMEOUT_SECONDS,
        )
        findings: dict[Finding, list[int]] = {}
        sources: dict[str, list[str]] = {}
        for item in json.loads(result.stdout)["results"]:
            path = item["path"]
            if path not in sources:
                sources[path] = (root / path).read_text(errors="replace").splitlines()
            start, end = item["start"]["line"], item["end"]["line"]
            matched = "\n".join(line.strip() for line in sources[path][start - 1 : end])
            # The id prefix encodes the rule file's path relative to the working directory.
            # The last segment is the rule's own id.
            rule = item["check_id"].rsplit(".", 1)[-1]
            findings.setdefault((rule, path, matched), []).append(start)
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        # A missing uvx download, a crash and a timeout all end here, because none of them prints a report.
        return None
    return findings


def _write_tree(root: Path, contents: dict[str, bytes | None]) -> None:
    for path, content in contents.items():
        if content is None:
            continue
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def check_semgrep_devex(scope: Scope) -> Outcome:
    files = [f for f in scope.files if not matches_globs(f, SEMGREP_EXCLUDED)]
    after_contents = {path: _head_copy(path, scope.committed_only) for path in files}
    if not any(content is not None for content in after_contents.values()):
        return "skipped", "no file to scan"
    if shutil.which("uvx") is None:
        return "skipped", "uvx not found"
    version = _semgrep_version()
    if version is None:
        return "skipped", f"no semgrep version pinned in {SEMGREP_WORKFLOW}"
    semgrep = ["uvx", f"semgrep@{version}"]

    # CI blocks only on findings the branch introduced, and gets them from `--baseline-commit`.
    # That flag is not usable here: on a clean checkout semgrep runs `git reset --hard` to the
    # baseline and back, and otherwise it checks the whole repository out again. Scanning the
    # merge-base copies of the changed files gives the same comparison without touching the checkout.
    renames = _renamed_from(scope.merge_base)
    before_contents = {
        path: _git("show", f"{scope.merge_base}:{renames.get(path, path)}")
        for path, content in after_contents.items()
        if content is not None
    }
    with tempfile.TemporaryDirectory() as tmp:
        roots = [Path(tmp) / "before", Path(tmp) / "after"]
        for root, contents in zip(roots, (before_contents, after_contents)):
            root.mkdir()
            _write_tree(root, contents)
        with ThreadPoolExecutor(max_workers=2) as pool:
            before, after = pool.map(lambda root: _semgrep_findings(semgrep, root), roots)
    if before is None or after is None:
        return "skipped", "semgrep did not produce a report (it needs network on its first run)"

    introduced = [
        f"{rule} at {path}:{line}"
        for (rule, path, matched), lines in sorted(after.items())
        for line in lines[len(before.get((rule, path, matched), [])) :]
    ]
    if not introduced:
        return "pass", "no new findings"
    more = f" (+{len(introduced) - 3} more)" if len(introduced) > 3 else ""
    return "fail", f"{len(introduced)} new finding(s): {' · '.join(introduced[:3])}{more}"


LANE_TARGETS_SCRIPT = ".github/scripts/trunk-impacted-targets.js"
LANE_SUMMARY_SCRIPT = ".github/scripts/trunk-lane-telemetry.js"
_LANE_TIMEOUT_SECONDS = 120


def _node(script: str, files: list[str], env: dict[str, str]) -> object:
    result = subprocess.run(
        ["node", script],
        cwd=REPO_ROOT,
        env=env,
        input="\n".join(files),
        capture_output=True,
        text=True,
        timeout=_LANE_TIMEOUT_SECONDS,
    )
    return json.loads(result.stdout)


def check_merge_queue_lane(scope: Scope) -> Outcome:
    if shutil.which("node") is None:
        return "skipped", "node not found"
    # CI lists a rename as its old path and its new one, and the old path can widen the lane.
    changed = sorted({*scope.changed, *_renamed_from(scope.merge_base).values()})
    env = {**os.environ, "LANE_MERGE_BASE": scope.merge_base}
    try:
        targets = _node(LANE_TARGETS_SCRIPT, changed, env)
        lane = _node(
            LANE_SUMMARY_SCRIPT, changed, {**env, "IMPACTED_TARGETS": json.dumps({"impactedTargets": targets})}
        )
        if not isinstance(lane, dict):
            return "skipped", "could not compute the merge queue lane"
        if not lane.get("is_all"):
            return "pass", f"claims {lane.get('target_count', 0)} merge queue lane target(s)"

        # The summary names every file that some widening rule matched, which is not proof that
        # those files caused it. Recomputing without them is.
        suspects = set(lane.get("tripwire_files") or [])
        rest = [path for path in changed if path not in suspects]
        narrowed = _node(LANE_TARGETS_SCRIPT, rest, env) if suspects and rest else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return "skipped", "could not compute the merge queue lane"

    if not isinstance(targets, list) or not isinstance(narrowed, list) or len(narrowed) >= len(targets):
        return "pass", "claims every merge queue lane, and splitting the PR would not narrow it"
    return (
        "warning",
        f"claims every merge queue lane because of {', '.join(sorted(suspects)[:3])}. "
        "The whole queue then merges in series behind this PR. "
        f"In their own PR, the other changes claim {len(narrowed)} of {len(targets)} lane targets",
    )


FUNCTION_CHECKS: list[FunctionCheck] = [
    FunctionCheck(
        key="snapshot-baselines",
        label="visual baselines dropped from snapshots.yml (fails every merge queue batch)",
        triggers=[SNAPSHOT_MANIFEST],
        run=check_snapshot_baselines,
    ),
    FunctionCheck(
        key="semgrep-devex",
        label="new semgrep findings (devex rules)",
        triggers=SEMGREP_SCOPE,
        run=check_semgrep_devex,
    ),
    FunctionCheck(
        key="merge-queue-lane",
        label="merge queue lane this diff claims",
        triggers=["*"],
        run=check_merge_queue_lane,
    ),
]
